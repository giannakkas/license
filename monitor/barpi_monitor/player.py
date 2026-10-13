"""One libmpv instance per tile, driven from a background poll thread.

The meters are fed by two FFmpeg audio filters inserted in mpv's filter chain:

* ``astats`` tags every audio frame with per-channel peak and RMS level (dBFS)
* ``ebur128`` tags it with EBU R128 momentary and short-term loudness (LUFS)

mpv exposes those tags through the ``af-metadata/<label>`` property, which is read
~25 times a second here. Because the filters sit *before* mute/volume and before the
down-mix to the sound card's layout, a muted 5.1 stream still meters all six channels.

For the picture alarms one raw frame per second is fetched with ``screenshot-raw`` and
reduced to a sparse pixel sample (see ``levels.frame_signature``): identical samples
mean a frozen picture, a dark mean means black, and a failing grab means no video.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .config import Settings, Source
from .levels import SILENCE_FLOOR, frame_signature, parse_astats, parse_r128

log = logging.getLogger(__name__)

AF_CHAIN = (
    "@stats:lavfi=[astats=metadata=1:reset=1:measure_perchannel=Peak_level+RMS_level:measure_overall=none],"
    "@r128:lavfi=[ebur128=metadata=1:framelog=quiet]"
)
POLL_HZ = 25
INFO_EVERY_S = 1.0
PROGRESS_EVERY_S = 0.25
FRAME_EVERY_S = 1.0


class State:
    IDLE = "idle"
    CONNECTING = "connecting"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    STALLED = "stalled"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    ENDED = "ended"


# States during which the operator should see a big red flag on the tile.
ALARM_STATES = {State.STALLED, State.RECONNECTING, State.ERROR}
# States in which a file is loaded and transport controls make sense.
LOADED_STATES = {State.PLAYING, State.PAUSED, State.BUFFERING}


@dataclass
class LevelSnapshot:
    t: float
    peaks: list[float] = field(default_factory=list)
    rms: list[float] = field(default_factory=list)
    momentary: float = SILENCE_FLOOR
    short_term: float = SILENCE_FLOOR
    has_audio: bool = False
    fresh: bool = True     # False when the filter has produced no new frame since the last poll


@dataclass
class StreamInfo:
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vcodec: str = ""
    acodec: str = ""
    samplerate: int = 0
    channels: str = ""
    channel_count: int = 0
    cache_s: float = 0.0
    bitrate_kbps: float = 0.0
    time_pos: float | None = None
    idle: bool = True

    def summary(self) -> str:
        parts = []
        if self.width and self.height:
            fps = f" {self.fps:.3g}p" if self.fps else ""
            parts.append(f"{self.width}×{self.height}{fps}")
        if self.vcodec:
            parts.append(self.vcodec)
        if self.acodec or self.samplerate:
            a = self.acodec or "audio"
            if self.samplerate:
                a += f" {self.samplerate / 1000:.3g} kHz"
            if self.channels:
                a += f" {self.channels}"
            parts.append(a)
        if self.bitrate_kbps >= 1:
            parts.append(f"{self.bitrate_kbps / 1000:.1f} Mb/s" if self.bitrate_kbps >= 1000
                         else f"{self.bitrate_kbps:.0f} kb/s")
        return " · ".join(parts)


@dataclass
class Progress:
    time_pos: float | None = None
    duration: float | None = None   # None for live streams
    paused: bool = False
    seekable: bool = False


@dataclass
class FrameSample:
    t: float
    ok: bool                 # False: no frame could be read (no video track, or nothing decoded yet)
    signature: bytes = b""
    mean: float = 0.0        # mean brightness 0-255


class MpvUnavailable(RuntimeError):
    pass


def import_mpv():
    """Import python-mpv, turning its DLL-not-found error into something we can show."""
    try:
        import mpv  # noqa: WPS433 (deferred so the DLL search path is set up first)
    except OSError as exc:
        raise MpvUnavailable(str(exc)) from exc
    return mpv


class MonitorPlayer(QObject):
    """Plays one source into a native window and reports levels, info and state via signals.

    All signals are emitted from mpv's or the poll thread and are therefore queued onto
    the GUI thread by Qt; slots on this object run on the GUI thread.
    """

    levels = Signal(object)        # LevelSnapshot, ~25 Hz
    devices = Signal(object)       # list of (name, description) audio outputs, once after start
    info = Signal(object)          # StreamInfo, 1 Hz
    progress = Signal(object)      # Progress, 4 Hz
    frame = Signal(object)         # FrameSample, 1 Hz while playing (video analysis on)
    state = Signal(str, str)       # state, detail
    clicked = Signal()
    double_clicked = Signal()

    _end_file = Signal(str, str)   # internal, cross-thread: reason, error text
    _file_loaded = Signal()
    _stalled = Signal(str)

    def __init__(self, wid: int | None, settings: Settings, headless: bool = False, parent=None):
        super().__init__(parent)
        mpv = import_mpv()
        self.settings = settings
        self.source: Source | None = None
        self._state = State.IDLE
        self._detail = ""
        self._closing = False
        self._loading = False
        self._attempts = 0
        self._audible = False
        self._paused = False
        self._last_meta: dict | None = None
        self._last_pos: float | None = None
        self._pos_frozen_since: float | None = None
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._do_load)

        opts: dict = dict(
            af=AF_CHAIN,
            idle="yes",
            osc="no",
            osd_level=1,
            osd_msg1="",
            input_default_bindings="no",
            input_vo_keyboard="no",
            input_cursor="yes",
            keep_open="no",
            ytdl="no",
            mute="yes",
            volume=settings.volume,
            volume_max=130,
        )
        extra: dict = dict(
            hwdec="auto-safe" if settings.hwdec else "no",
            network_timeout=15,
            demuxer_lavf_o="rtsp_transport=tcp",
            stream_lavf_o="reconnect=1,reconnect_streamed=1,reconnect_delay_max=5",
            cache="yes",
            demuxer_max_bytes="64MiB",
            demuxer_max_back_bytes="16MiB",
            cursor_autohide="no",
            osd_font_size=44,
            osd_border_size=2,
            osd_align_x="center",
            osd_align_y="center",
            audio_channels="auto-safe",
            screenshot_sw="yes",       # frame grabs from the decoded picture, not through the VO
        )
        if settings.audio_device and settings.audio_device != "auto":
            extra["audio_device"] = settings.audio_device
        if headless:
            opts.update(vo="null", ao="null")
        elif wid is not None:
            opts["wid"] = int(wid)
        # Options are applied before mpv_initialize, where they cannot block; an option a very old
        # libmpv does not know raises, in which case the core set alone is used.
        try:
            self._mpv = mpv.MPV(log_handler=self._on_log, loglevel="warn", **opts, **extra)
        except Exception as exc:  # noqa: BLE001
            log.warning("libmpv rejected an option (%s); using the basic set", exc)
            self._mpv = mpv.MPV(log_handler=self._on_log, loglevel="warn", **opts)
        self.mpv_version = "libmpv"
        self._devices: list[tuple[str, str]] = [("auto", "Autoselect device")]
        self._devices_read = False

        try:
            self._mpv.event_callback("end-file")(self._on_end_file)
            self._mpv.event_callback("file-loaded")(self._on_file_loaded)
            if not headless:
                # Registered while the core is idle and no window exists yet, so these two
                # synchronous commands cannot wait on anything.
                self._mpv.register_key_binding("MBTN_LEFT", self._on_mouse)
                self._mpv.register_key_binding("MBTN_LEFT_DBL", self._on_mouse_dbl)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not register mpv callbacks: %s", exc)
        if not headless:
            # The video window is created by mpv's own threads; the GUI thread never waits for it.
            self._set_async("force-window", "yes")

        self._end_file.connect(self._handle_end_file)
        self._file_loaded.connect(self._handle_file_loaded)
        self._stalled.connect(self._handle_stalled)

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll_loop, name="mpv-poll", daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- public API

    @property
    def current_state(self) -> str:
        return self._state

    @property
    def is_paused(self) -> bool:
        return self._paused

    def load(self, source: Source) -> None:
        self.source = source
        self._attempts = 0
        self._reconnect_timer.stop()
        self._do_load()

    def stop(self) -> None:
        self._reconnect_timer.stop()
        self._loading = False
        self._command_async("stop")
        self._set_state(State.IDLE, "")

    def set_paused(self, paused: bool) -> None:
        self._set_async("pause", "yes" if paused else "no")

    def set_loop(self, loop: bool) -> None:
        self._set_async("loop-file", "inf" if loop else "no")

    def toggle_pause(self) -> None:
        self.set_paused(not self._paused)

    def seek_relative(self, seconds: float) -> None:
        self._command_async("seek", seconds, "relative")

    def seek_absolute(self, seconds: float) -> None:
        self._command_async("seek", max(0.0, seconds), "absolute")

    def seek_percent(self, percent: float) -> None:
        self._command_async("seek", max(0.0, min(100.0, percent)), "absolute-percent")

    def set_audible(self, audible: bool) -> None:
        self._audible = bool(audible)
        self._set_async("mute", "no" if audible else "yes")

    def set_volume(self, volume: int) -> None:
        self._set_async("volume", max(0, min(130, int(volume))))

    def set_audio_device(self, device: str) -> None:
        self._set_async("audio-device", device or "auto")

    def audio_devices(self) -> list[tuple[str, str]]:
        """The output devices, as last read by the poll thread (see the ``devices`` signal)."""
        return list(self._devices)

    def set_osd_text(self, text: str, color: str = "#FFFFFF") -> None:
        """Big centred text on the video (empty to clear); alarms pass red."""
        self._set_async("osd-color", color)
        self._set_async("osd-msg1", text or "")

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self._set_async("hwdec", "auto-safe" if settings.hwdec else "no")

    def close(self) -> None:
        self._closing = True
        self._reconnect_timer.stop()
        self._stop.set()
        self._thread.join(timeout=1.5)
        try:
            self._mpv.terminate()
        except Exception:  # already dead
            pass

    # ---------------------------------------------------------------- mpv plumbing

    # The GUI thread must never wait for mpv's core: on Windows the core can be waiting for
    # mpv's window thread, which can be waiting for a message the GUI thread has to answer
    # (mpv's video window is a child of a Qt window). So everything the GUI thread asks for
    # is queued with the asynchronous command API and the reply is ignored or logged.

    def _set_async(self, name: str, value) -> None:
        if isinstance(value, bool):
            value = "yes" if value else "no"
        self._command_async("set", name, str(value))

    def _command_async(self, *args) -> None:
        try:
            self._mpv.command_async(*args, callback=self._async_reply)
        except Exception as exc:  # noqa: BLE001 (core already gone)
            log.debug("async command %r not queued: %s", args, exc)

    @staticmethod
    def _async_reply(error, result):
        if error:
            log.debug("mpv command failed: %s", error)
        return result

    def _try_set(self, name: str, value) -> None:
        self._set_async(name, value)

    def _try_command(self, *args) -> None:
        self._command_async(*args)

    def _get(self, name: str, default=None):
        try:
            v = self._mpv._get_property(name)
            return default if v is None else v
        except Exception:
            return default

    @Slot()
    def _do_load(self) -> None:
        if self._closing or self.source is None:
            return
        src = self.source
        self._loading = True
        self._last_meta = None
        self._last_pos = None
        self._pos_frozen_since = None
        self._set_async("loop-file", "inf" if (src.loop and not src.is_stream) else "no")
        self._set_async("pause", "no")
        self._set_state(State.CONNECTING if self._attempts == 0 else State.RECONNECTING,
                        "" if self._attempts == 0 else f"attempt {self._attempts + 1}")
        self._command_async("loadfile", src.url, "replace")

    def _on_log(self, level: str, prefix: str, text: str) -> None:
        text = text.strip()
        if level in ("error", "fatal"):
            log.warning("mpv[%s] %s: %s", self.source.display_name() if self.source else "-", prefix, text)
            self._detail = text

    def _on_end_file(self, event) -> None:  # mpv thread
        try:
            d = event.as_dict(decoder=lambda b: b.decode("utf-8", "replace"))
        except Exception:
            d = {}
        self._end_file.emit(str(d.get("reason", "")), str(d.get("file_error", "")))

    def _on_file_loaded(self, event) -> None:  # mpv thread
        self._file_loaded.emit()

    def _on_mouse(self, state="", *_) -> None:  # mpv thread
        if state and state[0] in ("d", "p"):
            self.clicked.emit()

    def _on_mouse_dbl(self, state="", *_) -> None:  # mpv thread
        if state and state[0] in ("d", "p"):
            self.double_clicked.emit()

    @Slot()
    def _handle_file_loaded(self) -> None:
        self._loading = False
        self._attempts = 0
        self._set_state(State.PAUSED if self._paused else State.PLAYING, "")

    @Slot(str, str)
    def _handle_end_file(self, reason: str, error: str) -> None:
        if self._closing or self.source is None:
            return
        if reason in ("stop", "quit", "redirect"):
            return
        self._loading = False
        if reason == "eof":
            if self.source.is_stream:
                self._set_state(State.ERROR, "stream ended")
                self._schedule_reconnect()
            else:
                self._set_state(State.ENDED, "ended")
            return
        detail = error or self._detail or "playback error"
        self._set_state(State.ERROR, detail)
        if self.source.is_stream or not error.lower().startswith("loading failed"):
            self._schedule_reconnect()

    @Slot(str)
    def _handle_stalled(self, why: str) -> None:
        if self._closing or self.source is None:
            return
        log.warning("%s: %s; reconnecting", self.source.display_name(), why)
        self._try_command("stop")
        self._set_state(State.STALLED, why)
        self._schedule_reconnect(immediate=True)

    def _schedule_reconnect(self, immediate: bool = False) -> None:
        if not self.settings.reconnect or self._closing or self.source is None:
            return
        if not self.source.is_stream and not immediate:
            return  # a broken file will not fix itself
        self._attempts += 1
        delay = 1.0 if immediate else min(2.0 * (2 ** (self._attempts - 1)), 30.0)
        self._set_state(State.RECONNECTING, f"retry {self._attempts} in {delay:.0f}s · {self._detail}".rstrip(" ·"))
        self._reconnect_timer.start(int(delay * 1000))

    def _set_state(self, state: str, detail: str) -> None:
        if state != self._state or detail != self._detail:
            self._state, self._detail = state, detail
            self.state.emit(state, detail)

    # ---------------------------------------------------------------- poll thread

    def _poll_loop(self) -> None:
        period = 1.0 / POLL_HZ
        last_info = last_progress = last_frame = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if not self._devices_read:
                    self._read_static()
                snap = self._read_levels(now)
                if snap is not None:
                    self.levels.emit(snap)
                if now - last_progress >= PROGRESS_EVERY_S:
                    last_progress = now
                    self._read_progress()
                if now - last_info >= INFO_EVERY_S:
                    last_info = now
                    info = self._read_info()
                    self.info.emit(info)
                    self._derive_state(info, now)
                if (self.settings.video_analysis and self._state == State.PLAYING
                        and now - last_frame >= FRAME_EVERY_S):
                    last_frame = now
                    self.frame.emit(self._read_frame(now))
            except Exception:  # never let the meter thread die
                log.exception("poll loop error")
            self._stop.wait(period)

    def _read_static(self) -> None:
        """Things that do not change: the libmpv version and the audio output list."""
        self._devices_read = True
        self.mpv_version = str(self._get("mpv-version", "libmpv"))
        devs = self._get("audio-device-list") or []
        found = [(d.get("name", ""), d.get("description", d.get("name", ""))) for d in devs if isinstance(d, dict)]
        if found:
            self._devices = found
            self.devices.emit(found)

    def _read_levels(self, now: float) -> LevelSnapshot | None:
        if self._loading and self._state not in LOADED_STATES:
            return None
        meta = self._get("af-metadata/stats")
        if not meta:
            if self._state in LOADED_STATES:
                return LevelSnapshot(t=now, has_audio=False)
            return None
        fresh = meta != self._last_meta
        self._last_meta = meta
        peaks, rms = parse_astats(meta)
        mom, short = parse_r128(self._get("af-metadata/r128"))
        return LevelSnapshot(t=now, peaks=peaks, rms=rms, momentary=mom, short_term=short,
                             has_audio=bool(peaks), fresh=fresh)

    def _read_progress(self) -> None:
        if self._state not in LOADED_STATES:
            return
        paused = bool(self._get("pause", False))
        self._paused = paused
        if paused and self._state in (State.PLAYING, State.BUFFERING):
            self._set_state(State.PAUSED, "")
        elif not paused and self._state == State.PAUSED:
            self._set_state(State.PLAYING, "")
        tp = self._get("time-pos")
        dur = self._get("duration")
        self.progress.emit(Progress(time_pos=float(tp) if tp is not None else None,
                                    duration=float(dur) if dur else None,
                                    paused=paused, seekable=bool(self._get("seekable", False))))

    def _read_frame(self, now: float) -> FrameSample:
        try:
            shot = self._mpv.command("screenshot-raw", "video")
            data = shot.get("data") if isinstance(shot, dict) else None
            if not data:
                return FrameSample(t=now, ok=False)
            sig, mean = frame_signature(data)
            return FrameSample(t=now, ok=True, signature=sig, mean=mean)
        except Exception:
            return FrameSample(t=now, ok=False)

    def _read_info(self) -> StreamInfo:
        info = StreamInfo()
        info.idle = bool(self._get("idle-active", True))
        if info.idle:
            return info
        info.width = int(self._get("video-params/w", 0) or 0)
        info.height = int(self._get("video-params/h", 0) or 0)
        info.fps = float(self._get("container-fps", 0.0) or 0.0)
        info.vcodec = str(self._get("video-codec", "") or "").split(" ")[0]
        info.acodec = str(self._get("audio-codec-name", "") or "")
        info.samplerate = int(self._get("audio-params/samplerate", 0) or 0)
        info.channels = str(self._get("audio-params/channels", "") or "")
        info.channel_count = int(self._get("audio-params/channel-count", 0) or 0)
        info.cache_s = float(self._get("demuxer-cache-duration", 0.0) or 0.0)
        vb = float(self._get("video-bitrate", 0.0) or 0.0)
        ab = float(self._get("audio-bitrate", 0.0) or 0.0)
        info.bitrate_kbps = (vb + ab) / 1000.0
        tp = self._get("time-pos")
        info.time_pos = float(tp) if tp is not None else None
        return info

    def _derive_state(self, info: StreamInfo, now: float) -> None:
        """Work out buffering / stalled from playback progress; everything else comes from events."""
        if self._state not in (State.PLAYING, State.BUFFERING):
            self._pos_frozen_since = None
            return
        if info.idle or self._paused:
            return
        paused_for_cache = bool(self._get("paused-for-cache", False))
        pos = info.time_pos
        progressing = pos is not None and (self._last_pos is None or pos != self._last_pos)
        self._last_pos = pos
        if progressing:
            self._pos_frozen_since = None
        elif self._pos_frozen_since is None:
            self._pos_frozen_since = now
        frozen_for = (now - self._pos_frozen_since) if self._pos_frozen_since else 0.0

        if paused_for_cache or (not progressing and frozen_for > 2.0):
            self._set_state(State.BUFFERING, f"buffering {frozen_for:.0f}s" if frozen_for > 2 else "buffering")
            if frozen_for >= self.settings.stall_seconds and self.source and self.source.is_stream:
                self._stalled.emit(f"no data for {frozen_for:.0f}s")
        elif self._state == State.BUFFERING and progressing:
            self._set_state(State.PLAYING, "")
