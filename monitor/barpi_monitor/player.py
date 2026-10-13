"""One libmpv instance per tile, driven from a background poll thread.

The meters are fed by two FFmpeg audio filters inserted in mpv's filter chain:

* ``astats`` tags every audio frame with per-channel peak and RMS level (dBFS)
* ``ebur128`` tags it with EBU R128 momentary and short-term loudness (LUFS)

mpv exposes those tags through the ``af-metadata/<label>`` property, which is read
~25 times a second here. Because the filters sit *before* mute/volume and before the
down-mix to the sound card's layout, a muted 5.1 stream still meters all six channels.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .config import Settings, Source
from .levels import SILENCE_FLOOR, parse_astats, parse_r128

log = logging.getLogger(__name__)

AF_CHAIN = (
    "@stats:lavfi=[astats=metadata=1:reset=1:measure_perchannel=Peak_level+RMS_level:measure_overall=none],"
    "@r128:lavfi=[ebur128=metadata=1:framelog=quiet]"
)
POLL_HZ = 25
INFO_EVERY_S = 1.0


class State:
    IDLE = "idle"
    CONNECTING = "connecting"
    PLAYING = "playing"
    BUFFERING = "buffering"
    STALLED = "stalled"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    ENDED = "ended"


# States during which the operator should see a big red flag on the tile.
ALARM_STATES = {State.STALLED, State.RECONNECTING, State.ERROR}


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

    levels = Signal(object)        # LevelSnapshot
    info = Signal(object)          # StreamInfo
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
        self._last_meta: dict | None = None
        self._last_pos: float | None = None
        self._pos_frozen_since: float | None = None
        self._buffering_since: float | None = None
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
        if headless:
            opts.update(vo="null", ao="null")
        else:
            opts["force_window"] = "yes"
            if wid is not None:
                opts["wid"] = int(wid)
        self._mpv = mpv.MPV(log_handler=self._on_log, loglevel="warn", **opts)

        # Options that may not exist in every libmpv build go in one at a time.
        self._try_set("hwdec", "auto-safe" if settings.hwdec else "no")
        self._try_set("network-timeout", 15)
        self._try_set("demuxer-lavf-o", "rtsp_transport=tcp")
        self._try_set("stream-lavf-o", "reconnect=1,reconnect_streamed=1,reconnect_delay_max=5")
        self._try_set("cache", "yes")
        self._try_set("demuxer-max-bytes", "64MiB")
        self._try_set("demuxer-max-back-bytes", "16MiB")
        self._try_set("cursor-autohide", "no")
        self._try_set("osd-font-size", 44)
        self._try_set("osd-border-size", 2)
        self._try_set("osd-align-x", "center")
        self._try_set("osd-align-y", "center")
        self._try_set("audio-channels", "auto-safe")
        if settings.audio_device and settings.audio_device != "auto":
            self._try_set("audio-device", settings.audio_device)

        self._mpv.event_callback("end-file")(self._on_end_file)
        self._mpv.event_callback("file-loaded")(self._on_file_loaded)
        if not headless:
            self._mpv.register_key_binding("MBTN_LEFT", self._on_mouse)
            self._mpv.register_key_binding("MBTN_LEFT_DBL", self._on_mouse_dbl)

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

    def load(self, source: Source) -> None:
        self.source = source
        self._attempts = 0
        self._reconnect_timer.stop()
        self._do_load()

    def stop(self) -> None:
        self._reconnect_timer.stop()
        self._loading = False
        self._try_command("stop")
        self._set_state(State.IDLE, "")

    def set_audible(self, audible: bool) -> None:
        self._audible = bool(audible)
        self._try_set("mute", "no" if audible else "yes")

    def set_volume(self, volume: int) -> None:
        self._try_set("volume", max(0, min(130, int(volume))))

    def set_audio_device(self, device: str) -> None:
        self._try_set("audio-device", device or "auto")

    def audio_devices(self) -> list[tuple[str, str]]:
        try:
            devs = self._mpv._get_property("audio-device-list") or []
            return [(d.get("name", ""), d.get("description", d.get("name", ""))) for d in devs]
        except Exception:
            return [("auto", "Autoselect device")]

    def set_osd_text(self, text: str) -> None:
        self._try_set("osd-msg1", text or "")

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self._try_set("hwdec", "auto-safe" if settings.hwdec else "no")

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

    def _try_set(self, name: str, value) -> None:
        try:
            self._mpv[name] = value
        except Exception as exc:
            log.debug("option %s=%r rejected: %s", name, value, exc)

    def _try_command(self, *args) -> None:
        try:
            self._mpv.command(*args)
        except Exception as exc:
            log.debug("command %r failed: %s", args, exc)

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
        self._buffering_since = None
        self._try_set("loop-file", "inf" if (src.loop and not src.is_stream) else "no")
        self._set_state(State.CONNECTING if self._attempts == 0 else State.RECONNECTING,
                        "" if self._attempts == 0 else f"attempt {self._attempts + 1}")
        try:
            self._mpv.loadfile(src.url, "replace")
        except Exception as exc:
            self._set_state(State.ERROR, str(exc))
            self._schedule_reconnect()

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
        self._set_state(State.PLAYING, "")

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
        last_info = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                snap = self._read_levels(now)
                if snap is not None:
                    self.levels.emit(snap)
                if now - last_info >= INFO_EVERY_S:
                    last_info = now
                    info = self._read_info()
                    self.info.emit(info)
                    self._derive_state(info, now)
            except Exception:  # never let the meter thread die
                log.exception("poll loop error")
            self._stop.wait(period)

    def _read_levels(self, now: float) -> LevelSnapshot | None:
        if self._loading and self._state != State.PLAYING:
            return None
        meta = self._get("af-metadata/stats")
        if not meta:
            if self._state == State.PLAYING:
                return LevelSnapshot(t=now, has_audio=False)
            return None
        fresh = meta != self._last_meta
        self._last_meta = meta
        peaks, rms = parse_astats(meta)
        mom, short = parse_r128(self._get("af-metadata/r128"))
        return LevelSnapshot(t=now, peaks=peaks, rms=rms, momentary=mom, short_term=short,
                             has_audio=bool(peaks), fresh=fresh)

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
            return
        if info.idle:
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
