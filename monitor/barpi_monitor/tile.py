"""A tile is one monitored source: the video surface, its level meter and a status footer."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .config import Settings, Source
from .levels import (SILENCE_FLOOR, MeterBallistics, OverDetector, SilenceDetector, channel_labels,
                     format_db)
from .meter import LevelMeter
from .player import ALARM_STATES, LevelSnapshot, MonitorPlayer, State, StreamInfo

STATUS_TEXT = {
    State.IDLE: "Stopped",
    State.CONNECTING: "Connecting…",
    State.PLAYING: "",
    State.BUFFERING: "Buffering…",
    State.STALLED: "Stalled",
    State.RECONNECTING: "Reconnecting…",
    State.ERROR: "Error",
    State.ENDED: "Ended",
}
OSD_TEXT = {
    State.CONNECTING: "CONNECTING…",
    State.RECONNECTING: "NO SIGNAL",
    State.STALLED: "NO SIGNAL",
    State.ERROR: "NO SIGNAL",
    State.ENDED: "ENDED",
    State.BUFFERING: "BUFFERING…",
}
STALE_AFTER_S = 0.15     # no fresh audio frame for this long -> let the meter fall


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
    activated = Signal(object)         # the user clicked this tile
    maximize_toggled = Signal(object)  # the user double-clicked it
    alarm_changed = Signal(object)     # its alarm text changed

    def __init__(self, source: Source, settings: Settings, parent=None):
        super().__init__(parent)
        self.source = source
        self.settings = settings
        self._alarm = ""
        self._osd = None
        self._audible = False
        self._selected = False
        self._blink_on = False
        self._state = State.IDLE
        self._detail = ""
        self._info = StreamInfo()
        self._has_audio = False
        self._raw_peaks: list[float] = []
        self._momentary = SILENCE_FLOOR
        self._short_term = SILENCE_FLOOR
        self._last_levels_t: float | None = None
        self._last_tick = time.monotonic()
        self.ballistics = MeterBallistics(settings.meter_release_db_s, settings.peak_hold_s)
        self.silence = SilenceDetector(settings.silence_threshold_db, settings.silence_seconds)
        self.over = OverDetector()

        self.setObjectName("tile")
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumSize(200, 140)

        self.video = VideoSurface()
        self.meter = LevelMeter()
        self.name_label = QLabel(source.display_name())
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1)
        self.name_label.setFont(f)
        self.name_label.setStyleSheet(f"color: {theme.TEXT}; border: none; background: transparent;")
        self.audio_badge = QLabel("AUDIO")
        self.audio_badge.setStyleSheet(
            f"color: white; background: {theme.ACCENT}; border: none; border-radius: 3px; padding: 0 5px; font-size: 10px; font-weight: bold;")
        self.audio_badge.hide()
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setStyleSheet(f"color: {theme.MUTED}; border: none; background: transparent;")
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(f"color: {theme.MUTED}; border: none; background: transparent; font-size: 10px;")
        self.loud_label = QLabel("")
        self.loud_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(8)
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

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        self.player.load(self.source)

    def restart(self) -> None:
        self._reset_audio_state()
        self.player.load(self.source)

    def stop(self) -> None:
        self.player.stop()

    def set_source(self, source: Source) -> None:
        self.source = source
        self.name_label.setText(source.display_name())
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
        self.ballistics.release = settings.meter_release_db_s
        self.ballistics.hold_seconds = settings.peak_hold_s
        self.silence.threshold_db = settings.silence_threshold_db
        self.silence.hold_seconds = settings.silence_seconds
        self.player.apply_settings(settings)
        self._update_loudness()

    def close_player(self) -> None:
        self._timer.stop()
        self._blink.stop()
        self.player.close()

    @property
    def alarm(self) -> str:
        return self._alarm

    @property
    def state(self) -> str:
        return self._state

    def _reset_audio_state(self) -> None:
        self.ballistics.reset()
        self.silence.reset()
        self.over.reset()
        self._has_audio = False
        self._raw_peaks = []
        self._last_levels_t = None

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

    def _on_state(self, state: str, detail: str) -> None:
        self._state, self._detail = state, detail
        if state not in (State.PLAYING, State.BUFFERING):
            self.silence.reset()
            self._has_audio = False
            self._raw_peaks = []
        if state in (State.CONNECTING, State.RECONNECTING, State.IDLE):
            self.info_label.setText("")
            self._info = StreamInfo()
        self._update_footer()
        self._refresh_alarm(False)

    # ------------------------------------------------------------------ periodic UI tick

    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        playing = self._state in (State.PLAYING, State.BUFFERING)

        if not playing or not self._has_audio:
            self.ballistics.decay(dt)
        elif self._last_levels_t is not None and now - self._last_levels_t > STALE_AFTER_S:
            self.ballistics.decay(dt)

        live = self._has_audio and self._last_levels_t is not None and now - self._last_levels_t < 1.0
        peaks = self._raw_peaks if live else []
        if self._state == State.PLAYING and self.source.silence_alarm:
            silent = self.silence.update(dt, peaks)
        else:
            self.silence.reset()
            silent = False
        over = self.over.update(dt, peaks)

        labels = channel_labels(len(self.ballistics.channels), self._info.channels)
        self.meter.set_levels(self.ballistics.channels, labels, self._has_audio and playing, over)
        self.meter.set_dim(not playing)
        self._refresh_alarm(silent)
        self._update_loudness()

    def _refresh_alarm(self, silent: bool) -> None:
        if self._state in ALARM_STATES:
            alarm = "NO SIGNAL"
        elif silent:
            alarm = "SILENCE"
        else:
            alarm = ""
        if alarm != self._alarm:
            self._alarm = alarm
            if alarm:
                self._blink_on = True
                self._blink.start()
            else:
                self._blink.stop()
                self._blink_on = False
            self._update_style()
            self._update_footer()
            self.alarm_changed.emit(self)
        osd = "SILENCE" if alarm == "SILENCE" else OSD_TEXT.get(self._state, "")
        if osd != self._osd:
            self._osd = osd
            self.player.set_osd_text(osd)

    def _on_blink(self) -> None:
        self._blink_on = not self._blink_on
        self._update_style()

    # ------------------------------------------------------------------ presentation

    def _update_loudness(self) -> None:
        if self.settings.show_loudness and self._has_audio and self._state == State.PLAYING:
            self.loud_label.setText(f"M {format_db(self._momentary):>6}  S {format_db(self._short_term):>6} LUFS")
        else:
            self.loud_label.setText("")

    def _update_footer(self) -> None:
        text = STATUS_TEXT.get(self._state, self._state)
        if self._alarm == "SILENCE":
            text = f"SILENCE {self.silence.silent_for:.0f}s"
        elif self._detail and self._state in (State.ERROR, State.RECONNECTING, State.STALLED, State.BUFFERING):
            text = f"{text} {self._detail}" if text else self._detail
        if self._state in ALARM_STATES or self._alarm:
            color = theme.RED
        elif self._state in (State.CONNECTING, State.BUFFERING):
            color = theme.AMBER
        else:
            color = theme.MUTED
        self.status_label.setText(text[:90])
        self.status_label.setStyleSheet(
            f"color: {color}; border: none; background: transparent; font-weight: {'bold' if self._alarm else 'normal'};")
        self.status_label.setToolTip(self._detail)

    def _update_style(self) -> None:
        if self._alarm:
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
