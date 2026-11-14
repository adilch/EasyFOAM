"""Design a hydraulic structure from its design values and see it drawn from the side and from above."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from easyfoam import structures as sm
from easyfoam.gui.icons import icon
from easyfoam.gui.style import MUTED, WARNING, set_primary
from easyfoam.gui.widgets import NOT_NEGATIVE, POSITIVE, FloatEdit
from easyfoam.model import Structure

CONCRETE = QColor("#c3c9d1")
EDGE = QColor("#44505c")
GROUND = QColor("#8c6d46")
WATER = QColor("#2563eb")
WHOLE = ("cycles", "count", "pools")  # design values that are whole numbers


def clip(polygon, axis: int, level: float, keep_above: bool) -> list[tuple[float, float]]:
    """The part of a polygon on one side of the line ``coordinate[axis] = level`` (Sutherland-Hodgman)."""
    out: list[tuple[float, float]] = []

    def inside(p) -> bool:
        return p[axis] >= level if keep_above else p[axis] <= level

    for i, p1 in enumerate(polygon):
        p0 = polygon[i - 1]
        if inside(p0) != inside(p1):
            t = (level - p0[axis]) / (p1[axis] - p0[axis])
            out.append((p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1])))
        if inside(p1):
            out.append((float(p1[0]), float(p1[1])))
    return out


def _fit(points, left: float, top: float, width: float, height: float, stretch: float = 1.0):
    """A mapping from model coordinates to the screen that fits the points into the rectangle.

    It keeps the true scale unless the drawing would fill less than a third of the height; then heights are drawn
    up to ``stretch`` times larger (the factor is kept as ``screen.rise``).
    """
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    sx = (width - 30) / max(max(xs) - min(xs), 0.05 * span)
    sy = (height - 30) / max(max(ys) - min(ys), 0.05 * span)
    scale = min(sx, sy)
    room = sy / scale
    rise = min(stretch, room / 2) if room > 3 else 1.0
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    def screen(x: float, y: float) -> QPointF:
        return QPointF(left + width / 2 + (x - cx) * scale, top + height / 2 - (y - cy) * scale * rise)

    screen.rise = rise
    return screen


class StructurePreview(QWidget):
    """The structure seen from the side (left) and from above (right), standing in its channel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.structure: Structure | None = None
        self.built: sm.Built | None = None
        self.setMinimumSize(560, 250)

    def show_structure(self, structure: Structure | None, built: sm.Built | None) -> None:
        self.structure, self.built = structure, built
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcfd"))
        if self.built is None or self.structure is None:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Cannot draw this structure yet")
            return
        half = self.width() // 2
        self._side(painter, 0, half)
        self._plan(painter, half, self.width() - half)
        painter.setPen(QPen(QColor("#d5dbe1"), 1))
        painter.drawLine(half, 8, half, self.height() - 8)

    def _outline(self, painter: QPainter, screen, outline, opening: bool = False) -> None:
        if len(outline) >= 3:
            painter.setPen(QPen(EDGE, 1.0, Qt.PenStyle.DashLine) if opening else QPen(EDGE, 1.2))
            painter.setBrush(QBrush(QColor("#f4f8fd") if opening else CONCRETE))
            painter.drawPolygon(QPolygonF([screen(*p) for p in outline]))

    def _side(self, painter: QPainter, left: int, width: int) -> None:
        st, built = self.structure, self.built
        above = [clip(o, 1, st.bed, keep_above=True) for o in built.side]
        points = [p for o in above + built.water for p in o]
        x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
        pad = 0.15 * (x1 - x0)
        points += [(x0 - pad, st.bed), (x1 + pad, st.bed)]
        screen = _fit(points, left, 40, width, self.height() - 46, stretch=5.0)
        painter.setPen(QColor("#27313b"))
        painter.drawText(left + 10, 18, "Side view, flow to the right")
        if screen.rise > 1.05:
            painter.setPen(QColor(MUTED))
            painter.drawText(left + 10, 34, f"heights drawn {screen.rise:.2g} times larger")
        bed_left, bed_right = screen(x0 - pad, st.bed), screen(x1 + pad, st.bed)
        painter.setPen(QPen(GROUND, 2.4))
        painter.drawLine(bed_left, bed_right)
        for outline in above:
            self._outline(painter, screen, outline)
        for outline in built.openings:
            self._outline(painter, screen, outline, opening=True)
        painter.setPen(QPen(WATER, 1.6, Qt.PenStyle.DashLine))
        for line in built.water:
            for a, b in zip(line, line[1:]):
                painter.drawLine(screen(*a), screen(*b))

    def _plan(self, painter: QPainter, left: int, width: int) -> None:
        st, built = self.structure, self.built
        walls = (st.y0, st.y0 + st.width)
        inside = [clip(clip(o, 1, walls[0], True), 1, walls[1], False) for o in built.plan]
        points = [p for o in inside for p in o]
        x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
        pad = 0.15 * (x1 - x0) + 0.05 * st.width
        points += [(x0 - pad, walls[0]), (x1 + pad, walls[1])]
        screen = _fit(points, left, 40, width, self.height() - 46, stretch=10.0)
        painter.setPen(QColor("#27313b"))
        painter.drawText(left + 10, 18, f"Plan, {st.width:.3g} m wide")
        if screen.rise > 1.05:
            painter.setPen(QColor(MUTED))
            painter.drawText(left + 10, 34, f"widths drawn {screen.rise:.2g} times larger")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#e3eefb")))
        painter.drawRect(QRectF(screen(x0 - pad, walls[1]), screen(x1 + pad, walls[0])).normalized())
        painter.setPen(QPen(EDGE, 2))
        for y in walls:
            painter.drawLine(screen(x0 - pad, y), screen(x1 + pad, y))
        for outline in inside:
            self._outline(painter, screen, outline)
        for outline in built.openings_plan:
            self._outline(painter, screen, outline, opening=True)


class StructureDialog(QDialog):
    """Choose a structure, give its place in the channel and its design values, and see what they make."""

    def __init__(self, structure: Structure, box=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Design a structure")
        self.resize(1080, 640)
        self._box = box  # the base mesh, (min, max): new kinds start with sizes that suit it
        start = dataclasses.replace(structure, values=dict(structure.values))

        self.kind = QComboBox()
        for key, (title, _purpose) in sm.KINDS.items():
            self.kind.addItem(icon(f"structure-{key}"), title, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(start.kind)))
        self.purpose = QLabel("")
        self.purpose.setWordWrap(True)
        self.purpose.setStyleSheet(f"color: {MUTED};")

        self.station = FloatEdit(start.station)
        self.bed = FloatEdit(start.bed)
        self.y0 = FloatEdit(start.y0)
        self.width = FloatEdit(start.width)
        tips = {
            self.station: "Where the structure begins, along the channel (x).",
            self.bed: "Level of the bed the structure stands on.",
            self.y0: "Position of the channel's first side wall (y); the structure spans the channel from here.",
            self.width: "Width of the channel, which the structure spans from wall to wall.",
        }
        for widget, tip in tips.items():
            widget.setToolTip(tip)
            widget.changed.connect(self._update)
        place = QFormLayout()
        place.addRow("Starts at x [m]", self.station)
        place.addRow("Bed level [m]", self.bed)
        place.addRow("First wall at y [m]", self.y0)
        place.addRow("Channel width [m]", self.width)
        place_box = QGroupBox("Place in the channel")
        place_box.setLayout(place)

        self.values_form = QFormLayout()
        self.values_box = QGroupBox("Design")
        self.values_box.setLayout(self.values_form)
        self.inputs: dict[str, QWidget] = {}

        self.preview = StructurePreview()
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Use this structure")
        set_primary(self.ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        chooser = QFormLayout()
        chooser.addRow("Structure", self.kind)
        chooser.addRow(self.purpose)
        left = QVBoxLayout()
        left.addLayout(chooser)
        left.addWidget(place_box)
        left.addWidget(self.values_box)
        left.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(self.preview, 3)
        right.addWidget(self.info, 1)
        hint = QLabel(
            "The flow runs along +x. The structure reaches a little beyond the side walls and below the bed so "
            "that the mesh is cut cleanly; snappyHexMesh cuts it out of the base mesh like any other shape."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED};")
        right.addWidget(hint)
        top = QHBoxLayout()
        top.addLayout(left, 2)
        top.addLayout(right, 3)
        layout = QVBoxLayout(self)
        layout.addLayout(top, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._fill_values(start.kind, start.values)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._update()

    # -- the structure as set
    def structure(self) -> Structure:
        values = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QComboBox):
                values[key] = float(widget.currentData())
            elif isinstance(widget, QSpinBox):
                values[key] = float(widget.value())
            else:
                values[key] = widget.value()
        return Structure(kind=self.kind.currentData(), station=self.station.value(), bed=self.bed.value(),
                         y0=self.y0.value(), width=self.width.value(), values=values)  # fmt: skip

    def _fill_values(self, kind: str, values: dict[str, float]) -> None:
        while self.values_form.rowCount():
            self.values_form.removeRow(0)
        self.inputs = {}
        for spec in sm.VALUES[kind]:
            current = float(values.get(spec.key, spec.default))
            if spec.choices:
                widget = QComboBox()
                for number, label in spec.choices:
                    widget.addItem(label, number)
                widget.setCurrentIndex(max(0, widget.findData(current)))
                widget.currentIndexChanged.connect(self._update)
            elif spec.key in WHOLE:
                widget = QSpinBox()
                widget.setRange(1, 200)
                widget.setValue(round(current))
                widget.valueChanged.connect(self._update)
            else:
                check = {"invert": None, "toe_radius": NOT_NEGATIVE}.get(spec.key, POSITIVE)
                widget = FloatEdit(current, check=check)
                widget.changed.connect(self._update)
            widget.setToolTip(spec.tip)
            self.values_form.addRow(f"{spec.label} [{spec.unit}]" if spec.unit else spec.label, widget)
            self.inputs[spec.key] = widget
        self.values_box.setTitle(f"Design of the {sm.kind_name(kind)}")

    def _kind_changed(self, _index: int) -> None:
        kind = self.kind.currentData()
        if self._box is not None:
            values = sm.place(kind, *self._box).values
        else:
            values = sm.defaults(kind)
        if kind == "fishway" and self.width.value() > 0:
            values["slot"] = float(f"{self.width.value() / 8:.3g}")
        self._fill_values(kind, values)
        self._update()

    def _update(self, *_args) -> None:
        st = self.structure()
        self.purpose.setText(sm.KINDS[st.kind][1])
        found = sm.problems(st)
        if found:
            self.status.setText("To make this structure: " + "; ".join(found) + ".")
            self.status.setStyleSheet(f"color: {WARNING};")
            self.preview.show_structure(None, None)
            self.info.setText("")
        else:
            built = sm.build(st)
            warnings = sm.fit_warnings(st, *self._box) if self._box is not None else []
            self.status.setText("Check where it stands: " + "; ".join(warnings) + "." if warnings else "")
            self.status.setStyleSheet(f"color: {WARNING};" if warnings else "")
            self.preview.show_structure(st, built)
            self.info.setText("<ul style='margin-left: -20px'>" + "".join(f"<li>{line}</li>" for line in built.info)
                              + "</ul>")  # fmt: skip
        self.ok.setEnabled(not found)
