"""The channel builder: a cross-section, a bed slope and a centreline of straight pieces and bends."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from easyfoam import channel as chm
from easyfoam.gui import style
from easyfoam.gui.icons import icon
from easyfoam.gui.style import set_primary
from easyfoam.gui.widgets import NOT_NEGATIVE, POSITIVE, FloatEdit
from easyfoam.model import Channel, ChannelSegment

SECTION_LABELS = {
    "rectangular": "Rectangular",
    "trapezoidal": "Trapezoidal",
    "compound": "Compound: a main channel with floodplains",
    "circular": "Circular culvert",
}
WATER = QColor("#4c8ed9")
GROUND = QColor("#8c6d46")
EDGE = QColor("#44505c")


def clip_below(polygon: list[tuple[float, float]], level: float) -> list[tuple[float, float]]:
    """The part of a polygon (n, z) at or below a level (Sutherland-Hodgman against one half-plane)."""
    out: list[tuple[float, float]] = []
    for i, (n1, z1) in enumerate(polygon):
        n0, z0 = polygon[i - 1]
        inside0, inside1 = z0 <= level, z1 <= level
        if inside0 != inside1:
            t = (level - z0) / (z1 - z0)
            out.append((n0 + t * (n1 - n0), level))
        if inside1:
            out.append((n1, z1))
    return out


class ChannelPreview(QWidget):
    """The cross-section with the water in it (left) and the channel seen from above (right)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.channel: Channel | None = None
        self.setMinimumSize(520, 220)

    def set_channel(self, channel: Channel | None) -> None:
        self.channel = channel
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcfd"))
        if self.channel is None:
            painter.setPen(QColor(style.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Nothing to show yet")
            return
        half = self.width() // 2
        try:
            self._section(painter, 0, half)
            self._plan(painter, half, self.width() - half)
        except (ValueError, ZeroDivisionError, IndexError):
            painter.setPen(QColor(style.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Cannot draw this channel yet")
            return
        painter.setPen(QPen(QColor("#d5dbe1"), 1))
        painter.drawLine(half, 8, half, self.height() - 8)

    @staticmethod
    def _fit(points, left: float, width: float, height: float, stretch: float = 1.0):
        """A mapping from model to screen that fits the points; heights may be drawn up to ``stretch`` times taller."""
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
        sx = (width - 40) / max(max(xs) - min(xs), 0.02 * span)
        sy = (height - 64) / max(max(ys) - min(ys), 0.02 * span)
        scale = min(sx, sy)
        rise = min(stretch, sy / scale) if stretch > 1 else 1.0
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

        def screen(x: float, y: float) -> QPointF:
            return QPointF(left + width / 2 + (x - cx) * scale, height / 2 + 10 - (y - cy) * scale * rise)

        screen.rise = rise
        return screen

    def _section(self, painter: QPainter, left: int, width: int) -> None:
        ch = self.channel
        # looking downstream the left bank (positive n) is on the left of the picture
        edges = [(-n, z, name) for n, z, name in chm.outline(ch, 48)]
        outline = [(n, z) for n, z, _name in edges]
        screen = self._fit(outline, left, width, self.height(), stretch=10.0)
        painter.setPen(QColor("#27313b"))
        painter.drawText(left + 10, 18, "Cross-section, looking downstream")
        if screen.rise > 1.05:
            painter.setPen(QColor(style.MUTED))
            painter.drawText(left + 10, 34, f"heights drawn {screen.rise:.2g} times larger")
        if ch.water_depth > 0:
            water = clip_below(outline, ch.water_depth)
            if len(water) >= 3:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(WATER.lighter(130)))
                painter.drawPolygon(QPolygonF([screen(n, z) for n, z in water]))
        for i, (n, z, name) in enumerate(edges):
            n1, z1, _ = edges[(i + 1) % len(edges)]
            colour = EDGE if name in ("banks", "barrel") else GROUND if name in ("bed", "floodplain") else None
            if colour is None:  # the top: open to the air
                painter.setPen(QPen(QColor("#9ecae1"), 1, Qt.PenStyle.DashLine))
            else:
                painter.setPen(QPen(colour, 2.4 if name in ("bed", "floodplain") else 1.8))
            painter.drawLine(screen(n, z), screen(n1, z1))

    def _plan(self, painter: QPainter, left: int, width: int) -> None:
        ch = self.channel
        line = chm.centreline_points(ch)
        sec = chm.section(ch)
        tangent = np.gradient(line, axis=0)
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
        normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
        banks = (line + sec.half_width * normal, line - sec.half_width * normal)
        screen = self._fit([tuple(p) for p in np.vstack(banks)], left, width, self.height())
        painter.setPen(QColor("#27313b"))
        painter.drawText(left + 10, 18, f"Plan: {chm.total_length(ch):.4g} m along the centreline")
        polygon = [screen(*p) for p in banks[0]] + [screen(*p) for p in banks[1][::-1]]
        painter.setPen(QPen(EDGE, 1.4))
        painter.setBrush(QBrush(WATER.lighter(160)))
        painter.drawPolygon(QPolygonF(polygon))
        painter.setPen(QPen(QColor("#2563eb"), 1.4, Qt.PenStyle.DashLine))
        for a, b in zip(line, line[1:]):
            painter.drawLine(screen(*a), screen(*b))
        start, ahead = screen(*line[0]), screen(*(line[0] + tangent[0] * sec.half_width))
        painter.setPen(QPen(QColor("#2563eb"), 2))
        painter.drawLine(start, ahead)
        painter.setPen(QColor("#27313b"))
        painter.drawText(start + QPointF(-12, -8), "in")
        painter.drawText(screen(*line[-1]) + QPointF(6, -6), "out")


class ChannelDialog(QDialog):
    """Set up an open channel: its cross-section, its bed slope and its centreline."""

    def __init__(self, channel: Channel | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build a channel")
        self.resize(1040, 680)
        start = dataclasses.replace(channel) if channel else Channel()
        start.segments = [dataclasses.replace(s) for s in start.segments]

        self.section = QComboBox()
        for key, label in SECTION_LABELS.items():
            self.section.addItem(label, key)
        self.section.setCurrentIndex(max(0, self.section.findData(start.section)))
        self.bottom_width = FloatEdit(start.bottom_width, check=POSITIVE)
        self.depth = FloatEdit(start.depth, check=POSITIVE)
        self.side_slope = FloatEdit(start.side_slope, check=NOT_NEGATIVE)
        self.berm_width = FloatEdit(start.berm_width, check=NOT_NEGATIVE)
        self.berm_depth = FloatEdit(start.berm_depth, check=NOT_NEGATIVE)
        self.berm_slope = FloatEdit(start.berm_slope, check=NOT_NEGATIVE)
        self.diameter = FloatEdit(start.diameter, check=POSITIVE)
        self.slope = FloatEdit(start.slope)
        self.freeboard = FloatEdit(start.freeboard, check=NOT_NEGATIVE)
        self.cell_size = FloatEdit(start.cell_size, check=POSITIVE)
        self.water_depth = FloatEdit(start.water_depth, check=NOT_NEGATIVE)
        tips = {
            self.bottom_width: "Width of the bed of the main channel.",
            self.depth: "Height of the main channel's banks above its bed.",
            self.side_slope: "How far the banks lean out: horizontal metres per metre of height (1.5 is 1V:1.5H).",
            self.berm_width: "Width of each floodplain, from the top of the main channel's bank to the foot of its outer bank.",
            self.berm_depth: "Height of the floodplains' outer banks.",
            self.berm_slope: "How far the outer banks lean out: horizontal metres per metre of height.",
            self.diameter: "Inside diameter of the culvert barrel.",
            self.slope: "Fall of the bed per metre along the channel (0.001 = 1 m per km).",
            self.freeboard: "Air above the banks, up to the top of the model (which is open to the atmosphere).",
            self.cell_size: "Size of the mesh cells. Halving it gives eight times the cells.",
            self.water_depth: "Depth of water above the bed at the start of the run; the outlet holds this level too. 0 = dry.",
        }  # fmt: skip
        for widget, tip in tips.items():
            widget.setToolTip(tip)

        self.form = QFormLayout()
        self.form.addRow("Cross-section", self.section)
        self.form.addRow("Bottom width [m]", self.bottom_width)
        self.form.addRow("Bank height [m]", self.depth)
        self.form.addRow("Bank slope [H per V]", self.side_slope)
        self.form.addRow("Floodplain width [m]", self.berm_width)
        self.form.addRow("Floodplain bank height [m]", self.berm_depth)
        self.form.addRow("Floodplain bank slope [H per V]", self.berm_slope)
        self.form.addRow("Diameter [m]", self.diameter)
        self.form.addRow("Bed slope [m/m]", self.slope)
        self.form.addRow("Freeboard [m]", self.freeboard)
        self.form.addRow("Initial water depth [m]", self.water_depth)
        self.form.addRow("Cell size [m]", self.cell_size)
        section_box = QGroupBox("Cross-section and slope")
        section_box.setLayout(self.form)

        self.pieces = QTableWidget(0, 4)
        self.pieces.setHorizontalHeaderLabels(["Piece", "Length [m]", "Bend radius [m]", "Turns by [°]"])
        self.pieces.verticalHeader().setVisible(False)
        self.pieces.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pieces.setToolTip(
            "The centreline from the inlet, seen from above: straight pieces and bends. A bend turns left for a "
            "positive angle and right for a negative one; its radius is measured to the centreline."
        )
        self.add_straight = QPushButton(icon("move-horizontal"), " Add straight")
        self.add_bend = QPushButton(icon("rotate-3d"), " Add bend")
        self.remove_piece = QPushButton(icon("trash-2"), " Remove")
        piece_buttons = QHBoxLayout()
        for button in (self.add_straight, self.add_bend, self.remove_piece):
            piece_buttons.addWidget(button)
        pieces_box = QGroupBox("Centreline")
        pieces_layout = QVBoxLayout(pieces_box)
        pieces_layout.addWidget(self.pieces)
        pieces_layout.addLayout(piece_buttons)

        self.preview = ChannelPreview()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Build the channel")
        set_primary(self.ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        left = QVBoxLayout()
        left.addWidget(section_box)
        left.addStretch(1)
        top = QHBoxLayout()
        top.addLayout(left, 2)
        right = QVBoxLayout()
        right.addWidget(self.preview, 3)
        right.addWidget(pieces_box, 2)
        hint = QLabel(
            "The channel starts at the origin heading along x; the bed at the outlet is at level 0. The mesh "
            "follows the banks and bends, and the boundaries are named inlet, outlet, bed, banks (floodplain, "
            "barrel) and atmosphere."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {style.MUTED};")
        right.addWidget(hint)
        top.addLayout(right, 3)
        layout = QVBoxLayout(self)
        layout.addLayout(top, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._filling = False
        self._segments = start.segments
        self._fill_pieces()
        for edit in tips:
            edit.changed.connect(self._update)
        self.section.currentIndexChanged.connect(self._update)
        self.pieces.itemChanged.connect(self._piece_edited)
        self.add_straight.clicked.connect(self._add_straight)
        self.add_bend.clicked.connect(self._add_bend)
        self.remove_piece.clicked.connect(self._remove)
        self._update()

    # -- the channel as set
    def channel(self) -> Channel:
        return Channel(
            section=self.section.currentData(), bottom_width=self.bottom_width.value(), depth=self.depth.value(),
            side_slope=self.side_slope.value(), berm_width=self.berm_width.value(),
            berm_depth=self.berm_depth.value(), berm_slope=self.berm_slope.value(), diameter=self.diameter.value(),
            slope=self.slope.value(), segments=[dataclasses.replace(s) for s in self._segments],
            freeboard=self.freeboard.value(), cell_size=self.cell_size.value(), water_depth=self.water_depth.value(),
        )  # fmt: skip

    def _update(self, *_args) -> None:
        kind = self.section.currentData()
        open_channel = kind != "circular"
        for widget in (self.bottom_width, self.depth, self.freeboard):
            self.form.setRowVisible(widget, open_channel)
        self.form.setRowVisible(self.side_slope, kind in ("trapezoidal", "compound"))
        for widget in (self.berm_width, self.berm_depth, self.berm_slope):
            self.form.setRowVisible(widget, kind == "compound")
        self.form.setRowVisible(self.diameter, kind == "circular")
        self.add_bend.setEnabled(open_channel)
        self.add_bend.setToolTip("" if open_channel else "A circular culvert is built straight.")
        ch = self.channel()
        found = chm.problems(ch)
        if found:
            self.status.setText("To build this channel: " + "; ".join(found) + ".")
            self.status.setStyleSheet("color: #b45309;")
            self.preview.set_channel(None if any("unknown" in f or "must be above zero" in f for f in found) else
                                     self._previewable(ch))  # fmt: skip
        else:
            cells = chm.cell_count(ch)
            q = chm.normal_discharge(ch)
            text = (f"{chm.total_length(ch):.4g} m long, about {cells:,} cells. With Manning's n = 0.03 the uniform "
                    f"flow at the initial depth is {q:.3g} m³/s; a new inlet starts with it.")  # fmt: skip
            if cells > 3_000_000:
                text += " That is a large mesh: a bigger cell size would run much faster."
            self.status.setText(text)
            self.status.setStyleSheet("")
            self.preview.set_channel(ch)
        self.ok.setEnabled(not found)

    @staticmethod
    def _previewable(ch: Channel) -> Channel | None:
        try:
            chm.centreline_points(ch)
            chm.outline(ch)
            return ch if ch.segments else None
        except (ValueError, ZeroDivisionError):
            return None

    # -- the centreline table
    def _fill_pieces(self) -> None:
        self._filling = True
        self.pieces.setRowCount(len(self._segments))
        for row, segment in enumerate(self._segments):
            bend = segment.kind == "bend"
            kind = QTableWidgetItem("bend" if bend else "straight")
            kind.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.pieces.setItem(row, 0, kind)
            values = [segment.run() if bend else segment.length, segment.radius if bend else None,
                      segment.angle if bend else None]  # fmt: skip
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem("—" if value is None else f"{value:.4g}")
                editable = value is not None and not (bend and column == 1)
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                item.setFlags(flags | Qt.ItemFlag.ItemIsEditable if editable else flags)
                if not editable:
                    item.setForeground(QColor(style.MUTED))
                self.pieces.setItem(row, column, item)
        self._filling = False

    def _piece_edited(self, item) -> None:
        if self._filling:
            return
        segment = self._segments[item.row()]
        try:
            value = float(item.text().replace(",", ".").replace("°", ""))
        except ValueError:
            self._fill_pieces()
            return
        field = {1: "length", 2: "radius", 3: "angle"}[item.column()]
        setattr(segment, field, value)
        self._fill_pieces()
        self._update()

    def _add_straight(self, _checked: bool = False) -> None:
        self._segments.append(ChannelSegment("straight", length=10.0))
        self._fill_pieces()
        self._update()

    def _add_bend(self, _checked: bool = False) -> None:
        try:
            half = chm.section(self.channel()).half_width
        except (ValueError, ZeroDivisionError):
            half = 2.5
        radius = max(10.0, math.ceil(4 * half))  # gentle: four times the half width
        self._segments.append(ChannelSegment("bend", radius=radius, angle=90.0))
        self._fill_pieces()
        self._update()

    def _remove(self, _checked: bool = False) -> None:
        row = self.pieces.currentRow()
        if 0 <= row < len(self._segments):
            del self._segments[row]
            self._fill_pieces()
            self._update()
