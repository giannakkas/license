"""Entry point: argument parsing, logging, DLL lookup, then the Qt application."""
from __future__ import annotations

import argparse
import locale
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME, ORG_NAME, __version__
from .config import Config, Source, default_config_path, guess_name, is_url

log = logging.getLogger("barpi_monitor")


def base_dir() -> Path:
    """Where bundled files live: the PyInstaller extraction dir when frozen, else ``monitor/``."""
    frozen = getattr(sys, "_MEIPASS", None)
    return Path(frozen) if frozen else Path(__file__).resolve().parent.parent


def prepare_dll_path() -> None:
    """Make libmpv findable: next to the exe, in the bundle, or in monitor/vendor when run from source."""
    candidates = [base_dir(), base_dir() / "vendor", Path(sys.executable).resolve().parent]
    for c in candidates:
        if not c.is_dir():
            continue
        os.environ["PATH"] = str(c) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(c))
            except OSError:
                pass


def setup_logging(log_dir: Path) -> None:
    handlers: list[logging.Handler] = []
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_dir / "monitor.log", maxBytes=1_000_000, backupCount=3,
                                            encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="MonitoringApp", description=f"{APP_NAME}: video monitor with audio level meters")
    parser.add_argument("sources", nargs="*", help="stream URLs or video files to add on start-up")
    parser.add_argument("-c", "--config", help="path to the config file (default: per-user app data)")
    parser.add_argument("--self-test", action="store_true", help="check libmpv, metering and Qt, then exit")
    parser.add_argument("--license-server", help="licensing platform URL (default: https://license.oncue.cy, "
                                                 "or BARPI_LICENSE_SERVER)")
    parser.add_argument("--version", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # A windowed Windows exe has no console: give print/argparse somewhere harmless to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    cfg_path = Path(args.config).expanduser() if args.config else default_config_path()
    setup_logging(cfg_path.parent)
    prepare_dll_path()
    log.info("%s %s starting; config %s", APP_NAME, __version__, cfg_path)

    if args.self_test:
        from .selftest import run_self_test
        return run_self_test(cfg_path.parent / "self-test.log")

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .theme import DarkTitleBarFilter, apply_theme

    app = QApplication(sys.argv[:1])
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    locale.setlocale(locale.LC_NUMERIC, "C")  # Qt applies the user locale; libmpv needs C numerics
    apply_theme(app)
    title_bar_filter = DarkTitleBarFilter(app)
    app.installEventFilter(title_bar_filter)
    for icon in (base_dir() / "assets" / "icon.ico", base_dir() / "assets" / "icon.png"):
        if icon.exists():
            app.setWindowIcon(QIcon(str(icon)))
            break

    from .player import MpvUnavailable, import_mpv
    try:
        import_mpv()
    except MpvUnavailable as exc:
        QMessageBox.critical(None, APP_NAME,
                             "The playback engine (libmpv-2.dll) could not be loaded.\n\n"
                             "Put libmpv-2.dll next to MonitoringApp.exe, or reinstall.\n\n"
                             f"Details: {exc}")
        return 2

    config = Config.load(cfg_path)
    for item in args.sources:
        config.sources.append(Source(name=guess_name(item), url=item, loop=not is_url(item)))

    from .license import NEEDS_ACTIVATION, LicenseClient, is_newer, license_path, server_override
    from .license_ui import ActivationDialog, LicenseMonitor
    from .updater import cleanup, current_exe
    from .window import MainWindow

    def excepthook(exc_type, exc, tb):
        log.error("unhandled exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = excepthook

    # Licence: a key is needed before the first start; afterwards the platform is asked
    # every few minutes and can lock this computer.
    client = LicenseClient(license_path(cfg_path.parent), server=args.license_server or server_override())
    exe = current_exe()
    if exe is not None:
        cleanup(exe)
    updated_note = ""
    if client.state.installed_update:
        if is_newer(client.state.installed_update, __version__):
            log.warning("the build installed as %s reports version %s; it will not be offered again",
                        client.state.installed_update, __version__)
        else:
            updated_note = f"updated to {__version__}"
            log.info("%s", updated_note)
            client.state.installed_update = ""
            client.save()
    status, message = client.effective_status()
    log.info("licence status at start: %s %s", status, message)
    if status in NEEDS_ACTIVATION:
        if not ActivationDialog(client, message=message).exec():
            return 0

    win = MainWindow(config, cfg_path, license_client=client)
    monitor = LicenseMonitor(client, parent=win)
    monitor.status_changed.connect(win.on_license_status)
    monitor.update_offered.connect(win.on_update_offer)
    win.license_monitor = monitor
    win.on_license_status(*client.effective_status())
    if updated_note:
        from . import theme
        win._log_line(updated_note, theme.GREEN)
    if exe is not None:
        # The previous build may still have been closing a moment ago: tidy up again shortly.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(20_000, lambda: cleanup(exe))
    monitor.start()
    win.show()
    return app.exec()
