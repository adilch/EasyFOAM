"""Small reusable input widgets."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QToolTip, QWidget

from easyfoam.units import parse_quantity, unit_in_label

Check = Callable[[float], "str | None"]  # a value -> what is wrong with it, or None


def above(low: float) -> Check:
    return lambda v: None if v > low else f"it must be above {low:g}"


def at_least(low: float) -> Check:
    return lambda v: None if v >= low else f"it cannot be below {low:g}"


def between(low: float, high: float) -> Check:
    return lambda v: None if low <= v <= high else f"it must lie between {low:g} and {high:g}"


POSITIVE = above(0)
NOT_NEGATIVE = at_least(0)
FRACTION = between(0, 1)


class FloatEdit(QLineEdit):
    """A line edit for one number.

    It takes ``1e-5``, a comma for the decimal point, arithmetic ("1.2 + 0.3") and a unit ("50 mm", "2 ft",
    "3 l/s"), which it turns into its own unit: the one given, or the one in brackets in its form label. A value it
    cannot use, or one its check rejects, stays in red with the reason until it is put right (Esc brings back the
    last good value); nothing is changed meanwhile.
    """

    changed = Signal(float)

    def __init__(self, value: float = 0.0, parent: QWidget | None = None, digits: int = 6, unit: str | None = None,
                 check: Check | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._value = float(value)
        self._digits = digits  # significant digits shown: survey coordinates need more than the usual six
        self._unit = unit  # None: read from the form label when first needed
        self._check = check
        self.problem = ""  # why the text in the box cannot be used, if it cannot
        self.setMinimumWidth(60)
        self._show()
        self.editingFinished.connect(self._commit)

    # -- what the field measures and what it accepts
    def unit(self) -> str:
        """The unit of the field: as given, or read from its label each time (labels change, e.g. time and iterations)."""
        return self._unit if self._unit is not None else self._label_unit()

    def _label_unit(self) -> str:
        """The unit in brackets in the label of this field's form row (or of the row it sits in)."""
        widget = self
        for _ in range(3):  # the field itself, or the row of fields it is part of (x, y, z)
            parent = widget.parentWidget()
            if parent is None:
                return ""
            for form in parent.findChildren(QFormLayout):  # forms may sit inside other layouts
                label = form.labelForField(widget)
                if isinstance(label, QLabel):
                    return unit_in_label(label.text())
            widget = parent
        return ""

    def set_check(self, check: Check | None) -> None:
        """What a value must satisfy to be taken, as a function that says what is wrong with it."""
        self._check = check

    # -- showing and taking values
    def _show(self) -> None:
        self.setText(f"{self._value:.{self._digits}g}")

    def _commit(self) -> None:
        text = self.text()
        try:
            new, note = parse_quantity(text, self.unit())
        except ValueError as exc:
            self._fail(str(exc))
            return
        wrong = self._check(new) if self._check else None
        if wrong:
            self._fail(f"{new:g}: {wrong}")
            return
        self._clear()
        if note:
            self._say(note)
        if new != self._value:
            self._value = new
            self._show()
            self.changed.emit(new)
        else:
            self._show()

    def _fail(self, reason: str) -> None:
        self.problem = reason[0].upper() + reason[1:]
        self.setProperty("invalid", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setToolTip(f"{self.problem}. Press Esc to bring back {self._value:g}.")
        self._say(self.toolTip())
        window = self.window()
        if isinstance(window, QMainWindow):  # where it stays readable after the note under the field fades
            window.statusBar().showMessage(self.toolTip(), 10000)

    def _clear(self) -> None:
        if self.problem:
            self.problem = ""
            self.setProperty("invalid", False)
            self.style().unpolish(self)
            self.style().polish(self)
            self.setToolTip("")

    def _say(self, text: str) -> None:
        """Show a short note under the field, where the eye is."""
        if self.isVisible():  # after the commit has settled; dropped if the field is gone by then
            QTimer.singleShot(0, self, lambda: QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), text, self))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.problem:
            self.set_value(self._value)
            event.accept()
            return
        super().keyPressEvent(event)

    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        """Set programmatically (does not emit ``changed``)."""
        self._value = float(value)
        self._clear()
        self._show()


class VectorEdit(QWidget):
    """Three numbers in a row (x, y, z)."""

    changed = Signal()

    def __init__(self, value: Sequence[float] = (0, 0, 0), parent: QWidget | None = None,
                 unit: str | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edits: list[FloatEdit] = []
        for axis, component in zip("xyz", value):
            label = QLabel(axis)
            label.setStyleSheet("color: gray;")
            edit = FloatEdit(component, unit=unit)
            edit.changed.connect(lambda _v: self.changed.emit())
            layout.addWidget(label)
            layout.addWidget(edit, 1)
            self.edits.append(edit)

    def value(self) -> list[float]:
        return [e.value() for e in self.edits]

    def set_value(self, value: Sequence[float]) -> None:
        for edit, component in zip(self.edits, value):
            edit.set_value(component)
