# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build: one BarpiMonitor.exe with Qt and libmpv inside.

    pyinstaller monitor/BarpiMonitor.spec --noconfirm

libmpv-2.dll must be in monitor/vendor/ first (build.ps1 and the GitHub workflow fetch it).
"""
import sys
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
vendor_dll = spec_dir / "vendor" / "libmpv-2.dll"

binaries = []
if sys.platform == "win32":
    if not vendor_dll.exists():
        raise SystemExit(f"{vendor_dll} is missing: run monitor/build.ps1 (it downloads libmpv) "
                         "or copy libmpv-2.dll there by hand")
    binaries.append((str(vendor_dll), "."))

datas = [
    (str(spec_dir / "assets" / "icon.png"), "assets"),
    (str(spec_dir / "assets" / "icon.ico"), "assets"),
]

a = Analysis(
    [str(spec_dir / "run_monitor.py")],
    pathex=[str(spec_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest", "pytest", "numpy", "PIL",
        "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtPdf",
        "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtSvg",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtPrintSupport", "PySide6.QtRemoteObjects",
        "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtBluetooth",
        "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtTextToSpeech",
        "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BarpiMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(spec_dir / "assets" / "icon.ico") if sys.platform == "win32" else None,
)
