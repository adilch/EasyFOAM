"""Find any setting or command of the window by typing part of its name (Ctrl+K).

The index is made from the window itself each time the search starts: every labelled field, tick box, button
and choice of the six steps, the sections of their forms, and every menu command. Words people use for things
the window names otherwise ("tailwater", "gauge", "Strickler", "CFL") lead to them too. Choosing a setting
opens its step and its section, scrolls to it and points it out; choosing a command runs it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QWidget,
)

from easyfoam.gui import style
from easyfoam.gui.icons import icon
from easyfoam.gui.layout import FoldingGroup, shown_if_unfolded, unfold_to

MAX_SHOWN = 12  # results listed at once
ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1

#: words people type for things the window calls otherwise, and what they lead to
SYNONYMS: dict[str, tuple[str, ...]] = {
    "tailwater": ("water level", "outlet"),
    "headwater": ("water level", "reservoir", "rating"),
    "downstream": ("outlet",),
    "upstream": ("inlet",),
    "strickler": ("manning", "roughness"),
    "chezy": ("roughness", "manning"),
    "roughness": ("manning", "ks"),
    "friction": ("manning", "roughness"),
    "discharge": ("flow rate",),
    "inflow": ("flow rate", "inlet"),
    "outflow": ("outlet",),
    "flow": ("flow rate", "discharge"),
    "depth": ("water level", "fill to a level"),
    "stage": ("water level", "rating"),
    "head": ("rating", "pressure", "long section"),
    "gauge": ("probe",),
    "gage": ("probe",),
    "monitor": ("probe", "discharge", "forces"),
    "cfl": ("courant",),
    "dt": ("time step",),
    "timestep": ("time step",),
    "duration": ("end time", "iterations"),
    "parallel": ("processor cores",),
    "cpu": ("processor cores",),
    "cores": ("processor cores",),
    "threads": ("processor cores",),
    "sediment": ("d50", "bed shear", "shields"),
    "scour": ("bed shear", "shields", "d50"),
    "erosion": ("bed shear", "shields"),
    "shields": ("bed shear",),
    "froude": ("long section",),
    "jump": ("long section",),
    "belanger": ("long section",),
    "energy": ("long section",),
    "profile": ("long section", "outline"),
    "residence": ("tracer test",),
    "t10": ("tracer test", "residence"),
    "baffling": ("tracer test", "residence"),
    "chlorine": ("tracer",),
    "concentration": ("tracer",),
    "age": ("water age",),
    "spillway": ("ogee", "stepped", "structure"),
    "weir": ("ogee", "labyrinth", "structure", "rating"),
    "stilling": ("basin",),
    "fish": ("fishway",),
    "pipe": ("culvert",),
    "dam": ("structure",),
    "river": ("terrain", "channel"),
    "survey": ("terrain",),
    "dem": ("terrain",),
    "grid": ("mesh", "cells"),
    "resolution": ("cells", "level", "refine"),
    "refinement": ("refine", "level"),
    "inflation": ("boundary layers",),
    "layers": ("boundary layers",),
    "screenshot": ("picture",),
    "image": ("picture",),
    "export": ("save the table", "picture", "report"),
    "csv": ("save the table",),
    "pdf": ("report",),
    "html": ("report",),
    "print": ("report",),
    "dark": ("theme",),
    "light": ("theme",),
    "font": ("text size",),
    "bigger": ("text size",),
    "smaller": ("text size",),
    "help": ("tutorial", "getting started"),
    "template": ("template",),
}

STEP_HINTS = {  # what each step is for, so that a search for the task finds the step
    "Geometry": "shapes structures channel terrain import STL draw",
    "Mesh": "cells grid refine snappyHexMesh blockMesh base mesh",
    "Physics": "flow type turbulence fluid water air gravity tracers",
    "Boundaries": "inlet outlet wall roughness conditions",
    "Run": "end time time step solver cores probes forces",
    "Results": "slice velocity pressure long section hydraulic results",
}


def normal(text: str) -> str:
    """Lower case, without accents and typographic quotes, for comparing."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().replace("’", "'").replace("‘", "'").replace("&", "")


def clean(text: str) -> str:
    """A label or menu text as shown, without accelerator marks, trailing colons and padding."""
    text = re.sub(r"&(?!&)", "", text).replace("&&", "&")
    return re.sub(r"\s+", " ", text).strip().rstrip(":").strip()


@dataclass
class Entry:
    text: str  # what it is called in the window
    where: str  # where it is: "Run › Forces", "View menu"
    kind: str  # setting, choice, button, section, step, command
    activate: Callable[[], None]
    keywords: str = ""  # its tooltip and other words that describe it
    shortcut: str = ""
    available: bool = True
    _title: str = field(default="", repr=False)
    _more: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        self._title = normal(self.text)
        self._more = normal(f"{self.where} {self.keywords}")


KIND_ORDER = {"setting": 0.3, "command": 0.25, "section": 0.2, "step": 0.2, "button": 0.15, "choice": 0.0}


def _found(option: str, text: str) -> float:
    """How well a word is found in a text: 1 at the start of a word; inside a word only if it is long enough not
    to be there by chance ("rating" is not looked for in "separating"); 0 not at all."""
    if option not in text:
        return 0.0
    if re.search(r"(^|[^a-z0-9])" + re.escape(option), text):
        return 1.0
    return 0.25 if len(option) >= 7 else 0.0


def score(entry: Entry, words: list[str]) -> float:
    """How well an entry answers the words typed (0: not at all). Every word must be found somewhere."""
    total = 0.0
    for word in words:
        found = []
        for k, option in enumerate((word, *SYNONYMS.get(word, ()))):
            weight = 1.0 if k == 0 else 0.7
            found.append(weight * max(4.5 * _found(option, entry._title), 1.0 * _found(option, entry._more)))
        best = max(found)
        if best == 0.0:
            return 0.0
        total += best + 0.25 * (sum(found) - best)  # more of the words it stands for: a closer answer
    query = " ".join(words)
    if entry._title == query:
        total += 3.0
    elif entry._title.startswith(query):
        total += 1.5
    return total + KIND_ORDER.get(entry.kind, 0.0) - len(entry.text) / 300 - (0.5 if not entry.available else 0.0)


def find(entries: list[Entry], query: str, limit: int = MAX_SHOWN) -> list[Entry]:
    """The entries that best answer what was typed, best first."""
    words = [w for w in re.split(r"[\s,;]+", normal(query)) if w]
    if not words:
        return []
    scored = [(score(e, words), i, e) for i, e in enumerate(entries)]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: (-s[0], s[1]))
    seen, result = set(), []
    for _, _, entry in scored:
        key = (entry.text, entry.where)
        if key not in seen:
            seen.add(key)
            result.append(entry)
        if len(result) >= limit:
            break
    return result


# --- what the window holds ------------------------------------------------------------------------------------


def _section(widget: QWidget, panel: QWidget) -> str:
    """The title of the section of the form a widget sits in."""
    parent = widget.parentWidget()
    while parent is not None and parent is not panel:
        if isinstance(parent, FoldingGroup):
            return parent.plain_title()
        if isinstance(parent, QGroupBox):
            return parent.title()
        parent = parent.parentWidget()
    return ""


def _first_widget(item) -> QWidget | None:
    """The widget of a form item: the widget itself, or the first input in a row of them."""
    if item is None:
        return None
    if item.widget() is not None:
        return item.widget()
    layout: QLayout | None = item.layout()
    if layout is None:
        return None
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is not None and not isinstance(widget, QLabel):
            return widget
    return None


def _tip(widget: QWidget | None) -> str:
    return widget.toolTip() if widget is not None else ""


def _button_text(button: QAbstractButton) -> str:
    text = clean(button.text())
    if text:
        return text
    tip = button.toolTip().split(".")[0].strip()  # an icon-only button: what its tooltip says it does
    return tip[:70]


def collect(window) -> list[Entry]:
    """Everything a search can lead to, as the window stands now."""
    from easyfoam.gui.main_window import STEPS

    entries: list[Entry] = []
    if window.project is not None:
        for row, name in enumerate(STEPS):
            entries.append(Entry(f"{name} step", "Workflow", "step", lambda r=row: go_to_step(window, r),
                                 STEP_HINTS.get(name, "")))  # fmt: skip
        for panel, step in zip(window.panels, STEPS):
            entries.extend(_panel_entries(window, panel, step))
    entries.extend(_menu_entries(window))
    viewer = getattr(window, "viewer", None)
    if viewer is not None and window.project is not None:
        for button in viewer.findChildren(QToolButton):
            text = clean(button.text())
            if text and button.isVisibleTo(viewer):
                entries.append(Entry(text, "3D view", "command", lambda b=button: _press(window, b),
                                     _tip(button), available=button.isEnabled()))  # fmt: skip
    return entries


def _panel_entries(window, panel: QWidget, step: str) -> list[Entry]:
    entries: list[Entry] = []
    seen: set[int] = set()

    def where(widget: QWidget) -> str:
        section = _section(widget, panel)
        return f"{step} › {section}" if section else step

    def add_widget(text: str, widget: QWidget, kind: str, keywords: str = "") -> None:
        if not text or id(widget) in seen:
            return
        seen.add(id(widget))
        entries.append(Entry(text, where(widget), kind, lambda w=widget: reveal(window, w), keywords or _tip(widget)))

    for group in panel.findChildren(QGroupBox):
        title = group.plain_title() if isinstance(group, FoldingGroup) else group.title()
        entries.append(Entry(clean(title), step, "section", lambda g=group: reveal(window, g, open_section=True),
                             group.note() if isinstance(group, FoldingGroup) else ""))  # fmt: skip
    for form in panel.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            span_item = form.itemAt(row, QFormLayout.ItemRole.SpanningRole)
            label = label_item.widget() if label_item is not None else None
            target = _first_widget(field_item)
            if isinstance(label, QCheckBox):  # a tick box that switches the field beside it
                add_widget(clean(label.text()), label, "setting")
            if isinstance(label, QLabel) and target is not None:
                text = clean(label.text())
                add_widget(text, target, "setting", f"{_tip(target)} {_tip(label)}")
                if isinstance(target, QComboBox):
                    entries.extend(_choices(window, target, text, where(target)))
            span = _first_widget(span_item)
            if isinstance(span, (QCheckBox, QPushButton)):
                add_widget(_button_text(span), span, "setting" if isinstance(span, QCheckBox) else "button")
    for button in panel.findChildren(QAbstractButton):
        if isinstance(button, (QCheckBox, QPushButton, QToolButton)):
            kind = "setting" if isinstance(button, QCheckBox) else "button"
            add_widget(_button_text(button), button, kind)
    return entries


def _choices(window, combo: QComboBox, label: str, place: str) -> list[Entry]:
    """The items of a drop-down list, each found by its own name (lists of numbers and long lists are left out)."""
    if combo.count() > 40:
        return []
    entries = []
    for index in range(combo.count()):
        text = clean(combo.itemText(index))
        if not text or re.fullmatch(r"[-+.\deE ]+", text):
            continue
        entries.append(Entry(text, f"{place} › {label}", "choice",
                             lambda c=combo, i=index: reveal(window, c, choice=i), label))  # fmt: skip
    return entries


def _menu_entries(window) -> list[Entry]:
    entries: list[Entry] = []

    def walk(menu: QMenu, path: str) -> None:
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            text = clean(action.text())
            if action.menu() is not None:
                walk(action.menu(), f"{path} › {text}")
                continue
            if not text:
                continue
            shortcut = action.shortcut().toString(action.shortcut().SequenceFormat.NativeText)
            keywords = f"{action.toolTip()} {action.statusTip()}"
            entries.append(Entry(text, f"{path} menu", "command", lambda a=action: _trigger(window, a), keywords,
                                 shortcut, action.isEnabled()))  # fmt: skip

    for top in window.menuBar().actions():
        if top.menu() is not None:
            walk(top.menu(), clean(top.text()))
    return entries


# --- going there ----------------------------------------------------------------------------------------------


def go_to_step(window, row: int) -> None:
    window.steps.setCurrentRow(row)
    window.workspace.set_folded(False)


def _trigger(window, action: QAction) -> None:
    if not action.isEnabled():
        window.statusBar().showMessage(f"“{clean(action.text())}” cannot be used right now.", 6000)
        return
    action.trigger()


def _press(window, button: QAbstractButton) -> None:
    if not button.isEnabled():
        window.statusBar().showMessage(f"“{_button_text(button)}” cannot be used right now.", 6000)
        return
    button.click()


def _page(window, widget: QWidget) -> int | None:
    for row in range(window.stack.count()):
        if window.stack.widget(row).isAncestorOf(widget):
            return row
    return None


def reveal(window, widget: QWidget, open_section: bool = False, choice: int | None = None) -> bool:
    """Show a control: open its step and its section, scroll to it, give it the focus and point it out."""
    from easyfoam.gui.main_window import STEPS

    row = _page(window, widget)
    if row is not None and window.steps.currentRow() != row:
        window.steps.setCurrentRow(row)
    window.workspace.set_folded(False)
    if open_section and isinstance(widget, FoldingGroup):
        widget.set_folded(False)
    unfold_to(widget)
    name = (widget.plain_title() if isinstance(widget, FoldingGroup) else
            clean(widget.text()) if isinstance(widget, QAbstractButton) else "")  # fmt: skip
    if not shown_if_unfolded(widget):
        step = STEPS[row] if row is not None else "this"
        what = f"“{name}”" if name else "That setting"
        hint = (" Select a boundary of the kind that uses it." if step == "Boundaries" else
                " It depends on other choices of the step, such as the flow type.")  # fmt: skip
        window.statusBar().showMessage(f"{what} is in the {step} step but not shown with the current choices.{hint}",
                                       10000)  # fmt: skip
        return False
    if not widget.isEnabled():
        window.statusBar().showMessage("Shown, but switched off by another choice: its tooltip says why.", 6000)

    def finish() -> None:
        scroll = window.stack.currentWidget()
        if hasattr(scroll, "ensureWidgetVisible") and scroll.isAncestorOf(widget):
            scroll.ensureWidgetVisible(widget, 40, 80)
        if widget.focusPolicy() != Qt.FocusPolicy.NoFocus and widget.isEnabled():
            widget.setFocus(Qt.FocusReason.ShortcutFocusReason)
            if isinstance(widget, QLineEdit):
                widget.selectAll()
        QTimer.singleShot(30, lambda: Flash(window, widget))
        if choice is not None and isinstance(widget, QComboBox) and widget.isEnabled():
            widget.showPopup()
            widget.view().setCurrentIndex(widget.model().index(choice, widget.modelColumn()))

    QTimer.singleShot(0, finish)  # once the step and its sections have been laid out
    return True


class Flash(QWidget):
    """A ring drawn round a control for a moment, to show where it is."""

    def __init__(self, window: QWidget, target: QWidget, ms: int = 1500) -> None:
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        rect = QRect(target.mapTo(window, QPoint(0, 0)), target.size()).adjusted(-4, -4, 4, 4)
        self.setGeometry(rect)
        self.show()
        self.raise_()
        QTimer.singleShot(ms, self.close)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(style.ACCENT), 2.5))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 6, 6)


# --- the search box -------------------------------------------------------------------------------------------


class _ResultDelegate(QStyledItemDelegate):
    """A result: its name, where it is beneath it, and its kind or shortcut on the right."""

    def sizeHint(self, option, index) -> QSize:
        line = option.fontMetrics.height()
        return QSize(200, 2 * line + 12)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        entry: Entry = index.data(ENTRY_ROLE)
        painter.save()
        rect = option.rect
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(style.SELECTED))
            painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 5, 5)
        line = option.fontMetrics.height()
        right = entry.shortcut or entry.kind
        small = QFont(option.font)
        small.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
        painter.setFont(small)
        painter.setPen(QColor(style.MUTED))
        side = painter.fontMetrics().horizontalAdvance(right) + 12
        painter.drawText(QRect(rect.right() - side, rect.top() + 6, side - 8, line),
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), right)  # fmt: skip
        where = painter.fontMetrics().elidedText(entry.where, Qt.TextElideMode.ElideLeft, rect.width() - 20)
        painter.drawText(QRect(rect.left() + 10, rect.top() + 6 + line, rect.width() - 20, line),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), where)  # fmt: skip
        painter.setFont(option.font)
        painter.setPen(QColor(style.TEXT if entry.available else style.MUTED))
        title = option.fontMetrics.elidedText(entry.text, Qt.TextElideMode.ElideRight, rect.width() - side - 20)
        painter.drawText(QRect(rect.left() + 10, rect.top() + 5, rect.width() - side - 20, line),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), title)  # fmt: skip
        painter.restore()


class SearchBox(QLineEdit):
    """The search field of the toolbar; the results open under it, over the window."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self.entries: list[Entry] = []
        self.setObjectName("search")
        self.setPlaceholderText("Search settings and commands   Ctrl+K")
        self.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.setClearButtonEnabled(True)
        self.setFixedWidth(330)
        self.setToolTip(
            "Type part of the name of a setting or command, or a word for it (Manning, tailwater, gauge, CFL), "
            "then press Enter."
        )
        # a window of its own, above the 3D view (a native window that covers any widget laid over it)
        self.results = QListWidget(window)
        self.results.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                    | Qt.WindowType.WindowDoesNotAcceptFocus)  # fmt: skip
        self.results.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.results.setObjectName("searchResults")
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results.setItemDelegate(_ResultDelegate(self.results))
        self.results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.hide()
        self.results.itemClicked.connect(self._activate_item)
        self.textEdited.connect(self._search)
        self._hide_timer = QTimer(self, singleShot=True, interval=150)
        self._hide_timer.timeout.connect(self.results.hide)
        window.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._window and event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide,
                                                       QEvent.Type.WindowDeactivate):  # fmt: skip
            self.results.hide()
        return False

    # -- searching
    def start(self) -> None:
        """Ctrl+K: put the cursor in the box, ready to type."""
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.selectAll()

    def focusInEvent(self, event) -> None:
        self._hide_timer.stop()
        self.entries = collect(self._window)  # as the window stands now
        super().focusInEvent(event)
        if self.text():
            self._search(self.text())

    def focusOutEvent(self, event) -> None:
        self._hide_timer.start()
        super().focusOutEvent(event)

    def _search(self, text: str) -> None:
        if not self.entries:
            self.entries = collect(self._window)
        found = find(self.entries, text)
        self.results.clear()
        for entry in found:
            item = QListWidgetItem(entry.text)
            item.setData(ENTRY_ROLE, entry)
            item.setToolTip(entry.keywords.strip()[:300] or entry.where)
            self.results.addItem(item)
        if not found:
            if text.strip():
                item = QListWidgetItem("")
                item.setData(ENTRY_ROLE, Entry("Nothing found", "Try another word, or fewer letters", "", lambda: None,
                                               available=False))  # fmt: skip
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.results.addItem(item)
            else:
                self.results.hide()
                return
        self.results.setCurrentRow(0)
        self._place()

    def _place(self) -> None:
        width = max(self.width() + 140, 470)
        right = self._window.mapToGlobal(QPoint(self._window.width() - 8, 0)).x()  # it stays within the window
        top_left = self.mapToGlobal(QPoint(0, self.height() + 2))
        rows = min(self.results.count(), 9)
        height = rows * self.results.sizeHintForRow(0) + 2 * self.results.frameWidth() + 6
        self.results.setGeometry(min(top_left.x(), right - width), top_left.y(), width, height)
        self.results.show()
        self.results.raise_()

    # -- choosing
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.results.isVisible():
            step = 1 if key == Qt.Key.Key_Down else -1
            row = max(0, min(self.results.count() - 1, self.results.currentRow() + step))
            self.results.setCurrentRow(row)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.results.currentItem() if self.results.isVisible() else None
            if item is not None:
                self._activate_item(item)
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            self.results.hide()
            self._window.setFocus()
            event.accept()
            return
        super().keyPressEvent(event)

    def _activate_item(self, item: QListWidgetItem) -> None:
        entry: Entry | None = item.data(ENTRY_ROLE)
        if entry is None or not entry.kind:
            return
        self.results.hide()
        self.clear()
        self._window.setFocus()  # out of the box first: the setting found may take the focus
        entry.activate()
        QApplication.processEvents()
