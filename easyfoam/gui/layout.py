"""Panels that can be resized by dragging and folded away, and sections of forms that fold to their title."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QSplitter,
    QSplitterHandle,
    QStyle,
    QStyleOptionGroupBox,
    QVBoxLayout,
    QWidget,
)

from easyfoam.gui import style
from easyfoam.gui.state import load_sections, save_section

KEEP = 120  # pixels the other side keeps at least when a folded side opens again
ARROW_ROOM = 13  # pixels before a section's title, where its chevron is drawn


class FoldingHandle(QSplitterHandle):
    """The bar between two panels: drag it to resize, double-click it to fold a panel away or bring it back."""

    def __init__(self, orientation: Qt.Orientation, parent: FoldingSplitter) -> None:
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Drag to resize. Double-click to fold the panel away, and again to bring it back.")

    def mouseDoubleClickEvent(self, event) -> None:
        self.splitter().toggle()
        event.accept()

    def event(self, event) -> bool:
        if event.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave):
            self.update()
        return super().event(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse()
        if hovered:
            painter.fillRect(self.rect(), QColor(style.colours()["handle_hover"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.ACCENT if hovered else style.colours()["handle"]))
        centre = QPointF(self.rect().center())
        across = self.orientation() == Qt.Orientation.Horizontal  # the dots run along the handle
        for k in (-2, -1, 0, 1, 2):
            step = 5.0 * k
            point = centre + (QPointF(0, step) if across else QPointF(step, 0))
            painter.drawEllipse(point, 1.3, 1.3)


class FoldingSplitter(QSplitter):
    """A splitter of two panels, one of which can be folded away and brought back to the size it had.

    A folded panel keeps ``folded_size`` pixels: nothing, or enough to show its tab headers.
    """

    folded_changed = Signal(bool)

    def __init__(self, orientation: Qt.Orientation, fold: int, open_size: int,
                 folded_size: int | Callable[[], int] = 0, parent=None) -> None:  # fmt: skip
        super().__init__(orientation, parent)
        self.fold = fold  # which of the two panels folds
        self.open_size = open_size  # the size it gets back when it opens
        self._folded_size = folded_size
        self._folded = False
        self._minimum = None
        self.setChildrenCollapsible(False)
        self.setHandleWidth(8)
        self.splitterMoved.connect(self._moved)

    def createHandle(self) -> QSplitterHandle:
        return FoldingHandle(self.orientation(), self)

    def folded_size(self) -> int:
        return int(self._folded_size()) if callable(self._folded_size) else int(self._folded_size)

    def is_folded(self) -> bool:
        return self._folded

    def toggle(self) -> None:
        self.set_folded(not self._folded)

    def _length(self) -> int:
        """The splitter's own length along its orientation, the space its panels share."""
        total = sum(self.sizes())
        if total > 0:
            return total
        return self.width() if self.orientation() == Qt.Orientation.Horizontal else self.height()

    def _set_minimum(self, widget, length: int | None) -> None:
        if length is None:
            if self._minimum is not None:
                widget.setMinimumSize(self._minimum)
            self._minimum = None
            return
        if self._minimum is None:
            self._minimum = widget.minimumSize()
        if self.orientation() == Qt.Orientation.Horizontal:
            widget.setMinimumWidth(length)
        else:
            widget.setMinimumHeight(length)

    def set_folded(self, folded: bool) -> None:
        """Fold the panel away, or open it again at the size it had."""
        if folded == self._folded or self.count() != 2:
            return
        sizes, total, widget = self.sizes(), self._length(), self.widget(self.fold)
        new = [0, 0]
        if folded:
            if sizes[self.fold] > self.folded_size() + 8:
                self.open_size = sizes[self.fold]
            small = self.folded_size()
            if small == 0:
                self.setCollapsible(self.fold, True)
            else:
                self._set_minimum(widget, small)  # let it shrink to its headers
            new[self.fold], new[1 - self.fold] = small, max(total - small, 0)
        else:
            self._set_minimum(widget, None)
            self.setCollapsible(self.fold, False)
            opened = max(0, min(self.open_size, total - KEEP))
            new[self.fold], new[1 - self.fold] = opened, total - opened
        self._folded = folded
        self.setSizes(new)
        self.folded_changed.emit(folded)

    def _moved(self, _pos: int, _index: int) -> None:
        """A folded panel dragged open again counts as open."""
        if self._folded and self.sizes()[self.fold] > self.folded_size() + 8:
            self._set_minimum(self.widget(self.fold), None)
            self.setCollapsible(self.fold, False)
            self._folded = False
            self.open_size = self.sizes()[self.fold]
            self.folded_changed.emit(False)

    # -- remembered between sessions
    def layout_state(self) -> dict:
        return {"sizes": self.sizes(), "folded": self._folded, "open": self.open_size}

    def restore_layout(self, saved: dict) -> None:
        sizes = saved.get("sizes")
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(s, int) and s >= 0 for s in sizes) \
                and sum(sizes) > 0:  # fmt: skip
            self.setSizes(sizes)
        if isinstance(saved.get("open"), int) and saved["open"] > 0:
            self.open_size = saved["open"]
        if saved.get("folded"):
            self.set_folded(True)


class FoldingGroup(QGroupBox):
    """A section of a form that folds away to its title, and opens again, with a click on the title.

    Its contents go in ``body`` (``setLayout`` puts a layout there). ``key`` names the section in the state file,
    so it stays the way it was left; ``folded`` is how it starts the first time: folded for sections most
    projects do not need. A folded section can say in a few words what it holds (``set_note``).
    """

    folded_changed = Signal(bool)

    def __init__(self, title: str, key: str, folded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._title = title
        self._note = ""
        self.body = QWidget(self)
        self.body.setCursor(Qt.CursorShape.ArrowCursor)  # the pointing hand belongs to the title only
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.body)
        saved = load_sections().get(key)
        self._folded = saved if saved is not None else folded
        self.body.setVisible(not self._folded)
        self.setProperty("folded", self._folded)
        self._styled = False
        self.setMouseTracking(True)
        self._show_title()

    # -- the contents go in the body, which is what folds away
    def setLayout(self, layout) -> None:  # noqa: N802 - Qt's name, called as box.setLayout(form)
        self.body.setLayout(layout)

    def setTitle(self, title: str) -> None:  # noqa: N802
        self._title = title
        self._show_title()

    def plain_title(self) -> str:
        return self._title

    def set_note(self, note: str) -> None:
        """A few words on what the section holds, shown after its title while it is folded."""
        if note != self._note:
            self._note = note
            self._show_title()

    def note(self) -> str:
        return self._note

    def _show_title(self) -> None:
        """The title, after room for the chevron that paintEvent draws; the note is drawn beside it, in grey."""
        room = -(-ARROW_ROOM // max(1, self.fontMetrics().horizontalAdvance(" ")))
        super().setTitle(" " * room + self._title)
        self.update()

    def _label_rect(self) -> QRect:
        option = QStyleOptionGroupBox()
        self.initStyleOption(option)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox, option, QStyle.SubControl.SC_GroupBoxLabel, self
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        label = self._label_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(style.TITLE if self.isEnabled() else style.MUTED)
        pen = QPen(colour, 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        centre = QPointF(label.left() + 4 + ARROW_ROOM / 2 - 1, label.center().y() + 1)
        a = 3.2  # half the chevron's size
        if self._folded:  # pointing right: open me
            points = [centre + QPointF(-a / 2, -a), centre + QPointF(a / 2, 0), centre + QPointF(-a / 2, a)]
        else:  # pointing down: open
            points = [centre + QPointF(-a, -a / 2), centre + QPointF(0, a / 2), centre + QPointF(a, -a / 2)]
        painter.drawPolyline(points)
        if self._folded and self._note:
            painter.setPen(QColor(style.MUTED))
            room = QRect(label.right() + 6, label.top(), max(0, self.width() - label.right() - 12), label.height())
            text = self.fontMetrics().elidedText(self._note, Qt.TextElideMode.ElideRight, room.width())
            painter.drawText(room, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        painter.end()

    # -- folding
    def is_folded(self) -> bool:
        return self._folded

    def set_folded(self, folded: bool, remember: bool = True) -> None:
        if folded == self._folded:
            return
        self._folded = folded
        self.body.setVisible(not folded)
        self.setProperty("folded", folded)
        self._restyle()
        self._show_title()
        if remember:
            save_section(self.key, folded)
        self.folded_changed.emit(folded)

    def toggle(self) -> None:
        self.set_folded(not self._folded)

    def _restyle(self) -> None:
        """Apply the folded or open look, margins included (a group box works those out only on a style change)."""
        self.style().unpolish(self)
        self.style().polish(self)
        QApplication.sendEvent(self, QEvent(QEvent.Type.StyleChange))
        self.updateGeometry()

    def minimumSizeHint(self):  # noqa: N802 - Qt's name
        hint = super().minimumSizeHint()
        if self._folded:  # the title line and no more
            hint.setHeight(min(hint.height(), self.sizeHint().height()))
        return hint

    def showEvent(self, event) -> None:
        if not self._styled:  # the first time: margins of the folded look, which the first polish missed
            self._styled = True
            self._restyle()
        super().showEvent(event)

    def _on_title(self, pos: QPoint) -> bool:
        """Whether a point lies on the title line, which folds and opens the section."""
        label = self._label_rect()
        bottom = max(label.bottom() + 4, self.fontMetrics().height() + 4)
        if not self._folded:
            bottom = min(bottom, self.body.geometry().top())
        return QRect(0, 0, self.width(), bottom).contains(pos)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_title(event.position().toPoint()):
            self.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._on_title(event.position().toPoint()):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)


def folding_groups(widget: QWidget) -> list[FoldingGroup]:
    """The folding sections that hold ``widget``, innermost first."""
    groups, parent = [], widget.parentWidget()
    while parent is not None:
        if isinstance(parent, FoldingGroup) and parent.body.isAncestorOf(widget):
            groups.append(parent)
        parent = parent.parentWidget()
    return groups


def unfold_to(widget: QWidget) -> list[FoldingGroup]:
    """Open every folded section that holds ``widget``; returns the ones it opened."""
    opened = [group for group in folding_groups(widget) if group.is_folded()]
    for group in opened:
        group.set_folded(False)
    return opened


def shown_if_unfolded(widget: QWidget) -> bool:
    """Whether ``widget`` is on screen, or would be once the folded sections that hold it are opened."""
    node = widget
    while node is not None:
        parent = node.parentWidget()
        folded_body = isinstance(parent, FoldingGroup) and node is parent.body
        if node.isHidden() and not folded_body:
            return False
        node = parent
    return True


class PlotWindow(QWidget):
    """A window of their own for the plots and the log, to put them on a second screen; closing it puts them back."""

    closed = Signal()

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner, Qt.WindowType.Window)
        from easyfoam.gui.icons import icon

        self.setWindowTitle("EasyFOAM — plots and log")
        self.setWindowIcon(icon("easyfoam"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.resize(960, 560)

    def hold(self, widget: QWidget) -> None:
        self.layout().addWidget(widget)
        widget.show()

    def bring_to_front(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        self.closed.emit()  # the plots go back to the main window
        super().closeEvent(event)
