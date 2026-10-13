"""The add/edit source dialog and the settings dialog."""
from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from .config import Settings, Source, guess_name, is_url

VIDEO_FILTER = ("Video and audio files (*.mp4 *.mkv *.mov *.ts *.m2ts *.mts *.mxf *.avi *.wmv *.webm *.flv "
                "*.mpg *.mpeg *.m4v *.mp3 *.wav *.aac *.m3u8 *.m3u);;All files (*)")


class SourceDialog(QDialog):
    def __init__(self, source: Source | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit source" if source else "Add source")
        self.setMinimumWidth(540)
        self._original = source

        self.name_edit = QLineEdit(source.name if source else "")
        self.name_edit.setPlaceholderText("optional: defaults to the host or file name")
        self.url_edit = QLineEdit(source.url if source else "")
        self.url_edit.setPlaceholderText("rtsp:// srt:// udp:// rtmp:// http(s)://…m3u8  or a file path")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        url_row = QHBoxLayout()
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(browse)
        self.loop_box = QCheckBox("Loop when a file reaches the end")
        self.loop_box.setChecked(source.loop if source else False)
        self.silence_box = QCheckBox("SILENCE alarm when every channel goes quiet")
        self.silence_box.setChecked(source.silence_alarm if source else True)
        self.level_box = QCheckBox("Level alarms: OVER, TOO LOUD, LOW LEVEL, missing channel")
        self.level_box.setChecked(source.level_alarm if source else True)
        self.video_box = QCheckBox("Picture alarms: NO VIDEO, FROZEN, BLACK")
        self.video_box.setChecked(source.video_alarm if source else True)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Source", url_row)
        form.addRow("", self.loop_box)
        form.addRow("Alarms", self.silence_box)
        form.addRow("", self.level_box)
        form.addRow("", self.video_box)
        hint = QLabel("Examples:  rtsp://192.168.1.20/live   ·   srt://10.0.0.5:9000?mode=caller   ·   "
                      "udp://@239.1.1.1:1234   ·   https://host/live/index.m3u8   ·   D:\\clips\\promo.mp4")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b93a3; font-size: 10px;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok = buttons.button(QDialogButtonBox.Ok)
        self._ok.setDefault(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.url_edit.textChanged.connect(self._validate)
        self._validate()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a video file", "", VIDEO_FILTER)
        if path:
            self.url_edit.setText(path)
            if not self.name_edit.text().strip():
                self.name_edit.setText(guess_name(path))
            self.loop_box.setChecked(True)

    def _validate(self) -> None:
        self._ok.setEnabled(bool(self.url_edit.text().strip()))

    def source(self) -> Source:
        url = self.url_edit.text().strip()
        return Source(name=self.name_edit.text().strip() or guess_name(url), url=url,
                      loop=self.loop_box.isChecked() and not is_url(url),
                      silence_alarm=self.silence_box.isChecked(),
                      level_alarm=self.level_box.isChecked(),
                      video_alarm=self.video_box.isChecked())


def _spin(value, lo, hi, suffix, step=1.0, decimals=1):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value)
    return s


def _ispin(value, lo, hi, suffix=""):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSuffix(suffix)
    s.setValue(value)
    return s


def _page(rows) -> QWidget:
    w = QWidget()
    form = QFormLayout(w)
    for label, widget in rows:
        if widget is None:
            form.addRow(QLabel(f"<b>{label}</b>"))
        else:
            form.addRow(label, widget)
    return w


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self._settings = settings
        s = settings

        # audio alarms
        self.silence_db = _spin(s.silence_threshold_db, -90, 0, " dBFS", 1, 0)
        self.silence_s = _spin(s.silence_seconds, 1, 600, " s", 1, 0)
        self.over = QCheckBox("OVER when a sample reaches full scale (clipping)")
        self.over.setChecked(s.over_alarm)
        self.over_hold = _spin(s.over_hold_s, 1, 60, " s", 1, 0)
        self.loud_lufs = _spin(s.loud_lufs, -40, 0, " LUFS", 1, 0)
        self.loud_s = _spin(s.loud_seconds, 1, 60, " s", 1, 0)
        self.high_db = _spin(s.high_peak_db, -30, 0, " dBFS", 1, 0)
        self.high_n = _ispin(s.high_peak_events, 1, 100, " peaks in 10 s")
        self.low_db = _spin(s.low_level_db, -80, 0, " dBFS", 1, 0)
        self.low_s = _spin(s.low_level_seconds, 1, 600, " s", 1, 0)
        self.missing_s = _spin(s.channel_missing_seconds, 1, 600, " s", 1, 0)
        audio = _page([
            ("Silence", None),
            ("SILENCE when every channel is under", self.silence_db),
            ("for longer than", self.silence_s),
            ("Clipping", None),
            ("", self.over),
            ("OVER stays lit for", self.over_hold),
            ("Too loud", None),
            ("TOO LOUD when short-term loudness exceeds", self.loud_lufs),
            ("for longer than", self.loud_s),
            ("or when peaks reach", self.high_db),
            ("at least", self.high_n),
            ("Too quiet", None),
            ("LOW LEVEL when the loudest channel stays under", self.low_db),
            ("for longer than", self.low_s),
            ("Missing channel", None),
            ("L / R MISSING when one channel is silent for", self.missing_s),
        ])

        # video alarms
        self.video_analysis = QCheckBox("Analyse the picture (one frame per second per source)")
        self.video_analysis.setChecked(s.video_analysis)
        self.freeze_s = _spin(s.freeze_seconds, 2, 600, " s", 1, 0)
        self.black_s = _spin(s.black_seconds, 1, 600, " s", 1, 0)
        self.black_level = _spin(s.black_level, 1, 128, " / 255", 1, 0)
        self.novideo_s = _spin(s.no_video_seconds, 1, 600, " s", 1, 0)
        video = _page([
            ("", self.video_analysis),
            ("FROZEN when the picture has not changed for", self.freeze_s),
            ("BLACK when the picture stays dark for", self.black_s),
            ("dark means mean brightness under", self.black_level),
            ("NO VIDEO when no frame can be read for", self.novideo_s),
        ])

        # general
        self.stall_s = _spin(s.stall_seconds, 3, 120, " s", 1, 0)
        self.reconnect = QCheckBox("Reconnect streams automatically when they drop or stall")
        self.reconnect.setChecked(s.reconnect)
        self.beep = QCheckBox("Beep every few seconds while any alarm is active")
        self.beep.setChecked(s.beep_on_alarm)
        self.alarm_log = QCheckBox("Write every alarm start and end to alarms.csv next to the config file")
        self.alarm_log.setChecked(s.alarm_log)
        self.hwdec = QCheckBox("Hardware video decoding (lower CPU; applies when a source restarts)")
        self.hwdec.setChecked(s.hwdec)
        general = _page([
            ("Streams", None),
            ("NO SIGNAL and reconnect after no data for", self.stall_s),
            ("", self.reconnect),
            ("Alarms", None),
            ("", self.beep),
            ("", self.alarm_log),
            ("Video", None),
            ("", self.hwdec),
        ])

        # meters
        self.release = _spin(s.meter_release_db_s, 5, 60, " dB/s", 1, 0)
        self.hold = _spin(s.peak_hold_s, 0.2, 5, " s", 0.1, 1)
        self.loudness = QCheckBox("Show EBU R128 loudness (momentary / short-term) under each tile")
        self.loudness.setChecked(s.show_loudness)
        meters = _page([
            ("Peak fall rate", self.release),
            ("Peak hold time", self.hold),
            ("", self.loudness),
        ])

        tabs = QTabWidget()
        tabs.addTab(audio, "Audio alarms")
        tabs.addTab(video, "Picture alarms")
        tabs.addTab(general, "General")
        tabs.addTab(meters, "Meters")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def settings(self) -> Settings:
        return dataclasses.replace(
            self._settings,
            silence_threshold_db=self.silence_db.value(),
            silence_seconds=self.silence_s.value(),
            over_alarm=self.over.isChecked(),
            over_hold_s=self.over_hold.value(),
            loud_lufs=self.loud_lufs.value(),
            loud_seconds=self.loud_s.value(),
            high_peak_db=self.high_db.value(),
            high_peak_events=self.high_n.value(),
            low_level_db=self.low_db.value(),
            low_level_seconds=self.low_s.value(),
            channel_missing_seconds=self.missing_s.value(),
            video_analysis=self.video_analysis.isChecked(),
            freeze_seconds=self.freeze_s.value(),
            black_seconds=self.black_s.value(),
            black_level=self.black_level.value(),
            no_video_seconds=self.novideo_s.value(),
            stall_seconds=self.stall_s.value(),
            reconnect=self.reconnect.isChecked(),
            beep_on_alarm=self.beep.isChecked(),
            alarm_log=self.alarm_log.isChecked(),
            hwdec=self.hwdec.isChecked(),
            meter_release_db_s=self.release.value(),
            peak_hold_s=self.hold.value(),
            show_loudness=self.loudness.isChecked(),
        )
