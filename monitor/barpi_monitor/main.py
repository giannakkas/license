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


# How vulkan-1.dll is provided: "system", "bundled", "missing", or "n/a" off Windows. Set by prepare_dll_path().
VULKAN_LOADER = "n/a"


def _system_has_vulkan() -> bool:
    """True when Windows can load vulkan-1.dll from System32, where graphics drivers install it."""
    import ctypes
    load_library_search_system32 = 0x00000800
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
    handle = kernel32.LoadLibraryExW("vulkan-1.dll", None, load_library_search_system32)
    if not handle:
        return False
    kernel32.FreeLibrary(handle)
    return True


def provide_vulkan_loader() -> str:
    """libmpv-2.dll imports vulkan-1.dll, which graphics drivers install but Windows itself does not.

    PCs with basic or older graphics, virtual machines and remote desktops may have none, and
    then libmpv cannot load at all. The official Khronos loader is bundled for those PCs only:
    it is loaded by full path before libmpv, so libmpv's import binds to it. A PC with its own
    loader keeps using that one.
    """
    if sys.platform != "win32":
        return "n/a"
    try:
        if _system_has_vulkan():
            return "system"
    except Exception as exc:  # noqa: BLE001 - the probe must never stop the program starting
        log.warning("could not probe for the system Vulkan loader: %s", exc)
    import ctypes
    for folder in (base_dir() / "vulkan-fallback", base_dir() / "vendor"):
        dll = folder / "vulkan-1.dll"
        if not dll.exists():
            continue
        try:
            ctypes.WinDLL(str(dll))
        except OSError as exc:
            log.warning("the bundled Vulkan loader %s could not be loaded: %s", dll, exc)
            continue
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(folder))
            except OSError:
                pass
        return "bundled"
    return "missing"


def prepare_dll_path() -> None:
    """Make libmpv findable: next to the exe, in the bundle, or in monitor/vendor when run from source."""
    global VULKAN_LOADER
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
    VULKAN_LOADER = provide_vulkan_loader()
    if VULKAN_LOADER != "n/a":
        log.info("Vulkan loader: %s", VULKAN_LOADER)


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
    parser.add_argument("--update", action="store_true",
                        help="install the newest version offered by the licensing platform without opening the "
                             "window, then exit (for IT scripts); the next start runs the new version")
    parser.add_argument("--version", action="store_true")
    return parser.parse_args(argv)


def update_from_command_line(cfg_path: Path, server: str | None) -> int:
    """``--update``: check in, then download, verify and install the newest build. 0 = done or up to date."""
    from .license import LicenseClient, ServerUnreachable, license_path, server_override
    from .updater import UpdateError, cleanup, current_exe, download, install, staged_path

    client = LicenseClient(license_path(cfg_path.parent), server=server or server_override())
    exe = current_exe()
    if exe is None:
        log.error("--update works on the packaged MonitoringApp.exe only")
        return 2
    cleanup(exe)
    if not client.state.token:
        log.error("--update: this computer is not activated yet")
        return 3
    try:
        client.check()
    except ServerUnreachable as exc:  # check() records outages itself; this is belt and braces
        log.error("--update: the licensing platform cannot be reached (%s)", exc)
        return 4
    offer = client.update_offer()
    if offer is None:
        st = client.state
        if st.installed_update and st.installed_update == st.update_version:
            log.warning("--update: the build offered as %s was installed already but reports version %s; "
                        "it is not installed again (check the version label on the platform)",
                        st.update_version, __version__)
        else:
            log.info("--update: %s is the newest version available", __version__)
        return 0
    try:
        new_file = download(offer["url"], staged_path(exe), offer["sha256"], int(offer.get("size") or 0))
        client.state.installed_update = offer["version"]
        client.save()
        mode = install(new_file, exe)
    except UpdateError as exc:
        client.state.installed_update = ""
        client.save()
        log.error("--update to %s failed: %s", offer["version"], exc)
        return 5
    if mode != "swapped":
        from .updater import finish_after_exit
        finish_after_exit(new_file, exe, [])
        log.info("--update: version %s will be in place once this process exits", offer["version"])
    else:
        log.info("--update: version %s installed; the next start runs it", offer["version"])
    return 0


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
    dump_every = os.environ.get("MONITORINGAPP_DUMP_STACKS", "")
    if dump_every.isdigit() and int(dump_every) > 0:
        # Support aid: write every thread's stack to stacks.txt in the settings folder every N seconds.
        import faulthandler
        faulthandler.dump_traceback_later(int(dump_every), repeat=True,
                                          file=open(cfg_path.parent / "stacks.txt", "w", encoding="utf-8"))  # noqa: SIM115
    prepare_dll_path()
    log.info("%s %s starting; config %s", APP_NAME, __version__, cfg_path)

    if args.self_test:
        from .selftest import run_self_test
        return run_self_test(cfg_path.parent / "self-test.log")

    if args.update:
        return update_from_command_line(cfg_path, args.license_server)

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
        log.error("libmpv could not be loaded: %s", exc)
        hint = ("This computer has no Vulkan graphics loader (vulkan-1.dll). Update the graphics driver, or "
                "install the Vulkan Runtime from https://vulkan.lunarg.com, then start the program again."
                if VULKAN_LOADER == "missing" else
                "Download the program again from the licensing platform and replace MonitoringApp.exe.")
        QMessageBox.critical(None, APP_NAME,
                             f"The playback engine (libmpv-2.dll) could not be loaded.\n\n{hint}\n\n"
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
