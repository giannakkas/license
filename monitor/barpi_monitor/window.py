"""The main window: a grid of tiles, a toolbar, transport keys, the alarm log and the one-tile-audible rule."""
from __future__ import annotations

import csv
import html
import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QFileDialog, QGridLayout, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QSlider, QStackedWidget, QToolBar, QWidget)

from . import APP_NAME, __version__, theme
from .config import Config, Source, guess_name, is_url
from .dialogs import VIDEO_FILTER, SettingsDialog, SourceDialog
from .license import USABLE, LicenseClient
from .license_ui import ActivationDialog, LicenseDialog, LicenseMonitor, LockScreen
from .main import base_dir
from .tile import SourceTile

log = logging.getLogger(__name__)
MAX_GRID = 16


def auto_columns(n: int) -> int:
    if n <= 1:
        return 1
    if n <= 4:
        return 2
    if n <= 9:
        return 3
    if n <= 16:
        return 4
    return int(math.ceil(math.sqrt(n)))


class MainWindow(QMainWindow):
    def __init__(self, config: Config, config_path: Path, license_client: LicenseClient | None = None):
        super().__init__()
        self.config = config
        self.config_path = config_path
        self.license_client = license_client
        self.license_monitor: LicenseMonitor | None = None
        self._locked = False
        self.tiles: list[SourceTile] = []
        self._selected: SourceTile | None = None
        self._maximized: SourceTile | None = None

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(640, 400)
        self.resize(1280, 760)
        self.setAcceptDrops(True)

        # The centre is either the grid of tiles or, while the licence forbids running, the lock screen.
        self.stack = QStackedWidget()
        self.grid_host = QWidget()
        self.grid_host.setStyleSheet(f"background: {theme.BG};")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.grid.setSpacing(6)
        self.lock_screen = LockScreen()
        self.lock_screen.check_again.connect(self._license_check_now)
        self.lock_screen.enter_key.connect(self._license_enter_key)
        self.stack.addWidget(self.grid_host)
        self.stack.addWidget(self.lock_screen)
        self.setCentralWidget(self.stack)
        central = self.grid_host
        self.empty_label = QLabel(
            "No sources yet.\n\nAdd a stream (RTSP, SRT, UDP, RTMP, HLS, HTTP) with Ctrl+N,\n"
            "open video files with Ctrl+O, or drop files onto this window.", central)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px;")

        self._build_toolbar()
        self._build_alarm_log()
        self._build_shortcuts()
        self.status_left = QLabel("")
        self.status_right = QLabel("")
        self.statusBar().addWidget(self.status_left, 1)
        self.statusBar().addPermanentWidget(self.status_right)

        if config.geometry:
            self.restoreGeometry(QByteArray.fromBase64(config.geometry.encode("ascii")))

        for source in config.sources:
            self._create_tile(source)
        self._relayout()
        self._populate_devices()
        self._apply_audible(config.audible, save=False)
        if self.tiles:
            self._select_tile(self.tiles[max(0, min(config.audible, len(self.tiles) - 1))], make_audible=False)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.save_config)
        self._beep_timer = QTimer(self)
        self._beep_timer.setInterval(4000)
        self._beep_timer.timeout.connect(self._maybe_beep)
        self._beep_timer.start()
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._update_status)
        self._clock.start()
        self._update_status()

    # ------------------------------------------------------------------ toolbar, log, keys

    def _action(self, text, slot, shortcut=None, checkable=False, tip=None, toolbar=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        a.setToolTip((tip or text) + (f"  ({shortcut})" if shortcut else ""))
        if toolbar is not None:
            toolbar.addAction(a)
        else:
            self.addAction(a)
        return a

    def _build_toolbar(self) -> None:
        """Two rows: the logo with sources and view on top, playback and audio underneath."""
        tb = QToolBar("Sources and view")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        act = lambda *a, **k: self._action(*a, toolbar=tb, **k)  # noqa: E731

        logo = self._logo_label()
        if logo is not None:
            tb.addWidget(logo)
            tb.addSeparator()
        act("Add stream…", self._add_url, "Ctrl+N", tip="Add a network stream by URL")
        act("Add files…", self._add_files, "Ctrl+O", tip="Add video files")
        act("Edit", self._edit_selected, "F2", tip="Edit the selected source")
        act("Remove", self._remove_selected, "Delete", tip="Remove the selected source")
        tb.addSeparator()
        tb.addWidget(QLabel(" Layout "))
        self.layout_combo = QComboBox()
        self.layout_combo.setFocusPolicy(Qt.NoFocus)
        self.layout_combo.addItem("Auto", 0)
        for c in (1, 2, 3, 4, 5, 6):
            self.layout_combo.addItem(f"{c} col", c)
        idx = self.layout_combo.findData(self.config.layout_columns)
        self.layout_combo.setCurrentIndex(max(0, idx))
        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        tb.addWidget(self.layout_combo)
        self.act_log = act("Alarm log", self._toggle_log, "Ctrl+L", checkable=True, tip="Show the alarm log panel")
        self.act_fullscreen = act("Full screen", self._toggle_fullscreen, "F11", checkable=True)
        self.act_top = act("On top", self._toggle_on_top, checkable=True, tip="Keep this window above others")
        tb.addSeparator()
        act("Settings…", self._open_settings, "Ctrl+,")
        if self.license_client is not None:
            act("Licence", self._open_license, tip="Licence status, change key, deactivate this computer")
        act("Help", self._about, "F1")
        self._toolbars = [tb]

        self.addToolBarBreak()
        tb2 = QToolBar("Playback and audio")
        tb2.setMovable(False)
        tb2.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb2)
        act2 = lambda *a, **k: self._action(*a, toolbar=tb2, **k)  # noqa: E731

        act2("Play/Pause", self._play_pause_selected, "Space", tip="Play or pause the selected source")
        act2("Stop", self._stop_selected, tip="Stop the selected source")
        act2("Restart", self._restart_selected, "F5", tip="Reconnect / restart the selected source from the beginning")
        self.act_pause_all = act2("Pause all", self._pause_all, "Ctrl+Space", checkable=True,
                                  tip="Pause every source; untick to resume them all")
        tb2.addSeparator()
        self.act_mute = act2("Mute all", self._toggle_mute_all, "M", checkable=True,
                             tip="Silence the speakers (meters keep working)")
        self.act_mute.setChecked(self.config.mute_all)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 130)
        self.volume.setValue(self.config.settings.volume)
        self.volume.setFixedWidth(110)
        self.volume.setFocusPolicy(Qt.NoFocus)
        self.volume.setToolTip("Monitor volume")
        self.volume.valueChanged.connect(self._set_volume)
        tb2.addWidget(QLabel(" Vol "))
        tb2.addWidget(self.volume)
        tb2.addWidget(QLabel("  Audio out "))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(180)
        self.device_combo.setFocusPolicy(Qt.NoFocus)
        self.device_combo.setToolTip("Which sound device plays the audible source")
        self.device_combo.currentIndexChanged.connect(self._audio_device_changed)
        tb2.addWidget(self.device_combo)
        self._toolbars.append(tb2)

    def _logo_label(self, height: int = 26) -> QLabel | None:
        """The owner's logo for the left of the toolbar, rendered sharp on high-DPI screens."""
        path = base_dir() / "assets" / "logo.png"
        pm = QPixmap(str(path))
        if pm.isNull():
            return None
        dpr = self.devicePixelRatioF() or 1.0
        scaled = pm.scaledToHeight(int(round(height * dpr)), Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        label = QLabel()
        label.setPixmap(scaled)
        label.setContentsMargins(8, 2, 10, 2)
        label.setToolTip(APP_NAME)
        label.setStyleSheet("background: transparent;")
        return label

    def _build_alarm_log(self) -> None:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(9)
        self.log_view.setFont(mono)
        self.log_view.setStyleSheet(f"background: {theme.PANEL}; color: {theme.TEXT}; border: none;")
        self.log_dock = QDockWidget("Alarm log", self)
        self.log_dock.setObjectName("alarmLog")
        self.log_dock.setWidget(self.log_view)
        self.log_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.log_dock.setStyleSheet(f"QDockWidget {{ color: {theme.MUTED}; }} QDockWidget::title {{ background: {theme.PANEL_2}; padding: 3px; }}")
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.log_dock.setVisible(self.config.show_alarm_log)
        self.log_dock.visibilityChanged.connect(self._log_visibility_changed)
        self.act_log.setChecked(self.config.show_alarm_log)
        self._log_line(f"{APP_NAME} {__version__} started")

    def _build_shortcuts(self) -> None:
        self._action("Seek back 5 s", lambda: self._seek_selected(-5), "Left")
        self._action("Seek forward 5 s", lambda: self._seek_selected(5), "Right")
        self._action("Seek back 30 s", lambda: self._seek_selected(-30), "Shift+Left")
        self._action("Seek forward 30 s", lambda: self._seek_selected(30), "Shift+Right")
        self._action("Back to start", self._seek_start_selected, "Home")
        self._action("Show selected alone", self._toggle_maximize_selected, "Return")
        self._action("Leave full screen / single view", self._escape, "Escape")
        for i in range(1, 10):
            self._action(f"Listen to tile {i}", lambda _=False, n=i: self._listen_to(n - 1), str(i))

    # ------------------------------------------------------------------ tiles

    def _create_tile(self, source: Source) -> SourceTile:
        tile = SourceTile(source, self.config.settings, self.grid_host)
        tile.player.devices.connect(lambda _d: self._populate_devices())
        tile.activated.connect(lambda t: self._select_tile(t, make_audible=True))
        tile.maximize_toggled.connect(self._toggle_maximize)
        tile.alarm_changed.connect(lambda _t: self._update_status())
        tile.alarm_started.connect(lambda t, name, detail: self._log_alarm(t, name, detail, True))
        tile.alarm_ended.connect(lambda t, name: self._log_alarm(t, name, "", False))
        tile.set_volume(self.config.settings.volume)
        self.tiles.append(tile)
        tile.start()
        return tile

    def _relayout(self) -> None:
        """Re-place the tiles in the grid.

        Tiles are never re-parented, hidden or shown here unless their visibility really
        changes: each one hosts a live mpv window owned by another thread, and hiding or
        re-parenting its native parent window makes Windows exchange synchronous messages
        between the two threads, which is how the GUI could freeze when a source was added.
        """
        while self.grid.count():
            self.grid.takeAt(0)
        for i in range(MAX_GRID + 1):
            self.grid.setRowStretch(i, 0)
            self.grid.setColumnStretch(i, 0)
        if self.empty_label.isHidden() == (not self.tiles):
            self.empty_label.setVisible(not self.tiles)
        if not self.tiles:
            self.grid.addWidget(self.empty_label, 0, 0)
            return
        if self._maximized is not None and self._maximized in self.tiles:
            shown = [self._maximized]
        else:
            self._maximized = None
            shown = list(self.tiles)
        for t in self.tiles:
            want = t in shown
            if t.isHidden() == want:
                t.setVisible(want)
        n = len(shown)
        cols = self.config.layout_columns or auto_columns(n)
        cols = max(1, min(cols, n))
        rows = int(math.ceil(n / cols))
        for i, t in enumerate(shown):
            self.grid.addWidget(t, i // cols, i % cols)
        for r in range(rows):
            self.grid.setRowStretch(r, 1)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

    def add_source(self, source: Source) -> None:
        self.config.sources.append(source)
        tile = self._create_tile(source)
        self._relayout()
        if len(self.tiles) == 1:
            self._populate_devices()
            self._apply_audible(0)
        self._select_tile(tile, make_audible=len(self.tiles) == 1)
        self.save_config()

    def _add_url(self) -> None:
        dlg = SourceDialog(parent=self)
        if dlg.exec():
            self.add_source(dlg.source())

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add video files", "", VIDEO_FILTER)
        for path in paths:
            self.add_source(Source(name=guess_name(path), url=path, loop=True))

    def _edit_selected(self) -> None:
        tile = self._selected
        if tile is None:
            return
        dlg = SourceDialog(tile.source, parent=self)
        if dlg.exec():
            new = dlg.source()
            idx = self.tiles.index(tile)
            self.config.sources[idx] = new
            tile.set_source(new)
            self.save_config()
            self._update_status()

    def _remove_selected(self) -> None:
        tile = self._selected
        if tile is None:
            return
        answer = QMessageBox.question(self, "Remove source", f"Remove “{tile.source.display_name()}”?",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        idx = self.tiles.index(tile)
        self.tiles.pop(idx)
        self.config.sources.pop(idx)
        if self._maximized is tile:
            self._maximized = None
        tile.close_player()
        self.grid.removeWidget(tile)
        tile.setParent(None)
        tile.deleteLater()
        self._selected = None
        self._relayout()
        if self.tiles:
            new_idx = min(idx, len(self.tiles) - 1)
            self._select_tile(self.tiles[new_idx], make_audible=True)
        else:
            self.config.audible = -1
        self.save_config()
        self._update_status()

    # ------------------------------------------------------------------ transport

    def _play_pause_selected(self) -> None:
        if self._selected is not None:
            self._selected.play_pause()

    def _stop_selected(self) -> None:
        if self._selected is not None:
            self._selected.stop()

    def _restart_selected(self) -> None:
        if self._selected is not None:
            self._selected.restart()

    def _seek_selected(self, seconds: float) -> None:
        if self._selected is not None:
            self._selected.seek_relative(seconds)

    def _seek_start_selected(self) -> None:
        if self._selected is not None:
            self._selected.seek_start()

    def _pause_all(self, checked: bool) -> None:
        for t in self.tiles:
            t.set_paused(bool(checked))

    def _toggle_maximize_selected(self) -> None:
        if self._selected is not None:
            self._toggle_maximize(self._selected)

    def _listen_to(self, index: int) -> None:
        if index < len(self.tiles):
            self._select_tile(self.tiles[index], make_audible=True)

    def _escape(self) -> None:
        if self.isFullScreen():
            self.act_fullscreen.setChecked(False)
            self.showNormal()
        elif self._maximized is not None:
            self._maximized = None
            self._relayout()

    # ------------------------------------------------------------------ selection / audio

    def _select_tile(self, tile: SourceTile, make_audible: bool) -> None:
        self._selected = tile
        for t in self.tiles:
            t.set_selected(t is tile)
        if make_audible:
            self._apply_audible(self.tiles.index(tile))

    def _apply_audible(self, index: int, save: bool = True) -> None:
        if not self.tiles:
            index = -1
        elif index < 0 or index >= len(self.tiles):
            index = 0
        self.config.audible = index
        for i, t in enumerate(self.tiles):
            t.set_audible(i == index and not self.config.mute_all)
        self._update_status()
        if save:
            self._save_soon()

    def _toggle_maximize(self, tile: SourceTile) -> None:
        self._maximized = None if self._maximized is tile else tile
        self._relayout()

    def _toggle_mute_all(self, checked: bool) -> None:
        self.config.mute_all = bool(checked)
        self._apply_audible(self.config.audible)

    def _set_volume(self, value: int) -> None:
        self.config.settings.volume = int(value)
        for t in self.tiles:
            t.set_volume(value)
        self._save_soon()

    def _populate_devices(self) -> None:
        devices = self.tiles[0].player.audio_devices() if self.tiles else [("auto", "Autoselect device")]
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for name, desc in devices:
            self.device_combo.addItem(desc, name)
        idx = self.device_combo.findData(self.config.settings.audio_device)
        self.device_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.device_combo.blockSignals(False)

    def _audio_device_changed(self, index: int) -> None:
        name = self.device_combo.itemData(index) or "auto"
        self.config.settings.audio_device = name
        for t in self.tiles:
            t.player.set_audio_device(name)
        self._save_soon()

    def _layout_changed(self, index: int) -> None:
        self.config.layout_columns = int(self.layout_combo.itemData(index) or 0)
        self._relayout()
        self._save_soon()

    # ------------------------------------------------------------------ alarm log

    def _log_line(self, text: str, color: str | None = None) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        body = html.escape(f"{stamp}  {text}")
        if color:
            body = f'<span style="color: {color}; font-weight: bold;">{body}</span>'
        else:
            body = f'<span style="color: {theme.MUTED};">{body}</span>'
        self.log_view.appendHtml(body)

    def _log_alarm(self, tile: SourceTile, name: str, detail: str, started: bool) -> None:
        source = tile.source.display_name()
        line = f"{'ALARM ' if started else 'clear '} {source}: {name}" + (f"  ({detail})" if detail else "")
        self._log_line(line, theme.RED if started else theme.GREEN)
        if self.config.settings.alarm_log:
            path = self.config_path.parent / "alarms.csv"
            try:
                new = not path.exists()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    if new:
                        w.writerow(["time", "source", "alarm", "event", "detail"])
                    w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), source, name, "start" if started else "end", detail])
            except OSError as exc:
                log.warning("could not write alarm log: %s", exc)
        self._update_status()

    def _toggle_log(self, checked: bool) -> None:
        self.log_dock.setVisible(bool(checked))

    def _log_visibility_changed(self, visible: bool) -> None:
        self.config.show_alarm_log = bool(visible)
        self.act_log.setChecked(bool(visible))
        self._save_soon()

    # ------------------------------------------------------------------ licence

    def on_license_status(self, status: str, message: str) -> None:
        """Called by the LicenseMonitor (and at start-up) with the status to act on."""
        if status in USABLE:
            self.set_locked(False)
        else:
            self.set_locked(True, status, message)

    def set_locked(self, locked: bool, status: str = "locked", message: str = "") -> None:
        if locked:
            client = self.license_client
            self.lock_screen.show_status(status, message, client.state.machine_id if client else "",
                                         client.state.server if client else "")
            if not self._locked:
                self._locked = True
                for t in self.tiles:
                    t.stop()
                self._log_line(f"LOCKED: {message or status}", theme.RED)
            self.stack.setCurrentWidget(self.lock_screen)
            for tb in self._toolbars:
                tb.setEnabled(False)
            self.setWindowTitle(f"LOCKED — {APP_NAME}")
        else:
            if self._locked:
                self._locked = False
                for t in self.tiles:
                    t.restart()
                self._log_line("licence OK: unlocked", theme.GREEN)
            self.stack.setCurrentWidget(self.grid_host)
            for tb in self._toolbars:
                tb.setEnabled(True)
            self._update_status()

    def _license_check_now(self) -> None:
        if self.license_client is None:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.license_client.check()
        finally:
            QApplication.restoreOverrideCursor()
        if self.license_monitor is not None:
            self.license_monitor.publish()
        else:
            self.on_license_status(*self.license_client.effective_status())

    def _license_enter_key(self) -> None:
        if self.license_client is None:
            return
        ActivationDialog(self.license_client, parent=self).exec()
        if self.license_monitor is not None:
            self.license_monitor.publish()
        else:
            self.on_license_status(*self.license_client.effective_status())

    def _open_license(self) -> None:
        if self.license_client is None:
            return
        LicenseDialog(self.license_client, self.license_monitor, parent=self).exec()
        if self.license_monitor is not None:
            self.license_monitor.publish()
        else:
            self.on_license_status(*self.license_client.effective_status())

    # ------------------------------------------------------------------ window

    def _toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _toggle_on_top(self, checked: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(checked))
        self.show()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config.settings, parent=self)
        if dlg.exec():
            self.config.settings = dlg.settings()
            for t in self.tiles:
                t.apply_settings(self.config.settings)
            self.save_config()

    def _about(self) -> None:
        libmpv = self.tiles[0].player.mpv_version if self.tiles else "not loaded"
        QMessageBox.about(self, f"About {APP_NAME}", f"""
            <h3>{APP_NAME} {__version__}</h3>
            <p>Multi-source video monitor with audio level meters and quality-control alarms.<br>
            Playback engine: {libmpv}</p>
            <p><b>Click</b> a tile to listen to it (one source is audible at a time).<br>
            <b>Double-click</b> a tile to show it alone; double-click or Esc to return.</p>
            <table>
            <tr><td><b>Space</b></td><td>play / pause the selected source</td></tr>
            <tr><td><b>← → / Shift+← →</b></td><td>seek 5 s / 30 s in a file</td></tr>
            <tr><td><b>Home</b></td><td>back to the start of a file</td></tr>
            <tr><td><b>Ctrl+Space</b></td><td>pause / resume everything</td></tr>
            <tr><td><b>1–9</b></td><td>listen to tile 1–9</td></tr>
            <tr><td><b>M</b></td><td>mute all</td></tr>
            <tr><td><b>Ctrl+N / Ctrl+O</b></td><td>add stream / add files</td></tr>
            <tr><td><b>F2 / Del / F5</b></td><td>edit / remove / restart the selected source</td></tr>
            <tr><td><b>Enter</b></td><td>show the selected source alone</td></tr>
            <tr><td><b>Ctrl+L</b></td><td>alarm log</td></tr>
            <tr><td><b>F11</b></td><td>full screen</td></tr>
            </table>
            <p>Meter: wide bar = peak (dBFS), inner bar = RMS, line = peak hold.<br>
            Green ≤ −18 dBFS, amber to −9 dBFS, red above.</p>
            <p>Alarms: NO SIGNAL, NO VIDEO, FROZEN, BLACK, OVER, TOO LOUD, SILENCE, L/R MISSING, LOW LEVEL.<br>
            Thresholds are in Settings; every start and end is listed in the alarm log and alarms.csv.</p>
            <p style="color:#8b93a3">Config: {self.config_path}</p>""")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        items: list[str] = []
        if md.hasUrls():
            for u in md.urls():
                items.append(u.toLocalFile() if u.isLocalFile() else u.toString())
        elif md.hasText():
            items = [line.strip() for line in md.text().splitlines() if line.strip()]
        for item in items:
            self.add_source(Source(name=guess_name(item), url=item, loop=not is_url(item)))
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.config.geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.save_config()
        if self.license_monitor is not None:
            self.license_monitor.stop()
        for t in self.tiles:
            t.close_player()
        super().closeEvent(event)

    # ------------------------------------------------------------------ status / persistence

    def _update_status(self) -> None:
        n = len(self.tiles)
        audible = self.tiles[self.config.audible] if 0 <= self.config.audible < n else None
        listening = "none" if (audible is None or self.config.mute_all) else audible.source.display_name()
        self.status_left.setText(f"{n} source{'s' if n != 1 else ''}  ·  listening: {listening}"
                                 + ("  (muted)" if self.config.mute_all and audible is not None else ""))
        alarms = [f"{t.source.display_name()}: {', '.join(t.alarms)}" for t in self.tiles if t.alarms]
        count = sum(len(t.alarms) for t in self.tiles)
        if alarms:
            self.status_right.setText("⚠ " + "   ".join(alarms[:4]) + ("  …" if len(alarms) > 4 else ""))
            self.status_right.setStyleSheet(f"color: {theme.RED}; font-weight: bold;")
            title = f"⚠ {count} alarm{'s' if count != 1 else ''} — {APP_NAME}"
        else:
            self.status_right.setText("all sources OK" if n else "")
            self.status_right.setStyleSheet(f"color: {theme.MUTED};")
            title = APP_NAME
        self.setWindowTitle(f"LOCKED — {APP_NAME}" if self._locked else title)

    def _maybe_beep(self) -> None:
        if self.config.settings.beep_on_alarm and any(t.alarms for t in self.tiles):
            QApplication.beep()

    def _save_soon(self) -> None:
        if hasattr(self, "_save_timer"):
            self._save_timer.start()

    def save_config(self) -> None:
        try:
            self.config.save(self.config_path)
        except OSError as exc:
            log.warning("could not save config: %s", exc)
