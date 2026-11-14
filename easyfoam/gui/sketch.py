"""A pad to draw the outline of a shape with the mouse.

Click to add a corner, drag a corner to move it, right-click it to remove it,
click on a side to add a corner there. The outline is extruded across the
plane it is drawn in, which turns the cross-section of a weir, a spillway or a
duct into a solid.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
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

from easyfoam import drawn
from easyfoam.gui import style
from easyfoam.gui.icons import icon
from easyfoam.gui.style import set_primary
from easyfoam.gui.widgets import FloatEdit

#: plane -> names of the two directions drawn in
AXES = {"xz": ("x", "z"), "xy": ("x", "y"), "yz": ("y", "z")}
GRAB = 10  # how close, in pixels, a click must be to a corner to take hold of it
PRESETS = {"rectangle": "Rectangle", "triangle": "Triangle", "trapezoid": "Trapezoid (weir)", "ogee": "Rounded crest (spillway)"}


def nice_step(rough: float) -> float:
    """The next 1-2-5 number at or above a rough step."""
    if rough <= 0:
        return 1.0
    power = 10.0 ** math.floor(math.log10(rough))
    for factor in (1.0, 2.0, 5.0, 10.0):
        if factor * power >= rough * 0.999:
            return factor * power
    return 10.0 * power


def preset(name: str, reference: Sequence[float]) -> list[list[float]]:
    """A ready-made outline standing on the lower edge of the reference rectangle."""
    u0, v0, u1, v1 = reference
    mid, height = (u0 + u1) / 2, 0.35 * (v1 - v0)
    half = 0.5 * height
    below = v0 - 0.2 * (v1 - v0)  # through the bed, so that the mesh is cut cleanly
    top = v0 + height
    if name == "rectangle":
        return [[mid - half, below], [mid + half, below], [mid + half, top], [mid - half, top]]
    if name == "triangle":
        return [[mid - 2 * half, below], [mid + 2 * half, below], [mid, top]]
    if name == "ogee":
        points = [[mid - half, below], [mid - half, top - 0.3 * half]]
        points += [[mid - half + 0.3 * half * (1 - math.cos(a)), top - 0.3 * half * (1 - math.sin(a))]
                   for a in (math.pi / 6, math.pi / 3, math.pi / 2)]  # fmt: skip
        crest = points[-1][0]
        for step in (1, 2, 3, 4, 5, 6):
            x = step / 6 * 1.6 * half
            points.append([crest + x, top - 0.5 * x**1.85 / (0.6 * half) ** 0.85])
        last_u, last_v = points[-1]
        points.append([last_u + (last_v - below) / 1.25, below])
        return [[round(u, 4), round(v, 4)] for u, v in points]
    return [[mid - 3 * half, below], [mid + 3 * half, below], [mid + half, top], [mid - half, top]]  # trapezoid


class SketchCanvas(QWidget):
    changed = Signal()  # the outline was edited
    hovered = Signal(float, float)  # where the mouse is, in drawing coordinates

    def __init__(
        self,
        points: Sequence[Sequence[float]] = (),
        axes: tuple[str, str] = ("x", "z"),
        reference: Sequence[float] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._points = [[float(u), float(v)] for u, v in points]
        self.axes = axes
        self.reference = tuple(float(c) for c in reference) if reference else None  # the base mesh: u0, v0, u1, v1
        self.grid = 0.0  # corners snap to multiples of this (0 = off)
        self._scale = 100.0  # pixels per metre
        self._centre = (0.0, 0.0)  # drawing coordinates in the middle of the pad
        self._dragging: int | None = None
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.fit()

    # -- the outline
    def points(self) -> list[list[float]]:
        return [list(p) for p in self._points]

    def set_points(self, points: Sequence[Sequence[float]]) -> None:
        self._points = [[float(u), float(v)] for u, v in points]
        self._dragging = None
        self.update()
        self.changed.emit()

    def problem(self) -> str | None:
        return drawn.outline_problem(self._points)

    def snap(self, u: float, v: float) -> tuple[float, float]:
        if self.grid > 0:
            return round(u / self.grid) * self.grid, round(v / self.grid) * self.grid
        return u, v

    def add_point(self, u: float, v: float, index: int | None = None) -> int:
        index = len(self._points) if index is None else index
        self._points.insert(index, [u, v])
        self.update()
        self.changed.emit()
        return index

    def move_point(self, index: int, u: float, v: float) -> None:
        if self._points[index] != [u, v]:
            self._points[index] = [u, v]
            self.update()
            self.changed.emit()

    def remove_point(self, index: int) -> None:
        del self._points[index]
        self.update()
        self.changed.emit()

    # -- the view
    def to_screen(self, u: float, v: float) -> QPointF:
        return QPointF(
            self.width() / 2 + (u - self._centre[0]) * self._scale,
            self.height() / 2 - (v - self._centre[1]) * self._scale,
        )

    def to_model(self, position) -> tuple[float, float]:
        return (
            self._centre[0] + (position.x() - self.width() / 2) / self._scale,
            self._centre[1] - (position.y() - self.height() / 2) / self._scale,
        )

    def fit(self) -> None:
        """Show the outline with room to work around it, or the whole base mesh while there is no outline."""
        corners = [tuple(p) for p in self._points]
        if len(corners) < 2:
            corners += [self.reference[:2], self.reference[2:]] if self.reference else [(0.0, 0.0), (1.0, 1.0)]
        us, vs = [c[0] for c in corners], [c[1] for c in corners]
        width, height = (max(us) - min(us)) or 1.0, (max(vs) - min(vs)) or 1.0
        self._centre = ((min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2)
        room = 0.8 if len(self._points) < 2 else 0.45  # an outline gets space around it for new corners
        self._scale = room * min(max(self.width(), 50) / width, max(self.height(), 50) / height)
        self.update()

    def grid_step(self) -> float:
        """Spacing of the grid lines, chosen so that they are about 50 pixels apart."""
        return nice_step(50.0 / self._scale)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit()

    # -- the mouse
    def _corner_at(self, position) -> int | None:
        best, nearest = None, float(GRAB)
        for index, (u, v) in enumerate(self._points):
            screen = self.to_screen(u, v)
            distance = math.hypot(screen.x() - position.x(), screen.y() - position.y())
            if distance <= nearest:
                best, nearest = index, distance
        return best

    def _side_at(self, position) -> int | None:
        """Number of the corner after which a click on a side inserts a new one."""
        if len(self._points) < 2:
            return None
        best, nearest = None, 0.7 * GRAB
        count = len(self._points)
        for index in range(count if count > 2 else 1):
            a, b = self.to_screen(*self._points[index]), self.to_screen(*self._points[(index + 1) % count])
            ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
            length2 = (bx - ax) ** 2 + (by - ay) ** 2
            if length2 == 0:
                continue
            t = ((position.x() - ax) * (bx - ax) + (position.y() - ay) * (by - ay)) / length2
            if not 0.05 < t < 0.95:
                continue
            distance = math.hypot(position.x() - (ax + t * (bx - ax)), position.y() - (ay + t * (by - ay)))
            if distance <= nearest:
                best, nearest = index + 1, distance
        return best

    def mousePressEvent(self, event) -> None:
        position = event.position()
        corner = self._corner_at(position)
        if event.button() == Qt.MouseButton.RightButton:
            if corner is not None:
                self.remove_point(corner)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if corner is None:
            u, v = self.snap(*self.to_model(position))
            corner = self.add_point(u, v, self._side_at(position))
        self._dragging = corner

    def mouseMoveEvent(self, event) -> None:
        u, v = self.snap(*self.to_model(event.position()))
        self.hovered.emit(u, v)
        if self._dragging is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move_point(self._dragging, u, v)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = None

    def wheelEvent(self, event) -> None:
        before = self.to_model(event.position())
        self._scale *= 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        after = self.to_model(event.position())
        self._centre = (self._centre[0] + before[0] - after[0], self._centre[1] + before[1] - after[1])
        self.update()

    # -- drawing
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        step = self.grid_step()
        (u_min, v_max), (u_max, v_min) = self.to_model(QPointF(0, 0)), self.to_model(QPointF(self.width(), self.height()))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        for vertical, low, high in ((True, u_min, u_max), (False, v_min, v_max)):
            first_line = math.floor(low / step)
            for line in range(int((high - low) / step) + 2):
                value = (first_line + line) * step
                value = 0.0 if abs(value) < step * 1e-6 else value  # no "-5.6e-17" where zero is meant
                at = self.to_screen(value, 0).x() if vertical else self.to_screen(0, value).y()
                painter.setPen(QPen(QColor("#c9d1da" if abs(value) < step / 2 else "#eef1f4"), 1))
                if vertical:
                    painter.drawLine(QPointF(at, 0), QPointF(at, self.height()))
                else:
                    painter.drawLine(QPointF(0, at), QPointF(self.width(), at))
                painter.setPen(QColor(style.MUTED))
                label = f"{value:.6g}"
                if vertical:
                    painter.drawText(QPointF(at + 3, self.height() - 4), label)
                else:
                    painter.drawText(QPointF(4, at - 3), label)
        painter.setPen(QColor(style.MUTED))
        painter.drawText(QPointF(self.width() - 46, self.height() - 18), f"{self.axes[0]} [m] →")
        painter.drawText(QPointF(4, 14), f"↑ {self.axes[1]} [m]")

        if self.reference:
            u0, v0, u1, v1 = self.reference
            painter.setPen(QPen(QColor("#44505c"), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(self.to_screen(u0, v1), self.to_screen(u1, v0)))
            painter.drawText(self.to_screen(u0, v1) + QPointF(4, -4), "base mesh")

        if self._points:
            sound = self.problem() is None
            colour = QColor(style.ACCENT if sound or len(self._points) < 3 else style.ERROR)
            polygon = QPolygonF([self.to_screen(u, v) for u, v in self._points])
            fill = QColor(colour)
            fill.setAlpha(45)
            painter.setPen(QPen(colour, 2))
            painter.setBrush(QBrush(fill))
            if len(self._points) > 2:
                painter.drawPolygon(polygon)
            else:
                painter.drawPolyline(polygon)
            for index, (u, v) in enumerate(self._points):
                centre = self.to_screen(u, v)
                painter.setPen(QPen(QColor("#ffffff"), 1.5))
                painter.setBrush(colour)
                painter.drawEllipse(centre, 5, 5)
                painter.setPen(QColor("#27313b"))
                painter.drawText(centre + QPointF(8, -6), str(index + 1))
        painter.end()


class SketchDialog(QDialog):
    """Draw or edit the outline of a shape."""

    def __init__(
        self,
        points: Sequence[Sequence[float]],
        plane: str = "xz",
        reference: Sequence[float] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Draw the outline")
        self.resize(980, 600)
        axes = AXES.get(plane, AXES["xz"])
        self.reference = tuple(reference) if reference else (0.0, 0.0, 1.0, 1.0)
        self.canvas = SketchCanvas(points, axes, reference)
        self.canvas.grid = nice_step(min(self.reference[2] - self.reference[0], self.reference[3] - self.reference[1]) / 40.0)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([f"{axes[0]} [m]", f"{axes[1]} [m]"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumWidth(210)
        self.table.setToolTip("The corners of the outline, in order. Type a number to place a corner exactly.")
        self.snap_on = QCheckBox("Snap to")
        self.snap_on.setChecked(True)
        self.snap_step = FloatEdit(self.canvas.grid)
        self.snap_step.setToolTip("Corners land on multiples of this distance, in metres.")
        self.presets = QComboBox()
        self.presets.addItem("Start from…", "")
        for key, label in PRESETS.items():
            self.presets.addItem(label, key)
        fit = QPushButton(icon("maximize"), " Fit view")
        clear = QPushButton(icon("trash-2"), " Clear")
        self.position = QLabel("")
        self.position.setStyleSheet(f"color: {style.MUTED};")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        hint = QLabel(
            "Click to add a corner. Drag a corner to move it, right-click it to remove it. "
            "Click on a side to add a corner there. The wheel zooms."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {style.MUTED};")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Use this outline")
        set_primary(self.ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        snap_row = QHBoxLayout()
        snap_row.addWidget(self.snap_on)
        snap_row.addWidget(self.snap_step, 1)
        snap_row.addWidget(QLabel("m"))
        tools = QHBoxLayout()
        tools.addWidget(fit)
        tools.addWidget(clear)
        side = QVBoxLayout()
        side.addWidget(self.presets)
        side.addWidget(self.table, 1)
        side.addLayout(snap_row)
        side.addLayout(tools)
        left = QVBoxLayout()
        left.addWidget(hint)
        left.addWidget(self.canvas, 1)
        left.addWidget(self.position)
        top = QHBoxLayout()
        top.addLayout(left, 1)
        top.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addLayout(top, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._filling = False
        # Methods, not small functions that hold on to the dialog: those would keep it alive after it
        # is closed, to be torn down only while the program exits.
        self.axes = axes
        self.canvas.changed.connect(self._outline_changed)
        self.canvas.hovered.connect(self._show_position)
        self.table.itemChanged.connect(self._cell_edited)
        self.snap_on.toggled.connect(self._snap_changed)
        self.snap_step.changed.connect(self._snap_changed)
        self.presets.activated.connect(self._preset_chosen)
        fit.clicked.connect(self._fit)
        clear.clicked.connect(self._clear)
        self._outline_changed()

    def values(self) -> list[list[float]]:
        return self.canvas.points()

    def use_preset(self, name: str) -> None:
        if name:
            self.canvas.set_points(preset(name, self.reference))
            self.canvas.fit()
        self.presets.setCurrentIndex(0)

    def _show_position(self, u: float, v: float) -> None:
        self.position.setText(f"{self.axes[0]} = {u:.4g} m    {self.axes[1]} = {v:.4g} m")

    def _preset_chosen(self, _index: int) -> None:
        self.use_preset(self.presets.currentData())

    def _fit(self, _checked: bool = False) -> None:
        self.canvas.fit()

    def _clear(self, _checked: bool = False) -> None:
        self.canvas.set_points([])

    def _snap_changed(self, *_value) -> None:
        self.canvas.grid = self.snap_step.value() if self.snap_on.isChecked() else 0.0

    def _outline_changed(self) -> None:
        points = self.canvas.points()
        self._filling = True
        self.table.setRowCount(len(points))
        for row, point in enumerate(points):
            for column, value in enumerate(point):
                item = self.table.item(row, column)
                if item is None:
                    self.table.setItem(row, column, QTableWidgetItem(f"{value:.6g}"))
                elif item.text() != f"{value:.6g}":
                    item.setText(f"{value:.6g}")
        self._filling = False
        wrong = self.canvas.problem()
        self.ok.setEnabled(wrong is None)
        if wrong is None:
            area = abs(drawn.signed_area(drawn.clean_outline(points)))
            self.status.setText(f"{len(points)} corners, area {area:.4g} m².")
            self.status.setStyleSheet("")
        else:
            self.status.setText(f"Not usable yet: {wrong}.")
            self.status.setStyleSheet(f"color: {style.ERROR};")

    def _cell_edited(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        points = self.canvas.points()
        try:
            points[item.row()][item.column()] = float(item.text().replace(",", "."))
        except ValueError:
            self._outline_changed()  # put the old number back
            return
        self.canvas.set_points(points)
