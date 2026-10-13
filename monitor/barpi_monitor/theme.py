"""Dark control-room theme. Colours live here so the meter, tiles and window agree."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

BG = "#0f1115"
PANEL = "#171a21"
PANEL_2 = "#1e222b"
BORDER = "#2a2f3a"
TEXT = "#e6e9ef"
MUTED = "#8b93a3"
ACCENT = "#3b82f6"      # audible / selected tile
GREEN = "#22c55e"
AMBER = "#f59e0b"
RED = "#ef4444"
TRACK = "#252a35"


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(PANEL))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL_2))
    pal.setColor(QPalette.ToolTipBase, QColor(PANEL_2))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(PANEL_2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.BrightText, QColor("#ffffff"))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(MUTED))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QToolBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; spacing: 6px; padding: 4px; }}
        QToolBar QToolButton {{ padding: 4px 8px; border-radius: 4px; }}
        QToolBar QToolButton:hover {{ background: {PANEL_2}; }}
        QToolBar QToolButton:checked {{ background: {ACCENT}; color: white; }}
        QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
        QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; }}
        QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
            background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 3px 6px; }}
        QSlider::groove:horizontal {{ height: 4px; background: {TRACK}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ width: 12px; margin: -5px 0; background: {TEXT}; border-radius: 6px; }}
        QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
        QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; }}
        QMenu::item:selected {{ background: {ACCENT}; }}
        QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 12px; }}
        QPushButton:hover {{ border-color: {ACCENT}; }}
        QPushButton:default {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
    """)


def apply_dark_title_bar(widget: QWidget) -> None:
    """Ask Windows for a dark title bar on this top-level window (no-op elsewhere).

    Windows draws the title bar itself and follows the system theme, not the app palette,
    so a dark app gets a white bar unless it opts in through DWM. Attribute 20 is the
    documented one (Windows 10 20H1+); 19 is the pre-release value older builds used.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.c_void_p(int(widget.winId()))
        value = ctypes.c_int(1)
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                return
    except Exception:  # noqa: BLE001 (cosmetic: never let this break the app)
        pass


class DarkTitleBarFilter(QObject):
    """Applies the dark title bar to every top-level window as it is shown (dialogs included)."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            apply_dark_title_bar(obj)
        return False
