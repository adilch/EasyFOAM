"""Bring in the ground of a river reach from a survey file (XYZ, ESRI ASCII grid, GeoTIFF or LandXML)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from easyfoam import terrain as tr
from easyfoam.gui import style
from easyfoam.gui.icons import icon
from easyfoam.gui.style import set_primary
from easyfoam.gui.widgets import FloatEdit

#: colours of the ground from low to high
RAMP = np.array([[38, 115, 77], [120, 170, 90], [214, 196, 128], [168, 120, 80], [235, 235, 235]], float)


def shaded(z: np.ndarray, spacing: float, water: float | None) -> QImage:
    """A picture of the ground: colour by height, light from the north-west, water below the level in blue."""
    low, high = float(np.nanmin(z)), float(np.nanmax(z))
    z = np.where(np.isfinite(z), z, low)
    t = np.clip((z - low) / max(high - low, 1e-9), 0, 1) * (len(RAMP) - 1)
    k = np.minimum(t.astype(int), len(RAMP) - 2)
    colour = RAMP[k] + (RAMP[k + 1] - RAMP[k]) * (t - k)[..., None]
    gy, gx = np.gradient(z, spacing)
    light = np.clip(0.75 + 0.35 * (gx - gy) / np.sqrt(1 + gx * gx + gy * gy), 0.35, 1.15)
    colour *= light[..., None]
    if water is not None:
        wet = z < water
        colour[wet] = colour[wet] * 0.35 + np.array([76, 142, 217]) * 0.65
    rgb = np.ascontiguousarray(np.clip(colour[::-1], 0, 255).astype(np.uint8))  # rows from north to south
    height, width = rgb.shape[:2]
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


class GroundPreview(QWidget):
    """The ground as it will be meshed, with the flow direction."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 300)
        self.picture: QPixmap | None = None
        self.text = "Choose a survey file"

    def set_ground(self, ground: tr.Ground | None, water: float | None, text: str = "") -> None:
        self.picture = QPixmap.fromImage(shaded(ground.z, ground.spacing, water)) if ground is not None else None
        self.text = text
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#fbfcfd"))
        if self.picture is None:
            painter.setPen(QColor(style.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
            return
        area = self.rect().adjusted(14, 30, -14, -14)
        scaled = self.picture.scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)  # fmt: skip
        left = area.left() + (area.width() - scaled.width()) // 2
        top = area.top() + (area.height() - scaled.height()) // 2
        painter.drawPixmap(left, top, scaled)
        painter.setPen(QColor("#27313b"))
        painter.drawText(14, 20, self.text or "Plan view: the river runs from left (inlet) to right (outlet)")
        middle = top + scaled.height() / 2
        painter.setPen(QPen(QColor("#1d4ed8"), 3))
        start, end = QPointF(left + 8, middle), QPointF(left + min(80, scaled.width() / 3), middle)
        painter.drawLine(start, end)
        painter.drawLine(end, end + QPointF(-9, -6))
        painter.drawLine(end, end + QPointF(-9, 6))
        painter.setPen(QColor("white"))
        painter.drawText(QPointF(left + 10, middle - 8), "inlet")
        painter.drawText(QPointF(left + scaled.width() - 44, middle - 8), "outlet")


class TerrainDialog(QDialog):
    """Read a survey, choose the part of it to model and how finely, and where the water stands at the start."""

    def __init__(self, path: Path | str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bring in the ground")
        self.resize(1000, 640)
        self.survey: tr.Survey | None = None

        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("XYZ points, ESRI ASCII grid (.asc), GeoTIFF (.tif) or LandXML (.xml)")
        browse = QPushButton(icon("folder-open"), " Choose…")
        browse.clicked.connect(self._browse)
        self.about = QLabel("")
        self.about.setWordWrap(True)
        self.about.setStyleSheet(f"color: {style.MUTED};")

        self.origin_x, self.origin_y = FloatEdit(0.0, digits=12), FloatEdit(0.0, digits=12)
        self.angle = FloatEdit(0.0)
        self.x_from, self.x_to, self.y_from, self.y_to = (FloatEdit(0.0) for _ in range(4))
        self.spacing = FloatEdit(1.0)
        self.cell_size = FloatEdit(1.0)
        self.water = FloatEdit(0.0)
        self.top = FloatEdit(0.0)
        self.discharge = FloatEdit(1.0)
        whole = QPushButton(icon("maximize"), " Whole survey")
        whole.clicked.connect(self._whole)
        tips = {
            self.origin_x: "Survey easting that becomes x = 0 (survey coordinates are large: the model uses small ones).",
            self.origin_y: "Survey northing that becomes y = 0.",
            self.angle: "Direction the river flows, in degrees anticlockwise from east. The survey is turned so "
                        "that the river runs along x, from the inlet (left) to the outlet (right).",
            self.spacing: "Distance between the points of the ground surface that is meshed. The survey's own "
                          "spacing keeps all detail; a coarser one is quicker to mesh.",
            self.cell_size: "Size of the mesh cells above the ground (snappyHexMesh refines once at the ground).",
            self.water: "Water level at the start: the low ground below it starts filled. The outlet holds it too.",
            self.top: "Top of the model, open to the atmosphere; leave room above the highest water.",
            self.discharge: "Water let in at the inlet, the side facing -x.",
        }  # fmt: skip
        for widget, tip in tips.items():
            widget.setToolTip(tip)

        def pair(a, b, word="to"):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(a, 1)
            layout.addWidget(QLabel(word))
            layout.addWidget(b, 1)
            return row

        form = QFormLayout()
        form.addRow("Local origin, E and N [m]", pair(self.origin_x, self.origin_y, ","))
        form.addRow("River flows towards [°]", self.angle)
        form.addRow("Region, x [m]", pair(self.x_from, self.x_to))
        form.addRow("Region, y [m]", pair(self.y_from, self.y_to))
        form.addRow(whole)
        form.addRow("Ground spacing [m]", self.spacing)
        form.addRow("Mesh cell size [m]", self.cell_size)
        form.addRow("Initial water level [m]", self.water)
        form.addRow("Top of the model [m]", self.top)
        form.addRow("Discharge [m³/s]", self.discharge)
        options = QGroupBox("What to model")
        options.setLayout(form)

        self.preview = GroundPreview()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Use this ground")
        set_primary(self.ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        file_row = QHBoxLayout()
        file_row.addWidget(self.path, 1)
        file_row.addWidget(browse)
        left = QVBoxLayout()
        left.addLayout(file_row)
        left.addWidget(self.about)
        left.addWidget(options)
        left.addStretch(1)
        body = QHBoxLayout()
        body.addLayout(left, 2)
        body.addWidget(self.preview, 3)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        for edit in tips:
            edit.changed.connect(self._update)
        for edit in (self.x_from, self.x_to, self.y_from, self.y_to):
            edit.changed.connect(self._update)
        self.origin_x.changed.connect(self._whole)
        self.origin_y.changed.connect(self._whole)
        self.angle.changed.connect(self._whole)
        self.ok.setEnabled(False)
        if path:
            self.load(Path(path))

    # -- the survey
    def _browse(self, _checked: bool = False) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in tr.FORMATS)
        name, _ = QFileDialog.getOpenFileName(self, "Survey file", "", f"Surveys ({patterns});;All files (*)")
        if name:
            self.load(Path(name))

    def load(self, path: Path) -> None:
        try:
            survey = tr.read_survey(path)
        except (ValueError, OSError) as exc:
            self.survey = None
            self.path.setText(str(path))
            self.about.setText(f"Cannot read it: {exc}")
            self._update()
            return
        self.survey = survey
        self.path.setText(str(path))
        lo, hi = survey.bounds()
        self.about.setText(
            f"{survey.kind}: {len(survey.points):,} points about {survey.spacing():.3g} m apart, "
            f"E {lo[0]:.0f}–{hi[0]:.0f}, N {lo[1]:.0f}–{hi[1]:.0f}, ground {lo[2]:.4g}–{hi[2]:.4g} m."
        )
        origin = tr.default_origin(survey)
        self.origin_x.set_value(origin[0])
        self.origin_y.set_value(origin[1])
        spacing = survey.spacing()
        self.spacing.set_value(float(f"{spacing:.3g}"))
        relief = max(hi[2] - lo[2], 1.0)
        self.cell_size.set_value(float(f"{max(spacing, relief / 20):.2g}"))
        self.water.set_value(float(f"{lo[2] + 0.3 * relief:.4g}"))
        self.top.set_value(float(f"{hi[2] + 0.2 * relief:.4g}"))
        self._whole()

    def _whole(self, *_args) -> None:
        if self.survey is None:
            return
        x0, y0, x1, y1 = tr.local_extent(self.survey, self.origin(), self.angle.value())
        for edit, value in zip((self.x_from, self.y_from, self.x_to, self.y_to), (x0, y0, x1, y1)):
            edit.set_value(float(f"{value:.6g}"))
        self._update()

    def origin(self) -> tuple[float, float]:
        return self.origin_x.value(), self.origin_y.value()

    def region(self) -> tuple[float, float, float, float]:
        return self.x_from.value(), self.y_from.value(), self.x_to.value(), self.y_to.value()

    def ground(self, spacing: float | None = None) -> tr.Ground:
        """The ground as set (at the chosen spacing, or another one for a quick look)."""
        if self.survey is None:
            raise ValueError("choose a survey file first")
        return tr.ground(self.survey, spacing or self.spacing.value(), self.origin(), self.angle.value(),
                         self.region())  # fmt: skip

    def settings(self) -> dict:
        """What use_terrain needs besides the ground."""
        return {"cell_size": self.cell_size.value(), "water_level": self.water.value(), "top": self.top.value(),
                "discharge": self.discharge.value()}  # fmt: skip

    def _update(self, *_args) -> None:
        if self.survey is None:
            self.preview.set_ground(None, None, "Choose a survey file")
            self.ok.setEnabled(False)
            return
        x0, y0, x1, y1 = self.region()
        try:
            look = max(self.spacing.value(), math.hypot(x1 - x0, y1 - y0) / 250)  # a quick, coarse look
            quick = self.ground(look)
            nodes = (round((x1 - x0) / self.spacing.value()) + 1) * (round((y1 - y0) / self.spacing.value()) + 1)
            if nodes > tr.MAX_NODES:
                raise ValueError(f"a {self.spacing.value():g} m ground has {nodes:,} points; use a coarser spacing")
            if self.top.value() <= float(np.nanmax(quick.z)):
                raise ValueError("the top of the model must be above the highest ground in the region")
            if self.cell_size.value() <= 0:
                raise ValueError("the cell size must be above zero")
        except (ValueError, ZeroDivisionError) as exc:
            self.status.setText(f"To use this ground: {exc}.")
            self.status.setStyleSheet("color: #b45309;")
            self.ok.setEnabled(False)
            return
        size = self.cell_size.value()
        cells = (x1 - x0) / size * (y1 - y0) / size * (self.top.value() - float(np.nanmin(quick.z))) / size
        self.preview.set_ground(quick, self.water.value())
        self.status.setText(
            f"{x1 - x0:.4g} m along the river, {y1 - y0:.4g} m across; ground {np.nanmin(quick.z):.4g}–"
            f"{np.nanmax(quick.z):.4g} m. The base mesh has about {cells:,.0f} cells before the ground is cut out."
        )
        self.status.setStyleSheet("")
        self.ok.setEnabled(True)
