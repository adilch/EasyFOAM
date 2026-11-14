"""Colours, the light and dark themes, the text size and the application style sheet.

The colours are module attributes (``style.TEXT``, ``style.PANEL`` …) of the theme in use. Code that paints reads
them when it paints, so that a change of theme reaches it; icons drawn in the default colour follow by themselves
(see ``icons``). ``set_theme`` and ``set_text_size`` change the look of the running application.
"""

from __future__ import annotations

LIGHT = {
    "accent": "#2563eb", "accent_dark": "#1d4ed8", "title": "#1d4ed8",
    "text": "#1f2933", "muted": "#64748b", "border": "#dde2e8", "background": "#f3f5f8", "panel": "#ffffff",
    "selected": "#dbe7fb", "ok": "#16a34a", "warning": "#d97706", "error": "#dc2626",
    "hover": "#eaf0f8", "hover_soft": "#f1f4f8", "button_hover": "#f0f4f9", "pressed": "#e2e8f0",
    "disabled_text": "#aab4c0", "field": "#ffffff", "field_border": "#c9d1db", "primary_disabled": "#a9c0f0",
    "card_hover": "#f5f9ff", "disabled_field": "#eef1f5", "disabled_field_text": "#8a96a3", "grid": "#eef1f5",
    "invalid_bg": "#fef2f2", "invalid_text": "#991b1b", "tooltip_bg": "#1f2937", "tooltip_text": "#ffffff",
    "log": "#fbfcfd", "issues_bg": "#fff7ed", "issues_border": "#fed7aa", "issues_text": "#7c2d12",
    "ready_bg": "#f0fdf4", "ready_border": "#bbf7d0", "ready_text": "#14532d", "step_hover": "#e9edf2",
    "placeholder": "#9aa5b1", "handle": "#9aa5b1", "handle_hover": "#e3ecf9", "icon": "#3d4a5c",
    "icon_disabled": "#b3bcc8", "view_bottom": "#f4f6f8", "view_top": "#cfd9e3", "view_text": "#27313b",
    "view_line": "#44505c", "plot_bg": "#ffffff", "plot_fg": "#27313b",
}  # fmt: skip

DARK = {
    "accent": "#3b82f6", "accent_dark": "#2563eb", "title": "#7fb0ff",
    "text": "#e4e8ee", "muted": "#98a2b3", "border": "#323946", "background": "#15181e", "panel": "#1d2129",
    "selected": "#24395f", "ok": "#22c55e", "warning": "#f59e0b", "error": "#f87171",
    "hover": "#283040", "hover_soft": "#232833", "button_hover": "#262c37", "pressed": "#2e3644",
    "disabled_text": "#5c6574", "field": "#242933", "field_border": "#3b4350", "primary_disabled": "#2a3a5c",
    "card_hover": "#22314d", "disabled_field": "#1b1f26", "disabled_field_text": "#5f6876", "grid": "#2c323d",
    "invalid_bg": "#3a1d22", "invalid_text": "#fca5a5", "tooltip_bg": "#0d0f13", "tooltip_text": "#e4e8ee",
    "log": "#191c22", "issues_bg": "#33260f", "issues_border": "#6b4a14", "issues_text": "#fcd9a3",
    "ready_bg": "#122a1c", "ready_border": "#1e5a37", "ready_text": "#b9f3cf", "step_hover": "#232833",
    "placeholder": "#6b7482", "handle": "#5a6372", "handle_hover": "#243049", "icon": "#c9d1dc",
    "icon_disabled": "#555e6c", "view_bottom": "#1a1e25", "view_top": "#2d3542", "view_text": "#dfe5ec",
    "view_line": "#a7b1bf", "plot_bg": "#191c22", "plot_fg": "#c9d1dc",
}  # fmt: skip

THEMES = {"light": LIGHT, "dark": DARK}
THEME_NAMES = {"light": "Light", "dark": "Dark", "system": "Same as Windows"}
TEXT_SIZE = 9.5  # points, as at first
TEXT_SIZES = (8.0, 14.0)  # smallest and largest

STATE_ICONS = {
    "done": "circle-check",
    "todo": "circle-dashed",
    "warning": "triangle-alert",
    "error": "circle-x",
}

# the colours of the theme in use, as module attributes; filled in by _use below
ACCENT = ACCENT_DARK = TITLE = TEXT = MUTED = BORDER = BACKGROUND = PANEL = SELECTED = OK = WARNING = ERROR = ""
STATE_COLOURS: dict[str, str] = {}
STYLE_SHEET = ""
theme = "light"  # the theme chosen: light, dark or system
text_size = TEXT_SIZE


def _sheet(c: dict[str, str], size: float) -> str:
    return f"""
QMainWindow, QDialog {{ background: {c['background']}; }}
QWidget {{ font-size: {size:g}pt; }}
QMenuBar {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; color: {c['text']}; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {c['hover']}; }}
QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 4px; color: {c['text']}; }}
QMenu::item {{ padding: 6px 22px 6px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['disabled_text']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
QToolBar {{ background: {c['panel']}; border: none; border-bottom: 1px solid {c['border']}; padding: 4px 6px; spacing: 2px; }}
QToolBar QToolButton {{ padding: 4px 9px; border-radius: 6px; color: {c['text']}; }}
QToolBar QToolButton:hover {{ background: {c['hover']}; }}
QToolBar QToolButton:pressed {{ background: {c['selected']}; }}
QToolBar QToolButton:disabled {{ color: {c['disabled_text']}; }}
QToolBar::separator {{ width: 1px; background: {c['border']}; margin: 6px 6px; }}
QGroupBox {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['title']}; }}
QGroupBox[folded="true"] {{ background: transparent; border: 1px solid transparent; padding: 0px; }}
QPushButton {{ background: {c['panel']}; border: 1px solid {c['field_border']}; border-radius: 6px; padding: 5px 12px; color: {c['text']}; }}
QPushButton:hover {{ background: {c['button_hover']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:disabled {{ color: {c['disabled_text']}; background: {c['background']}; }}
QPushButton[primary="true"] {{ background: {c['accent']}; color: white; border: 1px solid {c['accent_dark']}; font-weight: 600; padding: 7px 14px; }}
QPushButton[primary="true"]:hover {{ background: {c['accent_dark']}; }}
QPushButton[primary="true"]:disabled {{ background: {c['primary_disabled']}; border-color: {c['primary_disabled']}; color: white; }}
QPushButton[card="true"] {{ text-align: left; padding: 12px 14px; border-radius: 10px; }}
QPushButton[card="true"]:hover {{ border-color: {c['accent']}; background: {c['card_hover']}; }}
QLineEdit {{ border: 1px solid {c['field_border']}; border-radius: 5px; padding: 3px 6px; background: {c['field']}; color: {c['text']}; }}
QLineEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled {{ background: {c['disabled_field']}; color: {c['disabled_field_text']}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {c['error']}; background: {c['invalid_bg']}; color: {c['invalid_text']}; }}
QListWidget {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; outline: none; padding: 3px; color: {c['text']}; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 5px; color: {c['text']}; }}
QListWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
QListWidget::item:hover:!selected {{ background: {c['hover_soft']}; }}
QListWidget#steps {{ border: none; background: transparent; padding: 0; }}
QListWidget#steps::item {{ padding: 0; }}
QListWidget#searchResults {{ border: 1px solid {c['field_border']}; border-radius: 8px; padding: 3px; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 8px; background: {c['panel']}; top: -1px; }}
QTabBar::tab {{ padding: 6px 14px; border: 1px solid transparent; border-top-left-radius: 6px; border-top-right-radius: 6px; color: {c['muted']}; }}
QTabBar::tab:selected {{ background: {c['panel']}; border-color: {c['border']}; border-bottom-color: {c['panel']}; color: {c['text']}; }}
QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; color: {c['text']}; }}
QToolTip {{ background: {c['tooltip_bg']}; color: {c['tooltip_text']}; border: none; padding: 5px 7px; }}
QProgressBar {{ border: 1px solid {c['field_border']}; border-radius: 6px; text-align: center; background: {c['field']}; max-height: 14px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
QScrollArea {{ background: transparent; border: none; }}
QPlainTextEdit {{ border: none; background: {c['log']}; color: {c['text']}; }}
QTableWidget {{ border: 1px solid {c['border']}; border-radius: 6px; gridline-color: {c['grid']}; background: {c['field']}; color: {c['text']}; }}
QHeaderView::section {{ background: {c['background']}; border: none; border-bottom: 1px solid {c['border']}; padding: 4px; color: {c['text']}; }}
QLabel[role="title"] {{ font-size: 22pt; font-weight: 600; color: {c['text']}; }}
QLabel[role="subtitle"] {{ font-size: {size + 1:g}pt; color: {c['muted']}; }}
QLabel[role="heading"] {{ font-size: {size + 1.5:g}pt; font-weight: 600; color: {c['text']}; }}
QLabel[role="issues"] {{ background: {c['issues_bg']}; border: 1px solid {c['issues_border']}; border-radius: 6px; padding: 7px 9px; color: {c['issues_text']}; }}
QLabel[role="ready"] {{ background: {c['ready_bg']}; border: 1px solid {c['ready_border']}; border-radius: 6px; padding: 7px 9px; color: {c['ready_text']}; }}
QWidget#viewbar {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
QWidget#viewbar QToolButton {{ border: none; padding: 3px 7px; border-radius: 5px; color: {c['text']}; }}
QWidget#viewbar QToolButton:hover {{ background: {c['hover']}; }}
QWidget#viewbar QToolButton:checked {{ background: {c['selected']}; }}
QWidget#navbar {{ background: transparent; }}
"""


def resolved(name: str | None = None) -> str:
    """The theme a choice comes to: "system" follows the colour scheme of Windows (light if it cannot tell)."""
    name = name or theme
    if name != "system":
        return name if name in THEMES else "light"
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return "dark"
    except (ImportError, AttributeError):
        pass
    return "light"


def colours(name: str | None = None) -> dict[str, str]:
    """The colours of a theme (the one in use when no name is given)."""
    return THEMES[resolved(name)]


def _use(name: str, size: float) -> None:
    global theme, text_size, STYLE_SHEET
    theme, text_size = name, size
    c = colours(name)
    globals().update({key.upper(): value for key, value in c.items()})
    STATE_COLOURS.clear()
    STATE_COLOURS.update({"done": c["ok"], "todo": c["placeholder"], "warning": c["warning"], "error": c["error"]})
    STYLE_SHEET = _sheet(c, size)


_use("light", TEXT_SIZE)


def choose(name: str, size: float = TEXT_SIZE) -> None:
    """Take a theme and a text size, without applying them yet (at start-up, before any window exists)."""
    _use(name if name in THEME_NAMES else "light", min(max(size, TEXT_SIZES[0]), TEXT_SIZES[1]))


class _Notifier:
    """Tells the parts of the window that paint themselves when the theme or the text size changes."""

    def __init__(self) -> None:
        self._listeners = []

    def connect(self, listener) -> None:
        self._listeners.append(listener)

    def disconnect(self, listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except RuntimeError:  # its widget is gone
                self.disconnect(listener)


changed = _Notifier()


def apply_style(app) -> None:
    """Give the whole application EasyFOAM's look, in the theme and text size in use."""
    from PySide6.QtGui import QColor, QFont, QPalette

    c = colours()
    app.setStyle("Fusion")
    palette = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "background"), (QPalette.ColorRole.WindowText, "text"),
                      (QPalette.ColorRole.Base, "field"), (QPalette.ColorRole.AlternateBase, "background"),
                      (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "panel"),
                      (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "accent"),
                      (QPalette.ColorRole.PlaceholderText, "placeholder"), (QPalette.ColorRole.ToolTipBase, "tooltip_bg"),
                      (QPalette.ColorRole.ToolTipText, "tooltip_text"), (QPalette.ColorRole.Light, "panel"),
                      (QPalette.ColorRole.Mid, "border"), (QPalette.ColorRole.Dark, "field_border")):  # fmt: skip
        palette.setColor(role, QColor(c[key]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["disabled_text"]))
    app.setPalette(palette)
    font = QFont(app.font())
    font.setPointSizeF(text_size)
    app.setFont(font)
    app.setStyleSheet(STYLE_SHEET)


def set_theme(name: str, app=None) -> None:
    """Change the theme (light, dark, or system: as Windows) of the running application."""
    if name not in THEME_NAMES:
        raise ValueError(f"no theme named {name!r}")
    _use(name, text_size)
    _refresh(app)


def set_text_size(points: float, app=None) -> None:
    """Make the text of the whole application larger or smaller (8 to 14 points)."""
    _use(theme, round(min(max(points, TEXT_SIZES[0]), TEXT_SIZES[1]) * 2) / 2)
    _refresh(app)


def _refresh(app) -> None:
    from PySide6.QtWidgets import QApplication

    app = app or QApplication.instance()
    if app is not None:
        apply_style(app)
    changed.emit()


def set_primary(button) -> None:
    """Mark a button as the main action of its panel."""
    button.setProperty("primary", True)
