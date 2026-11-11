"""Small reusable input widgets."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget


class FloatEdit(QLineEdit):
    """A line edit for one number; accepts ``1e-5`` style input, rejects garbage."""

    changed = Signal(float)

    def __init__(self, value: float = 0.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = float(value)
        self.setMinimumWidth(60)
        self._show()
        self.editingFinished.connect(self._commit)

    def _show(self) -> None:
        self.setText(f"{self._value:g}")

    def _commit(self) -> None:
        try:
            new = float(self.text().replace(",", "."))
        except ValueError:
            self._show()
            return
        if new != self._value:
            self._value = new
            self._show()
            self.changed.emit(new)
        else:
            self._show()

    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        """Set programmatically (does not emit ``changed``)."""
        self._value = float(value)
        self._show()


class VectorEdit(QWidget):
    """Three numbers in a row (x, y, z)."""

    changed = Signal()

    def __init__(self, value: Sequence[float] = (0, 0, 0), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edits: list[FloatEdit] = []
        for axis, component in zip("xyz", value):
            label = QLabel(axis)
            label.setStyleSheet("color: gray;")
            edit = FloatEdit(component)
            edit.changed.connect(lambda _v: self.changed.emit())
            layout.addWidget(label)
            layout.addWidget(edit, 1)
            self.edits.append(edit)

    def value(self) -> list[float]:
        return [e.value() for e in self.edits]

    def set_value(self, value: Sequence[float]) -> None:
        for edit, component in zip(self.edits, value):
            edit.set_value(component)
