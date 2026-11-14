"""Colours and the application style sheet."""

from __future__ import annotations

ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
TEXT = "#1f2933"
MUTED = "#64748b"
BORDER = "#dde2e8"
BACKGROUND = "#f3f5f8"
PANEL = "#ffffff"
SELECTED = "#dbe7fb"
OK = "#16a34a"
WARNING = "#d97706"
ERROR = "#dc2626"

STATE_COLOURS = {"done": OK, "todo": "#9aa5b1", "warning": WARNING, "error": ERROR}
STATE_ICONS = {
    "done": "circle-check",
    "todo": "circle-dashed",
    "warning": "triangle-alert",
    "error": "circle-x",
}

STYLE_SHEET = f"""
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 5px; }}
QMenuBar::item:selected {{ background: #eaf0f8; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {SELECTED}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px 6px; spacing: 2px; }}
QToolBar QToolButton {{ padding: 4px 9px; border-radius: 6px; color: {TEXT}; }}
QToolBar QToolButton:hover {{ background: #eaf0f8; }}
QToolBar QToolButton:pressed {{ background: {SELECTED}; }}
QToolBar QToolButton:disabled {{ color: #aab4c0; }}
QToolBar::separator {{ width: 1px; background: {BORDER}; margin: 6px 6px; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT_DARK}; }}
QPushButton {{ background: {PANEL}; border: 1px solid #c9d1db; border-radius: 6px; padding: 5px 12px; color: {TEXT}; }}
QPushButton:hover {{ background: #f0f4f9; }}
QPushButton:pressed {{ background: #e2e8f0; }}
QPushButton:disabled {{ color: #aab4c0; background: {BACKGROUND}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT_DARK}; font-weight: 600; padding: 7px 14px; }}
QPushButton[primary="true"]:hover {{ background: {ACCENT_DARK}; }}
QPushButton[primary="true"]:disabled {{ background: #a9c0f0; border-color: #a9c0f0; color: white; }}
QPushButton[card="true"] {{ text-align: left; padding: 12px 14px; border-radius: 10px; }}
QPushButton[card="true"]:hover {{ border-color: {ACCENT}; background: #f5f9ff; }}
QLineEdit {{ border: 1px solid #c9d1db; border-radius: 5px; padding: 3px 6px; background: white; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ background: #eef1f5; color: #8a96a3; }}
QLineEdit[invalid="true"] {{ border: 1px solid {ERROR}; background: #fef2f2; color: #991b1b; }}
QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; outline: none; padding: 3px; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 5px; color: {TEXT}; }}
QListWidget::item:selected {{ background: {SELECTED}; color: {TEXT}; }}
QListWidget::item:hover:!selected {{ background: #f1f4f8; }}
QListWidget#steps {{ border: none; background: transparent; padding: 0; }}
QListWidget#steps::item {{ padding: 0; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: {PANEL}; top: -1px; }}
QTabBar::tab {{ padding: 6px 14px; border: 1px solid transparent; border-top-left-radius: 6px; border-top-right-radius: 6px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: {PANEL}; border-color: {BORDER}; border-bottom-color: {PANEL}; color: {TEXT}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QToolTip {{ background: #1f2937; color: white; border: none; padding: 5px 7px; }}
QProgressBar {{ border: 1px solid #c9d1db; border-radius: 6px; text-align: center; background: white; max-height: 14px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QScrollArea {{ background: transparent; border: none; }}
QPlainTextEdit {{ border: none; background: #fbfcfd; }}
QTableWidget {{ border: 1px solid {BORDER}; border-radius: 6px; gridline-color: #eef1f5; background: white; }}
QHeaderView::section {{ background: {BACKGROUND}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px; }}
QLabel[role="title"] {{ font-size: 22pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="subtitle"] {{ font-size: 10.5pt; color: {MUTED}; }}
QLabel[role="heading"] {{ font-size: 11pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="issues"] {{ background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; padding: 7px 9px; color: #7c2d12; }}
QLabel[role="ready"] {{ background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; padding: 7px 9px; color: #14532d; }}
QWidget#viewbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QWidget#viewbar QToolButton {{ border: none; padding: 3px 7px; border-radius: 5px; color: {TEXT}; }}
QWidget#viewbar QToolButton:hover {{ background: #eaf0f8; }}
QWidget#viewbar QToolButton:checked {{ background: {SELECTED}; }}
QWidget#navbar {{ background: transparent; }}
"""


def apply_style(app) -> None:
    """Give the whole application EasyFOAM's look."""
    from PySide6.QtGui import QColor, QFont, QPalette

    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BACKGROUND))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9aa5b1"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#9aa5b1"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#9aa5b1"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#9aa5b1"))
    app.setPalette(palette)
    font = QFont(app.font())
    font.setPointSizeF(9.5)
    app.setFont(font)
    app.setStyleSheet(STYLE_SHEET)


def set_primary(button) -> None:
    """Mark a button as the main action of its panel."""
    button.setProperty("primary", True)
