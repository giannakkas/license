"""The add/edit source dialog and the settings dialog."""
from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

from .config import Settings, Source, guess_name, is_url

VIDEO_FILTER = ("Video and audio files (*.mp4 *.mkv *.mov *.ts *.m2ts *.mts *.mxf *.avi *.wmv *.webm *.flv "
                "*.mpg *.mpeg *.m4v *.mp3 *.wav *.aac *.m3u8 *.m3u);;All files (*)")


class SourceDialog(QDialog):
    def __init__(self, source: Source | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit source" if source else "Add source")
        self.setMinimumWidth(520)
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
        self.silence_box = QCheckBox("Raise the SILENCE alarm when this source goes quiet")
        self.silence_box.setChecked(source.silence_alarm if source else True)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Source", url_row)
        form.addRow("", self.loop_box)
        form.addRow("", self.silence_box)
        hint = QLabel("Examples:  rtsp://192.168.1.20/live   ·   srt://10.0.0.5:9000?mode=caller   ·   "
                      "udp://@239.1.1.1:1234   ·   https://host/live/index.m3u8")
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
                      silence_alarm=self.silence_box.isChecked())


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._settings = settings

        def spin(value, lo, hi, suffix, step=1.0, decimals=1):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(decimals)
            s.setSingleStep(step)
            s.setSuffix(suffix)
            s.setValue(value)
            return s

        self.silence_db = spin(settings.silence_threshold_db, -90, 0, " dBFS", 1, 0)
        self.silence_s = spin(settings.silence_seconds, 1, 600, " s", 1, 0)
        self.stall_s = spin(settings.stall_seconds, 3, 120, " s", 1, 0)
        self.release = spin(settings.meter_release_db_s, 5, 60, " dB/s", 1, 0)
        self.hold = spin(settings.peak_hold_s, 0.2, 5, " s", 0.1, 1)
        self.beep = QCheckBox("Beep every few seconds while any alarm is active")
        self.beep.setChecked(settings.beep_on_alarm)
        self.loudness = QCheckBox("Show EBU R128 loudness (momentary / short-term) under each tile")
        self.loudness.setChecked(settings.show_loudness)
        self.hwdec = QCheckBox("Hardware video decoding (lower CPU; applies when a source restarts)")
        self.hwdec.setChecked(settings.hwdec)
        self.reconnect = QCheckBox("Reconnect streams automatically when they drop or stall")
        self.reconnect.setChecked(settings.reconnect)

        form = QFormLayout()
        form.addRow(QLabel("<b>Alarms</b>"))
        form.addRow("Silence threshold", self.silence_db)
        form.addRow("Silence duration", self.silence_s)
        form.addRow("Stalled stream after", self.stall_s)
        form.addRow("", self.beep)
        form.addRow("", self.reconnect)
        form.addRow(QLabel("<b>Meters</b>"))
        form.addRow("Peak fall rate", self.release)
        form.addRow("Peak hold time", self.hold)
        form.addRow("", self.loudness)
        form.addRow(QLabel("<b>Video</b>"))
        form.addRow("", self.hwdec)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def settings(self) -> Settings:
        return dataclasses.replace(
            self._settings,
            silence_threshold_db=self.silence_db.value(),
            silence_seconds=self.silence_s.value(),
            stall_seconds=self.stall_s.value(),
            meter_release_db_s=self.release.value(),
            peak_hold_s=self.hold.value(),
            beep_on_alarm=self.beep.isChecked(),
            show_loudness=self.loudness.isChecked(),
            hwdec=self.hwdec.isChecked(),
            reconnect=self.reconnect.isChecked(),
        )
