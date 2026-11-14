"""Panels that can be resized by dragging and folded away: the splitters of the main window."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSplitter, QSplitterHandle

from easyfoam.gui.style import ACCENT

KEEP = 120  # pixels the other side keeps at least when a folded side opens again


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
            painter.fillRect(self.rect(), QColor("#e3ecf9"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT if hovered else "#9aa5b1"))
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
