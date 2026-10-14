"""The update dialog: shows the offered version, downloads it with a progress bar, then restarts into it."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from . import APP_NAME, __version__, theme
from .license import LicenseClient
from .updater import UpdateError, current_exe, download, install, staged_path

log = logging.getLogger(__name__)


def fmt_size(n: int) -> str:
    return f"{n / 1024 / 1024:.0f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


class _Worker(QObject):
    progress = Signal(int, int)
    failed = Signal(str)
    finished = Signal(str)   # "swapped" or "deferred"


class UpdateDialog(QDialog):
    """``restart(mode, new_file)`` is called after a successful install; it saves, quits and starts the new build."""

    def __init__(self, offer: dict, client: LicenseClient, restart, parent=None):
        super().__init__(parent)
        self.offer = offer
        self.client = client
        self.restart = restart
        self.required = bool(offer.get("required"))
        self.exe = current_exe()
        self.setWindowTitle(f"Update {APP_NAME}")
        self.setMinimumWidth(480)

        head = QLabel(f"<b>Version {offer['version']}</b> is available. This computer has {__version__}.")
        head.setTextFormat(Qt.RichText)
        detail = []
        if offer.get("notes"):
            detail.append(f"What's new: {offer['notes']}")
        if offer.get("size"):
            detail.append(f"Download: {fmt_size(int(offer['size']))}.")
        if self.required:
            detail.append("Your administrator requires this version, so it installs now. "
                          "The program restarts by itself and resumes your sources.")
        else:
            detail.append("The program restarts by itself after the update and resumes your sources.")
        body = QLabel("\n".join(detail))
        body.setWordWrap(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(False)

        self.go_btn = QPushButton("Update now")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self.start)
        self.later_btn = QPushButton("Later" if not self.required else "Continue for now")
        self.later_btn.clicked.connect(self.reject)
        self.later_btn.setVisible(not self.required)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.later_btn)
        row.addWidget(self.go_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addWidget(body)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addLayout(row)

        self.worker = _Worker()
        self.worker.progress.connect(self._on_progress)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)

        if self.exe is None:
            # Running from source: there is no exe to replace; offer the download page instead.
            self.status.setText("This copy runs from source, so it cannot replace itself. Download the new exe instead.")
            self.go_btn.setText("Open download")
            self.go_btn.clicked.disconnect()
            self.go_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(offer["url"])))
            self.later_btn.setVisible(True)
            self.later_btn.setText("Close")
        elif self.required:
            self.go_btn.setVisible(False)
            self.start()

    def start(self) -> None:
        self.go_btn.setEnabled(False)
        self.later_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setStyleSheet(f"color: {theme.MUTED};")
        self.status.setText("Downloading…")
        threading.Thread(target=self._run, name="update", daemon=True).start()

    def _run(self) -> None:
        exe = self.exe
        offer = self.offer
        try:
            new_file = download(offer["url"], staged_path(exe), offer.get("sha256", ""), int(offer.get("size") or 0),
                                progress=lambda got, total: self.worker.progress.emit(got, total))
            # Remember what was installed before swapping, so a mislabelled build is not offered again.
            self.client.state.installed_update = offer["version"]
            self.client.save()
            mode = install(new_file, exe)
        except UpdateError as exc:
            self.client.state.installed_update = ""
            self.client.save()
            self.worker.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - an update must never crash the monitor
            log.exception("update failed")
            self.client.state.installed_update = ""
            self.client.save()
            self.worker.failed.emit(f"The update failed unexpectedly ({exc}).")
            return
        self.worker.finished.emit(mode)

    def _on_progress(self, got: int, total: int) -> None:
        if total:
            self.bar.setValue(int(got * 100 / total))
            self.status.setText(f"Downloading… {fmt_size(got)} of {fmt_size(total)}")

    def _on_failed(self, message: str) -> None:
        log.warning("update to %s failed: %s", self.offer["version"], message)
        self.bar.setVisible(False)
        self.status.setStyleSheet(f"color: {theme.RED};")
        self.status.setText(message + ("  The program keeps running and tries again at the next check." if self.required else ""))
        self.go_btn.setText("Try again")
        self.go_btn.setVisible(True)
        self.go_btn.setEnabled(True)
        self.later_btn.setVisible(True)
        self.later_btn.setEnabled(True)
        if self.required:
            self.later_btn.setText("Continue for now")

    def _on_finished(self, mode: str) -> None:
        self.bar.setValue(100)
        self.status.setStyleSheet(f"color: {theme.GREEN};")
        self.status.setText(f"Version {self.offer['version']} installed. Restarting…")
        log.info("update to %s installed (%s); restarting", self.offer["version"], mode)
        self.accept()
        self.restart(mode, staged_path(self.exe))
