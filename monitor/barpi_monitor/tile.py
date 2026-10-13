"""A tile is one monitored source: video surface, level meter, transport bar, status footer
and the quality-control alarm logic that watches its audio and picture.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QSlider, QToolButton,
                               QVBoxLayout, QWidget)

from . import theme
from .config import Settings, Source
from .levels import (SILENCE_FLOOR, EventCounter, MeterBallistics, OverDetector, SilenceDetector,
                     SustainedCondition, channel_labels, format_db, missing_channels)
from .meter import LevelMeter
from .player import (ALARM_STATES, LOADED_STATES, FrameSample, LevelSnapshot, MonitorPlayer, Progress, State,
                     StreamInfo)

STATUS_TEXT = {
    State.IDLE: "Stopped",
    State.CONNECTING: "Connecting…",
    State.PLAYING: "",
    State.PAUSED: "Paused",
    State.BUFFERING: "Buffering…",
    State.STALLED: "Stalled",
    State.RECONNECTING: "Reconnecting…",
    State.ERROR: "Error",
    State.ENDED: "Ended",
}
OSD_TEXT = {
    State.CONNECTING: "CONNECTING…",
    State.PAUSED: "PAUSED",
    State.RECONNECTING: "NO SIGNAL",
    State.STALLED: "NO SIGNAL",
    State.ERROR: "NO SIGNAL",
    State.ENDED: "ENDED",
    State.BUFFERING: "BUFFERING…",
}
STALE_AFTER_S = 0.15     # no fresh audio frame for this long -> let the meter fall

# Most serious first: the first active one colours the tile and is shown on the video.
ALARM_PRIORITY = ["NO SIGNAL", "NO VIDEO", "FROZEN", "BLACK", "OVER", "TOO LOUD", "SILENCE",
                  "L MISSING", "R MISSING", "CH MISSING", "LOW LEVEL"]


def alarm_rank(name: str) -> int:
    if name in ALARM_PRIORITY:
        return ALARM_PRIORITY.index(name)
    if name.endswith("MISSING"):
        return ALARM_PRIORITY.index("CH MISSING")
    return len(ALARM_PRIORITY)


def fmt_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


class VideoSurface(QWidget):
    """A native child window that libmpv draws into."""

    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor("black"))
        self.setPalette(pal)
        self.setMinimumSize(96, 54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()


class SourceTile(QFrame):
    activated = Signal(object)             # the user clicked this tile
    maximize_toggled = Signal(object)      # the user double-clicked it
    alarm_changed = Signal(object)         # the set of active alarms changed
    alarm_started = Signal(object, str, str)   # tile, alarm name, detail
    alarm_ended = Signal(object, str)          # tile, alarm name

    def __init__(self, source: Source, settings: Settings, parent=None):
        super().__init__(parent)
        self.source = source
        self.settings = settings
        self._alarms: dict[str, str] = {}
        self._osd = None
        self._audible = False
        self._selected = False
        self._blink_on = False
        self._state = State.IDLE
        self._detail = ""
        self._info = StreamInfo()
        self._progress = Progress()
        self._has_audio = False
        self._raw_peaks: list[float] = []
        self._momentary = SILENCE_FLOOR
        self._short_term = SILENCE_FLOOR
        self._last_levels_t: float | None = None
        self._last_tick = time.monotonic()
        self._last_frame: FrameSample | None = None
        self._dragging = False
        self._build_detectors()

        self.setObjectName("tile")
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumSize(220, 160)

        self.video = VideoSurface()
        self.meter = LevelMeter()

        # transport bar
        self.play_btn = QToolButton()
        self.play_btn.setText("Play")
        self.play_btn.setToolTip("Play / pause (Space)")
        self.play_btn.clicked.connect(self.play_pause)
        self.stop_btn = QToolButton()
        self.stop_btn.setText("Stop")
        self.stop_btn.setToolTip("Stop playback")
        self.stop_btn.clicked.connect(self.stop)
        self.loop_btn = QToolButton()
        self.loop_btn.setText("Loop")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setChecked(source.loop)
        self.loop_btn.setToolTip("Loop the file when it ends")
        self.loop_btn.toggled.connect(self._loop_toggled)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setEnabled(False)
        self.seek.setToolTip("Position (files only)")
        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderReleased.connect(self._seek_released)
        self.time_label = QLabel("--:--")
        for b in (self.play_btn, self.stop_btn, self.loop_btn):
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(f"QToolButton {{ background: {theme.PANEL_2}; border: 1px solid {theme.BORDER}; "
                            f"border-radius: 3px; padding: 1px 7px; color: {theme.TEXT}; }}"
                            f"QToolButton:checked {{ background: {theme.ACCENT}; color: white; }}"
                            f"QToolButton:hover {{ border-color: {theme.ACCENT}; }}")
        self.seek.setFocusPolicy(Qt.NoFocus)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(8)
        self.time_label.setFont(mono)
        self.time_label.setStyleSheet(f"color: {theme.MUTED}; border: none; background: transparent;")

        # footer
        self.name_label = QLabel(source.display_name())
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1)
        self.name_label.setFont(f)
        self.name_label.setStyleSheet(f"color: {theme.TEXT}; border: none; background: transparent;")
        self.audio_badge = QLabel("AUDIO")
        self.audio_badge.setStyleSheet(
            f"color: white; background: {theme.ACCENT}; border: none; border-radius: 3px; padding: 0 5px; "
            f"font-size: 10px; font-weight: bold;")
        self.audio_badge.hide()
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setStyleSheet(f"color: {theme.MUTED}; border: none; background: transparent;")
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(f"color: {theme.MUTED}; border: none; background: transparent; font-size: 10px;")
        self.loud_label = QLabel("")
        self.loud_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.loud_label.setFont(mono)
        self.loud_label.setStyleSheet(f"color: {theme.TEXT}; border: none; background: transparent;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.video, 1)
        row.addWidget(self.meter, 0)
        outer.addLayout(row, 1)
        transport = QHBoxLayout()
        transport.setSpacing(4)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.stop_btn)
        transport.addWidget(self.loop_btn)
        transport.addWidget(self.seek, 1)
        transport.addWidget(self.time_label)
        outer.addLayout(transport, 0)
        footer = QGridLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        footer.setHorizontalSpacing(6)
        footer.setVerticalSpacing(0)
        footer.addWidget(self.name_label, 0, 0)
        footer.addWidget(self.audio_badge, 0, 1)
        footer.addWidget(self.status_label, 0, 2)
        footer.addWidget(self.info_label, 1, 0, 1, 2)
        footer.addWidget(self.loud_label, 1, 2)
        footer.setColumnStretch(0, 1)
        footer.setColumnStretch(2, 1)
        outer.addLayout(footer, 0)

        self.player = MonitorPlayer(int(self.video.winId()), settings, parent=self)
        self.player.levels.connect(self._on_levels)
        self.player.info.connect(self._on_info)
        self.player.progress.connect(self._on_progress)
        self.player.frame.connect(self._on_frame)
        self.player.state.connect(self._on_state)
        self.player.clicked.connect(lambda: self.activated.emit(self))
        self.player.double_clicked.connect(lambda: self.maximize_toggled.emit(self))
        self.video.clicked.connect(lambda: self.activated.emit(self))
        self.video.double_clicked.connect(lambda: self.maximize_toggled.emit(self))

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._blink = QTimer(self)
        self._blink.setInterval(500)
        self._blink.timeout.connect(self._on_blink)

        self._update_style()
        self._update_footer()

    def _build_detectors(self) -> None:
        s = self.settings
        self.ballistics = MeterBallistics(s.meter_release_db_s, s.peak_hold_s)
        self.silence = SilenceDetector(s.silence_threshold_db, s.silence_seconds)
        self.over = OverDetector(hold_seconds=s.over_hold_s)
        self.loud = SustainedCondition(s.loud_seconds)
        self.high_peaks = EventCounter(10.0)
        self.low_level = SustainedCondition(s.low_level_seconds)
        self.missing: dict[int, SustainedCondition] = {}
        self.frozen = SustainedCondition(s.freeze_seconds)
        self.black = SustainedCondition(s.black_seconds)
        self.no_video = SustainedCondition(s.no_video_seconds)

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        self.player.load(self.source)

    def restart(self) -> None:
        self._reset_audio_state()
        self.player.load(self.source)

    def stop(self) -> None:
        self.player.stop()

    def play_pause(self) -> None:
        """Space / the Play button: resume, pause, or start again after Stop / the end of a file."""
        if self._state in LOADED_STATES:
            self.player.toggle_pause()
        else:
            self.restart()

    def set_paused(self, paused: bool) -> None:
        if self._state in LOADED_STATES:
            self.player.set_paused(paused)
        elif not paused:
            self.restart()

    def seek_relative(self, seconds: float) -> None:
        if self._state in LOADED_STATES and self._progress.seekable:
            self.player.seek_relative(seconds)

    def seek_start(self) -> None:
        if self._state in LOADED_STATES and self._progress.seekable:
            self.player.seek_absolute(0)

    def set_source(self, source: Source) -> None:
        self.source = source
        self.name_label.setText(source.display_name())
        self.loop_btn.setChecked(source.loop)
        self._reset_audio_state()
        self.player.load(source)

    def set_audible(self, audible: bool) -> None:
        self._audible = audible
        self.player.set_audible(audible)
        self.audio_badge.setVisible(audible)
        self._update_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def set_volume(self, volume: int) -> None:
        self.player.set_volume(volume)

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        keep = self.ballistics.channels
        self._build_detectors()
        self.ballistics.channels = keep
        self.player.apply_settings(settings)
        self._update_loudness()

    def close_player(self) -> None:
        self._timer.stop()
        self._blink.stop()
        self.player.close()

    @property
    def alarms(self) -> list[str]:
        """Active alarm names, most serious first."""
        return sorted(self._alarms, key=alarm_rank)

    @property
    def alarm(self) -> str:
        a = self.alarms
        return a[0] if a else ""

    def alarm_detail(self, name: str) -> str:
        return self._alarms.get(name, "")

    @property
    def state(self) -> str:
        return self._state

    def _reset_audio_state(self) -> None:
        self.ballistics.reset()
        self._reset_detectors()
        self._has_audio = False
        self._raw_peaks = []
        self._last_levels_t = None
        self._last_frame = None

    def _reset_detectors(self) -> None:
        for d in (self.silence, self.over, self.loud, self.high_peaks, self.low_level, self.frozen,
                  self.black, self.no_video):
            d.reset()
        self.missing.clear()

    # ------------------------------------------------------------------ player signals

    def _on_levels(self, snap: LevelSnapshot) -> None:
        self._has_audio = snap.has_audio
        if not snap.has_audio:
            self._raw_peaks = []
            return
        if snap.fresh:
            dt = snap.t - (self._last_levels_t if self._last_levels_t is not None else snap.t)
            self.ballistics.update(min(dt, 0.5), snap.peaks, snap.rms)
            self._last_levels_t = snap.t
            self._raw_peaks = snap.peaks
            self._momentary, self._short_term = snap.momentary, snap.short_term

    def _on_info(self, info: StreamInfo) -> None:
        self._info = info
        self.info_label.setText(info.summary())

    def _on_progress(self, p: Progress) -> None:
        self._progress = p
        self.play_btn.setText("Play" if p.paused else "Pause")
        live = p.duration is None
        self.seek.setEnabled(bool(p.seekable) and not live)
        if not self._dragging:
            if p.duration and p.time_pos is not None:
                self.seek.setValue(int(1000 * max(0.0, min(1.0, p.time_pos / p.duration))))
            elif live:
                self.seek.setValue(0)
        if live:
            self.time_label.setText(f"LIVE {fmt_time(p.time_pos)}" if p.time_pos is not None else "LIVE")
        else:
            self.time_label.setText(f"{fmt_time(p.time_pos)} / {fmt_time(p.duration)}")

    def _on_frame(self, sample: FrameSample) -> None:
        if self._state != State.PLAYING or not (self.source.video_alarm and self.settings.video_analysis):
            return
        prev = self._last_frame
        self._last_frame = sample
        dt = (sample.t - prev.t) if prev is not None else 1.0
        if not sample.ok:
            self.no_video.update(dt, True)
            self.frozen.reset()
            self.black.reset()
        else:
            self.no_video.update(dt, False)
            self.frozen.update(dt, prev is not None and prev.ok and prev.signature == sample.signature)
            self.black.update(dt, sample.mean < self.settings.black_level)
        self._set_alarm("NO VIDEO", self.no_video.active, f"no frame for {self.no_video.held_for:.0f}s")
        self._set_alarm("FROZEN", self.frozen.active, f"picture unchanged for {self.frozen.held_for:.0f}s")
        self._set_alarm("BLACK", self.black.active, f"brightness {sample.mean:.0f}/255 for {self.black.held_for:.0f}s")

    def _on_state(self, state: str, detail: str) -> None:
        self._state, self._detail = state, detail
        if state != State.PLAYING:
            self._reset_detectors()
            for name in [n for n in self._alarms if n != "NO SIGNAL"]:
                self._set_alarm(name, False)
            self._last_frame = None
        if state not in LOADED_STATES:
            self._has_audio = False
            self._raw_peaks = []
            self.play_btn.setText("Play")
            self.seek.setEnabled(False)
            self.seek.setValue(0)
            self.time_label.setText("--:--")
        if state in (State.CONNECTING, State.RECONNECTING, State.IDLE):
            self.info_label.setText("")
            self._info = StreamInfo()
        self._update_footer()
        self._refresh_alarms()

    # ------------------------------------------------------------------ periodic UI tick

    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        loaded = self._state in LOADED_STATES
        playing = self._state == State.PLAYING

        if not loaded or not self._has_audio or not playing:
            self.ballistics.decay(dt)
        elif self._last_levels_t is not None and now - self._last_levels_t > STALE_AFTER_S:
            self.ballistics.decay(dt)

        live = self._has_audio and self._last_levels_t is not None and now - self._last_levels_t < 1.0
        peaks = self._raw_peaks if live else []
        loudest = max(peaks) if peaks else SILENCE_FLOOR
        s = self.settings
        src = self.source

        if playing and src.silence_alarm:
            self.silence.update(dt, peaks)
            self._set_alarm("SILENCE", self.silence.active, f"{self.silence.silent_for:.0f}s under {s.silence_threshold_db:.0f} dBFS")
        else:
            self.silence.reset()
        if playing and src.level_alarm:
            over = self.over.update(dt, peaks) and s.over_alarm
            self._set_alarm("OVER", over, f"{self.over.count} clipped frame{'s' if self.over.count != 1 else ''}")
            loud = self.loud.update(dt, live and self._short_term > s.loud_lufs)
            peaks_hit = self.high_peaks.update(dt, bool(peaks) and loudest >= s.high_peak_db) >= s.high_peak_events
            detail = (f"short-term {self._short_term:.1f} LUFS > {s.loud_lufs:.0f}" if loud
                      else f"{self.high_peaks.count} peaks ≥ {s.high_peak_db:.0f} dBFS in 10 s")
            self._set_alarm("TOO LOUD", loud or peaks_hit, detail)
            low = self.low_level.update(dt, bool(peaks) and s.silence_threshold_db <= loudest < s.low_level_db)
            self._set_alarm("LOW LEVEL", low, f"peak {loudest:.0f} dBFS for {self.low_level.held_for:.0f}s")
            labels = channel_labels(len(peaks), self._info.channels)
            gone = set(missing_channels(peaks, s.silence_threshold_db))
            for ch in range(len(peaks)):
                cond = self.missing.setdefault(ch, SustainedCondition(s.channel_missing_seconds))
                cond.update(dt, ch in gone)
                label = labels[ch] if ch < len(labels) else str(ch + 1)
                self._set_alarm(f"{label} MISSING", cond.active, f"channel {label} silent for {cond.held_for:.0f}s")
        else:
            for d in (self.over, self.loud, self.high_peaks, self.low_level):
                d.reset()
            self.missing.clear()

        labels = channel_labels(len(self.ballistics.channels), self._info.channels)
        self.meter.set_levels(self.ballistics.channels, labels, self._has_audio and loaded, self.over.active)
        self.meter.set_dim(not playing)
        self._refresh_alarms()
        self._update_loudness()

    def _set_alarm(self, name: str, active: bool, detail: str = "") -> None:
        if active and name not in self._alarms:
            self._alarms[name] = detail
            self.alarm_started.emit(self, name, detail)
            self._alarms_dirty = True
        elif active:
            self._alarms[name] = detail
        elif not active and name in self._alarms:
            del self._alarms[name]
            self.alarm_ended.emit(self, name)
            self._alarms_dirty = True

    def _refresh_alarms(self) -> None:
        self._set_alarm("NO SIGNAL", self._state in ALARM_STATES, self._detail)
        if getattr(self, "_alarms_dirty", False):
            self._alarms_dirty = False
            if self._alarms:
                if not self._blink.isActive():
                    self._blink_on = True
                    self._blink.start()
            else:
                self._blink.stop()
                self._blink_on = False
            self._update_style()
            self._update_footer()
            self.alarm_changed.emit(self)
        top = self.alarm
        osd = top if top and top != "NO SIGNAL" else OSD_TEXT.get(self._state, "")
        if osd != self._osd:
            self._osd = osd
            self.player.set_osd_text(osd)

    def _on_blink(self) -> None:
        self._blink_on = not self._blink_on
        self._update_style()

    # ------------------------------------------------------------------ transport widgets

    def _loop_toggled(self, checked: bool) -> None:
        self.source.loop = bool(checked)
        self.player._try_set("loop-file", "inf" if (checked and not self.source.is_stream) else "no")

    def _seek_pressed(self) -> None:
        self._dragging = True

    def _seek_released(self) -> None:
        self._dragging = False
        if self._progress.seekable and self._progress.duration:
            self.player.seek_percent(self.seek.value() / 10.0)

    # ------------------------------------------------------------------ presentation

    def _update_loudness(self) -> None:
        if self.settings.show_loudness and self._has_audio and self._state == State.PLAYING:
            self.loud_label.setText(f"M {format_db(self._momentary):>6}  S {format_db(self._short_term):>6} LUFS")
        else:
            self.loud_label.setText("")

    def _update_footer(self) -> None:
        text = STATUS_TEXT.get(self._state, self._state)
        top = self.alarm
        if top and top != "NO SIGNAL":
            others = len(self._alarms) - 1
            text = top + (f" +{others}" if others else "")
        elif self._detail and self._state in (State.ERROR, State.RECONNECTING, State.STALLED, State.BUFFERING):
            text = f"{text} {self._detail}" if text else self._detail
        if self._alarms:
            color = theme.RED
        elif self._state in (State.CONNECTING, State.BUFFERING, State.PAUSED):
            color = theme.AMBER
        else:
            color = theme.MUTED
        self.status_label.setText(text[:90])
        self.status_label.setStyleSheet(
            f"color: {color}; border: none; background: transparent; font-weight: {'bold' if self._alarms else 'normal'};")
        self.status_label.setToolTip("\n".join(f"{n}: {d}" for n, d in self._alarms.items()) or self._detail)

    def _update_style(self) -> None:
        if self._alarms:
            border = theme.RED if self._blink_on else "#5a1d1d"
        elif self._audible:
            border = theme.ACCENT
        elif self._selected:
            border = "#4b5363"
        else:
            border = theme.BORDER
        self.setStyleSheet(
            f"QFrame#tile {{ background: {theme.PANEL}; border: 2px solid {border}; border-radius: 5px; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.activated.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.maximize_toggled.emit(self)
