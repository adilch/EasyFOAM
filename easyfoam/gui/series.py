"""A dialog to give a boundary value that changes in time: an inflow hydrograph or a tailwater level."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from easyfoam.gui import style
from easyfoam.gui.icons import icon
from easyfoam.gui.style import set_primary

PRESETS = {
    "flood": "Flood hydrograph (rise and fall)",
    "steps": "Steps (hold each value)",
    "ramp": "Slow rise",
}


def preset_series(name: str, base: float, peak: float, duration: float) -> list[list[float]]:
    """A ready-made series between a base and a peak value over ``duration`` seconds."""
    if name == "steps":
        values = [base + (peak - base) * k / 3 for k in range(4)]
        hold = duration / 4
        series = [[0.0, values[0]]]
        for k in range(1, 4):
            series += [[k * hold, values[k - 1]], [k * hold + 0.05 * hold, values[k]]]
        return [[round(t, 6), round(v, 6)] for t, v in series]
    if name == "ramp":
        return [[0.0, base], [duration, peak]]
    # a hydrograph that rises to its peak at a third of the time and falls back more slowly
    return [[0.0, base], [duration / 3, peak], [duration, base]]


def parse_pairs(text: str) -> list[list[float]]:
    """Rows of two numbers from pasted text (tabs, spaces, commas or semicolons between them)."""
    rows = []
    for line in text.splitlines():
        parts = line.replace(";", " ").replace(",", " ").replace("\t", " ").split()
        try:
            if len(parts) >= 2:
                rows.append([float(parts[0]), float(parts[1])])
        except ValueError:
            continue  # a heading
    return rows


def series_problem(series: Sequence[Sequence[float]], positive: bool) -> str | None:
    if len(series) < 2:
        return "give at least two points"
    times = [t for t, _ in series]
    if any(b <= a for a, b in zip(times, times[1:])):
        return "the times must increase from row to row"
    if positive and any(v < 0 for _, v in series):
        return "the values cannot be negative"
    return None


class SeriesDialog(QDialog):
    """Edit a time series as a table, from a preset or pasted from a spreadsheet."""

    def __init__(
        self,
        series: Sequence[Sequence[float]],
        title: str,
        unit: str,
        constant: float,
        positive: bool = True,
        duration: float = 60.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 460)
        self.unit, self.positive, self.constant, self.duration = unit, positive, constant, duration
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["time [s]", f"value [{unit}]"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setToolTip("Linear between the rows; before the first and after the last the value stays the same.")
        self.presets = QComboBox()
        self.presets.addItem("Start from…", "")
        for key, label in PRESETS.items():
            self.presets.addItem(label, key)
        add = QPushButton(icon("plus"), " Add row")
        remove = QPushButton(icon("trash-2"), " Remove row")
        paste = QPushButton(icon("import"), " Paste")
        paste.setToolTip("Paste two columns copied from a spreadsheet: time and value.")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        hint = QLabel(
            "One row per point in time. Copy two columns from a spreadsheet and press Ctrl+V (or Paste) "
            "to fill the table."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {style.MUTED};")
        self.plot = None
        try:
            import pyqtgraph as pg

            self.plot = pg.PlotWidget()
            self.plot.setBackground("w")
            self.plot.showGrid(x=True, y=True, alpha=0.25)
            self.plot.getAxis("left").enableAutoSIPrefix(False)
            self.plot.setLabel("left", unit)
            self.plot.setLabel("bottom", "Time [s]")
            self.curve = self.plot.plot([], [], pen=pg.mkPen("#2563eb", width=2), symbol="o", symbolSize=6)
        except ImportError:  # the dialog works without the preview
            pass

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Use this series")
        set_primary(self.ok)
        self.constant_button = buttons.addButton("Keep it constant", QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.constant_button.clicked.connect(self._make_constant)
        self.cleared = False

        tools = QHBoxLayout()
        for widget in (self.presets, add, remove, paste):
            tools.addWidget(widget)
        left = QVBoxLayout()
        left.addLayout(tools)
        left.addWidget(self.table, 1)
        top = QHBoxLayout()
        top.addLayout(left, 1)
        if self.plot is not None:
            top.addWidget(self.plot, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(top, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._filling = False
        add.clicked.connect(self._add_row)
        remove.clicked.connect(self._remove_row)
        paste.clicked.connect(self.paste)
        self.presets.activated.connect(self._preset_chosen)
        self.table.itemChanged.connect(self._changed)
        self.set_series(series or [[0.0, constant], [duration, constant]])

    # -- the table
    def set_series(self, series: Sequence[Sequence[float]]) -> None:
        self._filling = True
        self.table.setRowCount(len(series))
        for row, (t, v) in enumerate(series):
            self.table.setItem(row, 0, QTableWidgetItem(f"{float(t):g}"))
            self.table.setItem(row, 1, QTableWidgetItem(f"{float(v):g}"))
        self._filling = False
        self._changed()

    def values(self) -> list[list[float]]:
        rows = []
        for row in range(self.table.rowCount()):
            try:
                rows.append([float(self.table.item(row, c).text().replace(",", ".")) for c in (0, 1)])
            except (AttributeError, ValueError):
                continue  # an empty or unfinished row
        return rows

    def problem(self) -> str | None:
        return series_problem(self.values(), self.positive)

    def paste(self, _checked: bool = False) -> None:
        rows = parse_pairs(QGuiApplication.clipboard().text())
        if rows:
            self.set_series(rows)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
            return
        super().keyPressEvent(event)

    def _add_row(self, _checked: bool = False) -> None:
        rows = self.values()
        last = rows[-1] if rows else [0.0, self.constant]
        step = rows[-1][0] - rows[-2][0] if len(rows) > 1 else self.duration / 2
        self.set_series([*rows, [last[0] + step, last[1]]])

    def _remove_row(self, _checked: bool = False) -> None:
        row = self.table.currentRow()
        rows = self.values()
        if 0 <= row < len(rows):
            del rows[row]
            self.set_series(rows)

    def _preset_chosen(self, _index: int) -> None:
        name = self.presets.currentData()
        if name:
            values = [v for _, v in self.values()] or [self.constant]
            base, peak = min(values), max(values)
            if peak <= base:
                peak = base * 3 if base > 0 else 1.0
            self.set_series(preset_series(name, base, peak, self.duration))
        self.presets.setCurrentIndex(0)

    def _make_constant(self, _checked: bool = False) -> None:
        self.cleared = True
        self.accept()

    def _changed(self, *_args) -> None:
        if self._filling:
            return
        rows = self.values()
        if self.plot is not None:
            self.curve.setData([t for t, _ in rows], [v for _, v in rows])
        wrong = self.problem()
        self.ok.setEnabled(wrong is None)
        if wrong:
            self.status.setText(f"Not usable yet: {wrong}.")
            self.status.setStyleSheet(f"color: {style.ERROR};")
        else:
            self.status.setText(f"{len(rows)} points from {rows[0][0]:g} s to {rows[-1][0]:g} s.")
            self.status.setStyleSheet("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft)


def describe(series: Sequence[Sequence[float]], unit: str) -> str:
    """A one-line description of a time series, for the panel."""
    if not series:
        return ""
    values = [v for _, v in series]
    return (
        f"Varies in time: {len(series)} points from {series[0][0]:g} s to {series[-1][0]:g} s, "
        f"{min(values):g} to {max(values):g} {unit}."
    )
