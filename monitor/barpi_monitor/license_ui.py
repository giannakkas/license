"""Licence screens: activation, the licence status dialog, the lock screen and the check-in thread."""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from . import APP_NAME, __version__, theme
from .license import (MODE_OFFLINE, NEEDS_ACTIVATION, LicenseClient, LicenseError, ServerUnreachable, Status,
                      normalise_key)

LOCK_TITLES = {
    Status.LOCKED: "This system is locked",
    Status.REVOKED: "Licence revoked",
    Status.EXPIRED: "Licence expired",
    Status.UNKNOWN: "Activation needed",
    Status.OFFLINE: "Licence server unreachable",
    Status.CLOCK: "Clock set back",
    Status.UNLICENSED: "No licence",
}

FILE_FILTER = "Licence files (*.lic);;All files (*)"

log = logging.getLogger(__name__)

WATCH_BACKOFF_MAX_S = 300   # the longest pause between attempts to reach the platform for news


def import_license_file(client: LicenseClient, parent=None) -> tuple[bool, str]:
    """Ask for a .lic file and import it. Returns (imported, message)."""
    path, _ = QFileDialog.getOpenFileName(parent, "Import licence file", "", FILE_FILTER)
    if not path:
        return False, ""
    try:
        state = client.import_file(path)
    except LicenseError as exc:
        return False, exc.message
    who = f" for {state.label}" if state.label else ""
    return True, f"Licence file imported{who}; valid until {state.file_expires_at[:10]}."


def _mask(key: str) -> str:
    return f"ONCUE-•••••-•••••-•••••-{key[-5:]}" if len(key) >= 5 else key


class ActivationDialog(QDialog):
    """Asks for the serial key and activates this machine on the platform."""

    def __init__(self, client: LicenseClient, parent=None, message: str = ""):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle(f"Activate {APP_NAME}")
        self.setMinimumWidth(520)
        intro = QLabel(f"Enter the licence key for this computer. The key is checked with "
                       f"{client.state.server.replace('https://', '')} and this computer is registered to it.")
        intro.setWordWrap(True)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("ONCUE-XXXXX-XXXXX-XXXXX-XXXXX")
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        f.setPointSizeF(11)
        self.key_edit.setFont(f)
        self.key_edit.textEdited.connect(self._format)
        self.status = QLabel(message)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.AMBER};")

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.BORDER};")
        offline = QLabel("No internet on this computer? Send the computer ID below to your supplier and import "
                         "the licence file you receive. The file works on this computer only, until its expiry date.")
        offline.setWordWrap(True)
        offline.setStyleSheet(f"color: {theme.MUTED};")
        machine = QLabel(f"Computer ID: <b>{client.state.machine_id}</b>")
        machine.setStyleSheet(f"color: {theme.TEXT};")
        machine.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_btn = QPushButton("Copy ID")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(client.state.machine_id))
        import_btn = QPushButton("Import licence file…")
        import_btn.clicked.connect(self._import)
        id_row = QHBoxLayout()
        id_row.addWidget(machine)
        id_row.addWidget(copy_btn)
        id_row.addStretch(1)
        id_row.addWidget(import_btn)

        buttons = QDialogButtonBox()
        self.activate_btn = buttons.addButton("Activate", QDialogButtonBox.AcceptRole)
        self.activate_btn.setDefault(True)
        quit_btn = buttons.addButton("Quit", QDialogButtonBox.RejectRole)
        self.activate_btn.clicked.connect(self._activate)
        quit_btn.clicked.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.status)
        layout.addSpacing(6)
        layout.addWidget(line)
        layout.addWidget(offline)
        layout.addLayout(id_row)
        layout.addSpacing(6)
        layout.addWidget(buttons)
        if client.state.key:
            self.key_edit.setText(client.state.key)

    def _format(self, text: str) -> None:
        pos = self.key_edit.cursorPosition()
        formatted = normalise_key(text)
        if formatted != text:
            self.key_edit.setText(formatted)
            self.key_edit.setCursorPosition(min(len(formatted), pos + (len(formatted) - len(text))))

    def _activate(self) -> None:
        key = self.key_edit.text().strip()
        self.status.setStyleSheet(f"color: {theme.AMBER};")
        self.status.setText("Contacting the licence server…")
        self.activate_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            state = self.client.activate(key)
        except LicenseError as exc:
            self._fail(exc.message)
            return
        except ServerUnreachable as exc:
            self._fail(f"Cannot reach the licence server ({exc}). Check the internet connection and try again.")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.activate_btn.setEnabled(True)
        self.status.setStyleSheet(f"color: {theme.GREEN};")
        self.status.setText(f"Activated{(' for ' + state.label) if state.label else ''}.")
        self.accept()

    def _import(self) -> None:
        ok, message = import_license_file(self.client, parent=self)
        if ok:
            self.status.setStyleSheet(f"color: {theme.GREEN};")
            self.status.setText(message)
            self.accept()
        elif message:
            self._fail(message)

    def _fail(self, message: str) -> None:
        self.status.setStyleSheet(f"color: {theme.RED};")
        self.status.setText(message)


class LicenseDialog(QDialog):
    """Help → Licence: what the platform currently says about this computer."""

    def __init__(self, client: LicenseClient, monitor: "LicenseMonitor | None", parent=None):
        super().__init__(parent)
        self.client = client
        self.monitor = monitor
        self.setWindowTitle("Licence")
        self.setMinimumWidth(520)
        self.form = QFormLayout()
        self.labels = {name: QLabel() for name in ("status", "mode", "label", "key", "machine", "server", "last", "expires",
                                                   "version")}
        for lab in self.labels.values():
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.form.addRow("Status", self.labels["status"])
        self.form.addRow("Mode", self.labels["mode"])
        self.form.addRow("Licensed to", self.labels["label"])
        self.form.addRow("Key", self.labels["key"])
        self.form.addRow("Computer ID", self.labels["machine"])
        self.form.addRow("Platform", self.labels["server"])
        self.form.addRow("Last check", self.labels["last"])
        self.form.addRow("Expires", self.labels["expires"])
        self.form.addRow("Version", self.labels["version"])
        row = QHBoxLayout()
        check = QPushButton("Check now")
        check.setToolTip("Ask the platform for the licence status and for a newer version")
        check.clicked.connect(self._check_now)
        change = QPushButton("Change key…")
        change.clicked.connect(self._change_key)
        import_btn = QPushButton("Import licence file…")
        import_btn.clicked.connect(self._import)
        deactivate = QPushButton("Deactivate this computer")
        deactivate.clicked.connect(self._deactivate)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        for b in (check, change, import_btn, deactivate):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addLayout(row)
        self._refresh()

    def _refresh(self) -> None:
        st = self.client.state
        status, message = self.client.effective_status()
        color = theme.GREEN if status == Status.ACTIVE else theme.RED
        self.labels["status"].setText(f'<span style="color:{color}; font-weight:bold">{status.upper()}</span>'
                                      + (f" — {message}" if message else ""))
        if st.mode == MODE_OFFLINE:
            self.labels["mode"].setText(f"Offline licence file, valid until {st.file_expires_at[:10] or '?'}"
                                        f" (issued {st.file_issued_at[:10] or '?'})")
        else:
            self.labels["mode"].setText("Online: key checked with the platform")
        self.labels["label"].setText(st.label or "—")
        self.labels["key"].setText(_mask(st.key) if st.key else "—")
        self.labels["machine"].setText(st.machine_id)
        self.labels["server"].setText(st.server)
        last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.last_check)) if st.last_check else "never"
        if st.last_error:
            last += f"  (failed: {st.last_error})"
        self.labels["last"].setText(last)
        self.labels["expires"].setText(st.expires_at or "never")
        offer = self.client.update_offer()
        if offer:
            note = "required by your administrator" if offer["required"] else "use Update in the toolbar"
            self.labels["version"].setText(f'{__version__}  ·  <span style="color:{theme.GREEN}; font-weight:bold">'
                                           f'{offer["version"]} available</span> ({note})')
        else:
            self.labels["version"].setText(f"{__version__} (latest)" if st.update_version else __version__)

    def _check_now(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.client.check()
        finally:
            QApplication.restoreOverrideCursor()
        if self.monitor is not None:
            self.monitor.publish()
        self._refresh()

    def _change_key(self) -> None:
        dlg = ActivationDialog(self.client, parent=self)
        dlg.exec()
        if self.monitor is not None:
            self.monitor.publish()
        self._refresh()

    def _import(self) -> None:
        ok, message = import_license_file(self.client, parent=self)
        if message:
            color = theme.GREEN if ok else theme.RED
            self.labels["status"].setText(f'<span style="color:{color}">{message}</span>')
        if ok:
            if self.monitor is not None:
                self.monitor.publish()
            self._refresh()

    def _deactivate(self) -> None:
        self.client.deactivate()
        if self.monitor is not None:
            self.monitor.publish()
        self._refresh()


class LockScreen(QWidget):
    """Shown instead of the tiles while the licence does not allow running."""

    check_again = Signal()
    enter_key = Signal()
    import_file = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {theme.BG};")
        self.title = QLabel("LOCKED")
        f = QFont()
        f.setPointSizeF(28)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet(f"color: {theme.RED};")
        self.title.setAlignment(Qt.AlignCenter)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px;")
        self.machine = QLabel("")
        self.machine.setAlignment(Qt.AlignCenter)
        self.machine.setStyleSheet(f"color: {theme.MUTED};")
        self.machine.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.check_btn = QPushButton("Check again")
        self.check_btn.clicked.connect(self.check_again.emit)
        self.key_btn = QPushButton("Enter a licence key…")
        self.key_btn.clicked.connect(self.enter_key.emit)
        self.file_btn = QPushButton("Import licence file…")
        self.file_btn.clicked.connect(self.import_file.emit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.check_btn)
        row.addWidget(self.key_btn)
        row.addWidget(self.file_btn)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addStretch(2)
        layout.addWidget(self.title)
        layout.addSpacing(12)
        layout.addWidget(self.message)
        layout.addSpacing(8)
        layout.addWidget(self.machine)
        layout.addSpacing(20)
        layout.addLayout(row)
        layout.addStretch(3)

    def show_status(self, status: str, message: str, machine_id: str, server: str) -> None:
        self.title.setText(LOCK_TITLES.get(status, "Locked").upper())
        self.message.setText(message or "Contact the administrator of the licensing platform.")
        self.machine.setText(f"Computer ID {machine_id}  ·  {server.replace('https://', '')}")
        self.key_btn.setDefault(status in NEEDS_ACTIVATION)
        self.check_btn.setDefault(status not in NEEDS_ACTIVATION)


class LicenseMonitor(QObject):
    """Checks in with the platform in the background and announces status changes.

    Two threads: one checks in every few minutes; the other waits on the platform for news, so
    a lock or unlock from the dashboard shows within seconds instead of at the next check-in.
    """

    status_changed = Signal(str, str)   # status, message
    update_offered = Signal(object)     # the offer dict from LicenseClient.update_offer(), or None

    def __init__(self, client: LicenseClient, parent=None):
        super().__init__(parent)
        self.client = client
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._last: tuple[str, str] | None = None
        self._last_offer: tuple | None = ()
        self._thread = threading.Thread(target=self._loop, name="licence", daemon=True)
        self._watcher = threading.Thread(target=self._watch, name="licence-watch", daemon=True)
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.publish)   # ages the offline grace even without a check-in

    def start(self) -> None:
        self._thread.start()
        self._watcher.start()
        self._timer.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._timer.stop()

    def check_now(self) -> None:
        self._wake.set()

    def publish(self) -> None:
        """Emit the current effective status if it differs from the last one announced."""
        self.client.tick()
        current = self.client.effective_status()
        if current != self._last:
            self._last = current
            self.status_changed.emit(*current)
        offer = self.client.update_offer()
        key = (offer["version"], offer["required"]) if offer else None
        if key != self._last_offer:
            self._last_offer = key
            self.update_offered.emit(offer)

    def _check(self) -> None:
        if self.client.state.status not in NEEDS_ACTIVATION or self.client.state.token:
            self.client.check()
        self.publish()

    def _loop(self) -> None:
        next_check = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now >= next_check:
                self._check()
                next_check = time.time() + max(30, self.client.state.interval_s)
            self._wake.wait(timeout=min(30.0, max(1.0, next_check - time.time())))
            if self._wake.is_set():
                self._wake.clear()
                next_check = 0.0

    def _watch(self) -> None:
        backoff = 0.0
        unsettled = 0
        while not self._stop.is_set():
            if not self.client.can_wait():
                self._stop.wait(30)
                continue
            sent = self.client.state.status
            started = time.time()
            try:
                changed = self.client.wait_for_change()
            except ServerUnreachable as exc:
                # Offline, a deploy on the platform, or a platform without the endpoint: try again later.
                backoff = min(WATCH_BACKOFF_MAX_S, backoff * 2 or 5.0)
                log.debug("licence watch: %s; next try in %.0f s", exc, backoff)
                self._stop.wait(backoff)
                continue
            except Exception:  # noqa: BLE001 - the watcher must never die; the periodic check-in still runs
                log.exception("licence watch failed")
                self._stop.wait(60)
                continue
            backoff = 0.0
            if not changed:
                # The platform holds an unchanged answer for ~25 s; one that comes back at once (a proxy
                # in the way, say) must not turn this into a busy loop.
                if time.time() - started < 2:
                    self._stop.wait(15)
                continue
            log.info("licence: the platform reports a change; checking in now")
            self._check()
            # A check-in that leaves the status as it was makes the next wait answer at once.
            # Once may be a quick lock-and-unlock; twice in a row means it will not settle: slow down.
            unsettled = unsettled + 1 if self.client.state.status == sent else 0
            if unsettled >= 2:
                self._stop.wait(30)
