"""Dark control-room theme. Colours live here so the meter, tiles and window agree."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

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
