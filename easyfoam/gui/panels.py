"""The six workflow panels. Each one edits the project and emits ``changed``."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from easyfoam import geometry
from easyfoam import structures as sm
from easyfoam.foam.boundaryfile import Patch
from easyfoam.gui.icons import icon
from easyfoam.gui.layout import FoldingGroup
from easyfoam.gui.series import describe as describe_series
from easyfoam.gui.style import set_primary
from easyfoam.gui.widgets import FRACTION, NOT_NEGATIVE, POSITIVE, FloatEdit, VectorEdit, between
from easyfoam.model import (
    CONSTRAINT_TYPES,
    FACES,
    KIND_LABELS,
    KINDS_FOR_TYPE,
    BaseFace,
    Boundary,
    Project,
    Shape,
    Tracer,
    ks_from_manning,
    manning_from_ks,
)
from easyfoam.solvers import (
    MATERIALS,
    POST_FUNCTIONS,
    SOLVERS,
    TURBULENCE,
    VISCOSITY_MODELS,
    WAVE_MODELS,
    solver_spec,
)

NAME_ROLE = Qt.ItemDataRole.UserRole  # == 0x0100

KIND_ICONS = {
    "velocityInlet": "arrow-right-to-line",
    "pressureOutlet": "arrow-right-from-line",
    "slip": "waves",
    "wall": "brick-wall",
    "movingWall": "move-horizontal",
    "flowRateInlet": "droplet",
    "freeOutflow": "log-out",
    "atmosphere": "wind",
    "waterLevelOutlet": "ruler",
    "waveInlet": "activity",
    "waveOutlet": "arrow-right-from-line",
    "constraint": "flip-horizontal",
}
SHAPE_ICONS = {
    "stl": "shapes", "box": "box", "sphere": "circle", "cylinder": "cylinder",
    "cone": "shape-cone", "wedge": "shape-wedge", "profile": "shape-outline",
}  # fmt: skip
#: the shapes that can be drawn: kind -> (name in the menu, what it is for)
DRAWABLE = {
    "box": ("Box", "A block: a pier, a step, a gate, a building."),
    "sphere": ("Sphere", "A ball."),
    "cylinder": ("Cylinder", "A round bar or a pipe, along any direction."),
    "cone": ("Cone", "A cone or, with two radii, a tapering round piece such as a nozzle."),
    "wedge": ("Wedge (ramp)", "A box with a sloping top: a ramp, a chute, a sloping bed."),
    "profile": ("Outline, drawn by hand", "Draw the cross-section of a weir, spillway or duct; it is extruded into a solid."),
}
SHAPE_NAMES = {"stl": "imported surface", "profile": "outline"}
RISE_LABELS ={"+x": "+x (higher at the far x end)", "-x": "−x", "+y": "+y", "-y": "−y"}
PLANE_LABELS = {
    "xz": "the x–z plane (a side view), extruded along y",
    "xy": "the x–y plane (a plan view), extruded along z",
    "yz": "the y–z plane (a cross-section), extruded along x",
}
KIND_HINTS = {
    "velocityInlet": "Fluid enters with this velocity.",
    "pressureOutlet": "Fluid leaves freely at the given pressure (kinematic gauge pressure, p/rho).",
    "slip": "No flow through the surface and no friction along it. Good for far-field sides.",
    "wall": "Solid surface, the fluid sticks to it.",
    "movingWall": "Solid surface that moves with this velocity (e.g. a belt or lid).",
    "flowRateInlet": (
        "Fluid enters at this volume flow rate. In free-surface flow the water enters over the "
        "wetted part of the boundary, whatever the water level is: the usual choice for channels, weirs and spillways."
    ),
    "freeOutflow": "Whatever arrives here leaves undisturbed. Use it downstream of a weir or spillway.",
    "atmosphere": "Open air at ambient pressure: air can move in and out freely. Use it for the top of an open channel.",
    "waterLevelOutlet": (
        "Free-surface flow: water leaves into a tailwater that stands at this height. The pressure is "
        "hydrostatic below the level, so the downstream depth is held instead of draining away."
    ),
    "waveInlet": (
        "Free-surface flow: makes regular waves of this height and period on the still water in front of it. "
        "Fill the domain with water to the still-water level first."
    ),
    "waveOutlet": "Free-surface flow: lets waves leave without reflecting them back.",
    "constraint": "This condition is fixed by the patch type chosen in the mesh.",
}
FACE_TYPES = ("patch", "wall", "symmetry", "empty")
MOTION_LABELS = {
    "none": "Fixed (does not move)",
    "move": "Moves to a new position",
    "oscillate": "Swings back and forth",
    "floating": "Floats (moved by the water)",
}
MOTION_TAGS = {"move": "moves", "oscillate": "swings", "floating": "floats"}
FREEDOM_LABELS = {
    "heave": "Up and down only",
    "plane": "In the x–z plane (slide, rise, pitch)",
    "free": "All six directions",
}


def shape_icon(shape: Shape) -> str:
    """Name of the icon that stands for a shape in the list."""
    if shape.kind == "structure" and shape.structure is not None:
        return f"structure-{shape.structure.kind}"
    return SHAPE_ICONS.get(shape.kind, "shapes")


def shape_kind_name(shape: Shape) -> str:
    if shape.kind == "structure" and shape.structure is not None and shape.structure.kind in sm.KINDS:
        return sm.kind_name(shape.structure.kind)
    return SHAPE_NAMES.get(shape.kind, shape.kind)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: gray;")
    return label


def _spin(low: int, high: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    return spin


class Panel(QWidget):
    """Base class: holds the project and suppresses change signals while loading."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project: Project | None = None
        self._loading = False

    @contextmanager
    def loading(self):
        previous, self._loading = self._loading, True
        try:
            yield
        finally:
            self._loading = previous

    def fit_forms(self) -> None:
        """Let long rows wrap instead of pushing the panel wider than its column."""
        for form in self.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    def apply(self, edit: Callable[[], None]) -> None:
        """Run an edit of the project unless the panel is being filled."""
        if self._loading or self.project is None:
            return
        edit()
        self.changed.emit()
        self.update_notes()

    def update_notes(self) -> None:
        """Say in a few words what each folded section holds (panels with such sections fill this in)."""


# ---------------------------------------------------------------------------


class GeometryPanel(Panel):
    selection_changed = Signal(str)  # name of the selected shape
    channel_requested = Signal()  # build or change an open channel
    terrain_requested = Signal()  # bring in the ground from a survey

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.case_dir: Path | None = None

        self.shape_list = QListWidget()
        self.shape_list.currentRowChanged.connect(self._show_shape)

        self.empty_hint = _hint(
            "No shapes yet. Draw one (a box, a sphere, a cylinder, a cone, a wedge or an outline of your own), "
            "make a hydraulic structure from its design values, or import a file from a CAD program. A case without "
            "shapes is fine too: the flow then fills the base mesh."
        )
        self.import_button = import_button = QPushButton(icon("import"), " Import")
        import_button.clicked.connect(self._import_stl)
        self.draw_button = add_button = QPushButton(icon("draw"), " Draw")
        self.draw_menu = menu = QMenu(add_button)
        menu.setToolTipsVisible(True)
        for kind, (label, purpose) in DRAWABLE.items():
            action = menu.addAction(icon(SHAPE_ICONS[kind]), label, lambda k=kind: self.add_primitive(k))
            action.setData(kind)
            action.setToolTip(purpose)
        add_button.setMenu(menu)
        remove_button = QPushButton(icon("trash-2"), " Remove")
        remove_button.clicked.connect(self.remove_selected)
        rename_button = QPushButton(icon("pencil"), " Rename")
        rename_button.clicked.connect(self._ask_new_name)
        import_button.setToolTip("Bring in geometry from an STL, STEP, IGES or BREP file.")
        add_button.setToolTip("Draw a shape here: a box, sphere, cylinder, cone, wedge, or an outline of your own.")
        rename_button.setToolTip("The shape's name becomes the name of its boundary in the mesh.")
        buttons = QHBoxLayout()
        for b in (import_button, add_button, rename_button, remove_button):
            buttons.addWidget(b)
        self.channel_button = QPushButton(icon("flow-channel"), " Channel…")
        self.channel_button.setToolTip(
            "Build an open channel: a cross-section (rectangular, trapezoidal, compound or a culvert) swept along "
            "straight pieces and bends at a bed slope. Its mesh is fitted to it and replaces the base mesh."
        )
        self.channel_button.clicked.connect(self.channel_requested)
        self.terrain_button = QPushButton(icon("flow-terrain"), " Terrain…")
        self.terrain_button.setToolTip(
            "Bring in the ground of a river reach or a floodplain from a survey: XYZ points, an ESRI ASCII grid, "
            "a GeoTIFF or a LandXML surface. The water flows over it."
        )
        self.terrain_button.clicked.connect(self.terrain_requested)
        self.structure_button = QPushButton(icon("structure-ogee"), " Structure")
        self.structure_button.setToolTip(
            "Make a hydraulic structure from its design values: an ogee crest, a stepped spillway, a labyrinth "
            "weir, a USBR stilling basin, a culvert or a vertical-slot fishway."
        )
        self.structure_menu = QMenu(self.structure_button)
        self.structure_menu.setToolTipsVisible(True)
        for kind, (title, purpose) in sm.KINDS.items():
            action = self.structure_menu.addAction(icon(f"structure-{kind}"), title, lambda k=kind: self.new_structure(k))
            action.setData(kind)
            action.setToolTip(purpose)
        self.structure_button.setMenu(self.structure_menu)
        self.remove_channel_button = QPushButton(icon("trash-2"), " Remove channel")
        self.remove_channel_button.clicked.connect(self.remove_channel)
        self.channel_summary = _hint("")
        channel_row = QHBoxLayout()
        channel_row.addWidget(self.channel_button)
        channel_row.addWidget(self.terrain_button)
        channel_row.addWidget(self.structure_button)
        channel_row.addWidget(self.remove_channel_button)
        channel_row.addStretch(1)

        self.role = QComboBox()
        self.role.addItem("Solid surface (flow goes around it)", "wall")
        self.role.addItem("Refinement region (finer mesh inside)", "refinement")
        self.centre = VectorEdit(unit="m")
        self.radius = FloatEdit(0.5, unit="m", check=POSITIVE)
        self.box_min = VectorEdit(unit="m")
        self.box_max = VectorEdit(unit="m")
        self.point1 = VectorEdit(unit="m")
        self.point2 = VectorEdit(unit="m")
        self.radius2 = FloatEdit(0.25, unit="m", check=NOT_NEGATIVE)
        self.radius2.setToolTip(
            "Radius at the end of the axis. 0 makes a pointed cone; the same as the first radius, a cylinder."
        )
        self.rise = QComboBox()
        for key, label in RISE_LABELS.items():
            self.rise.addItem(label, key)
        self.rise.setToolTip("The direction in which the top of the wedge rises, from nothing to its full height.")
        self.plane = QComboBox()
        for key, label in PLANE_LABELS.items():
            self.plane.addItem(label, key)
        self.plane.setToolTip("The plane the outline is drawn in. The solid is made by pushing it through at right angles.")
        self.extent_from = FloatEdit(0.0, unit="m")
        self.extent_to = FloatEdit(1.0, unit="m")
        self.extent_row = QWidget()
        extent_layout = QHBoxLayout(self.extent_row)
        extent_layout.setContentsMargins(0, 0, 0, 0)
        extent_layout.addWidget(self.extent_from, 1)
        extent_layout.addWidget(QLabel("to"))
        extent_layout.addWidget(self.extent_to, 1)
        self.extent_row.setToolTip(
            "Where the solid starts and ends across the drawing plane. Let it reach beyond the base mesh "
            "on both sides if it should span the whole width."
        )
        self.outline_button = QPushButton(icon("shape-outline"), " Draw the outline…")
        self.outline_button.clicked.connect(self.edit_outline)
        self.outline_summary = _hint("")
        self.design_button = QPushButton(icon("pencil"), " Change the design…")
        self.design_button.setToolTip("Change where the structure stands and its design values, and see it drawn.")
        self.design_button.clicked.connect(self.edit_structure)
        self.design_summary = _hint("")
        self.handles = QCheckBox("Move and resize with the mouse in the 3D view")
        self.handles.setChecked(True)
        self.handles.setToolTip(
            "Shows handles on the selected shape: drag the balls on a box to move its faces, "
            "drag a sphere to move it, drag the ends of an axis."
        )
        self.level_min = _spin(0, 10)
        self.level_max = _spin(0, 10)
        self.layers = _spin(0, 20)
        self.region_level = _spin(0, 10)
        self.near_distance = FloatEdit(0.0, check=NOT_NEGATIVE)
        self.near_level = _spin(0, 10)
        self.regions = QTableWidget(0, 2)
        self.regions.setHorizontalHeaderLabels(["STL region", "Becomes"])
        self.regions.verticalHeader().setVisible(False)
        self.regions.horizontalHeader().setStretchLastSection(True)
        self._region_types: dict[str, QComboBox] = {}
        self.level_min.setToolTip("Coarsest refinement on this surface. Each level halves the base cell size.")
        self.level_max.setToolTip("Finest refinement, used where the surface curves or has sharp edges.")
        self.layers.setToolTip("Thin cells stacked on the surface to resolve the boundary layer. 0 switches them off.")
        self.near_distance.setToolTip("Cells closer to the surface than this distance are refined to the level below.")
        self.region_level.setToolTip("Refinement of all cells inside this region. Each level halves the base cell size.")

        self.motion_kind = QComboBox()
        for key, label in MOTION_LABELS.items():
            self.motion_kind.addItem(label, key)
        self.motion_displacement = VectorEdit((0, 0, 0.1), unit="m")
        self.motion_start = FloatEdit(0.0, check=NOT_NEGATIVE)
        self.motion_duration = FloatEdit(1.0, check=POSITIVE)
        self.motion_amplitude = VectorEdit((0, 0, 0.05), unit="m")
        self.motion_period = FloatEdit(2.0, check=POSITIVE)
        self.motion_density = FloatEdit(500.0, check=POSITIVE)
        self.motion_freedom = QComboBox()
        for key, label in FREEDOM_LABELS.items():
            self.motion_freedom.addItem(label, key)
        self.motion_mass = _hint("")
        self.motion_kind.setToolTip(
            "A gate that opens, a paddle that swings, or a body that floats. The mesh stretches to follow "
            "the shape, so keep the movement well below the gap to the nearest wall: a gate can open "
            "further or close part of the way, but it cannot shut completely."
        )
        self.motion_displacement.setToolTip("Where the shape ends up, measured from where it is drawn.")
        self.motion_start.setToolTip("The shape stays where it is until this time.")
        self.motion_duration.setToolTip("The shape moves at a steady speed for this long and then stays put.")
        self.motion_amplitude.setToolTip("The furthest the shape swings to either side of where it is drawn.")
        self.motion_period.setToolTip("Time for one full swing there and back.")
        self.motion_density.setToolTip(
            "Mass of the body per volume. Below the density of water (about 1000) it floats, above it sinks."
        )
        self.motion_freedom.setToolTip(
            "Which movements the body is free to make. Fewer is quicker and steadier: "
            "'up and down only' suits a first look at how deep a body floats."
        )

        self.form = QFormLayout()
        self.form.addRow("Use as", self.role)
        self.form.addRow("Centre", self.centre)
        self.form.addRow("Radius", self.radius)
        self.form.addRow("Corner (min)", self.box_min)
        self.form.addRow("Corner (max)", self.box_max)
        self.form.addRow("Axis start", self.point1)
        self.form.addRow("Axis end", self.point2)
        self.form.addRow("Radius at the end", self.radius2)
        self.form.addRow("Rises towards", self.rise)
        self.form.addRow("Drawn in", self.plane)
        self.form.addRow("Extruded from", self.extent_row)
        self.form.addRow(self.outline_button)
        self.form.addRow(self.outline_summary)
        self.form.addRow(self.design_summary)
        self.form.addRow(self.design_button)
        self.form.addRow(self.handles)
        self.form.addRow("Surface refinement, min", self.level_min)
        self.form.addRow("Surface refinement, max", self.level_max)
        self.form.addRow("Boundary-layer cells", self.layers)
        self.form.addRow("Refinement inside", self.region_level)
        self.form.addRow("Also refine within [m]", self.near_distance)
        self.form.addRow("… to level", self.near_level)
        self.form.addRow("Motion", self.motion_kind)
        self.form.addRow("Moves by [m]", self.motion_displacement)
        self.form.addRow("Starts at [s]", self.motion_start)
        self.form.addRow("Takes [s]", self.motion_duration)
        self.form.addRow("Swings by [m]", self.motion_amplitude)
        self.form.addRow("Period [s]", self.motion_period)
        self.form.addRow("Density [kg/m³]", self.motion_density)
        self.form.addRow("Free to move", self.motion_freedom)
        self.form.addRow(self.motion_mass)
        self.form.addRow(self.regions)
        self.details = QGroupBox("Selected shape")
        self.details.setLayout(self.form)

        layout = QVBoxLayout(self)
        layout.addLayout(channel_row)
        layout.addWidget(self.channel_summary)
        layout.addWidget(_hint("Surfaces to mesh around, and regions where the mesh should be finer."))
        layout.addWidget(self.empty_hint)
        layout.addWidget(self.shape_list, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.details)
        layout.addWidget(_hint("Each refinement level halves the cell size of the base mesh."))

        self.role.currentIndexChanged.connect(lambda: self._set("role", self.role.currentData(), refresh=True))
        self.centre.changed.connect(lambda: self._set("centre", self.centre.value()))
        self.radius.changed.connect(lambda v: self._set("radius", v))
        self.box_min.changed.connect(lambda: self._set("min", self.box_min.value()))
        self.box_max.changed.connect(lambda: self._set("max", self.box_max.value()))
        self.point1.changed.connect(lambda: self._set("point1", self.point1.value()))
        self.point2.changed.connect(lambda: self._set("point2", self.point2.value()))
        self.radius2.changed.connect(lambda v: self._set("radius2", v))
        self.rise.currentIndexChanged.connect(lambda: self._set("rise", self.rise.currentData()))
        self.plane.currentIndexChanged.connect(lambda: self._set("plane", self.plane.currentData(), refresh=True))
        self.extent_from.changed.connect(lambda _v: self._set_extent())
        self.extent_to.changed.connect(lambda _v: self._set_extent())
        self.handles.toggled.connect(lambda _on: self.changed.emit() if not self._loading else None)
        self.level_min.valueChanged.connect(self._set_level_min)
        self.level_max.valueChanged.connect(self._set_level_max)
        self.layers.valueChanged.connect(lambda v: self._set("layers", v))
        self.region_level.valueChanged.connect(lambda v: self._set("region_level", v))
        self.near_distance.changed.connect(lambda v: self._set("near_distance", v))
        self.near_level.valueChanged.connect(lambda v: self._set("near_level", v))
        self.motion_kind.currentIndexChanged.connect(
            lambda: self._set_motion("kind", self.motion_kind.currentData(), refresh=True)
        )
        self.motion_displacement.changed.connect(
            lambda: self._set_motion("displacement", self.motion_displacement.value())
        )
        self.motion_start.changed.connect(lambda v: self._set_motion("start", v))
        self.motion_duration.changed.connect(lambda v: self._set_motion("duration", v))
        self.motion_amplitude.changed.connect(lambda: self._set_motion("amplitude", self.motion_amplitude.value()))
        self.motion_period.changed.connect(lambda v: self._set_motion("period", v))
        self.motion_density.changed.connect(lambda v: self._set_motion("density", v))
        self.motion_freedom.currentIndexChanged.connect(
            lambda: self._set_motion("freedom", self.motion_freedom.currentData())
        )

    # -- model <-> widgets
    def load(self, project: Project, case_dir: Path | None) -> None:
        self.project, self.case_dir = project, case_dir
        self._refill(select=0)
        self.show_channel()

    def show_channel(self) -> None:
        """Say what channel the project has, if any."""
        from easyfoam import channel as chm

        ch = self.project.channel if self.project else None
        self.remove_channel_button.setVisible(ch is not None)
        self.channel_summary.setVisible(ch is not None)
        if ch is None:
            return
        pieces = len(ch.segments)
        try:
            cells = f", about {chm.cell_count(ch):,} cells"
        except (ValueError, ZeroDivisionError):
            cells = ""
        plural = "s" if pieces != 1 else ""
        self.channel_summary.setText(
            f"A {ch.section} channel, {chm.total_length(ch):.4g} m long in {pieces} piece{plural}, "
            f"bed slope {ch.slope:g}, cells of {ch.cell_size:g} m{cells}. Its mesh replaces the base mesh; shapes "
            "drawn here (piers, weirs) are cut out of it."
        )

    def remove_channel(self, _checked: bool = False) -> None:
        self.apply(lambda: setattr(self.project, "channel", None))
        self.show_channel()
        self.empty_hint.setVisible(not self.project.shapes)

    def _refill(self, select: int) -> None:
        with self.loading():
            self.shape_list.clear()
            for shape in self.project.shapes:
                self.shape_list.addItem(QListWidgetItem(icon(shape_icon(shape)), self._list_text(shape)))
            if self.project.shapes:
                self.shape_list.setCurrentRow(max(0, min(select, len(self.project.shapes) - 1)))
        self.empty_hint.setVisible(not self.project.shapes and self.project.channel is None)
        self._show_shape(self.shape_list.currentRow())

    @staticmethod
    def _list_text(shape: Shape) -> str:
        kind = shape_kind_name(shape)
        tag = MOTION_TAGS.get(shape.motion.kind) if shape.role == "wall" else None
        return f"{shape.name}   ({kind}, {tag})" if tag else f"{shape.name}   ({kind})"

    def selected(self) -> Shape | None:
        row = self.shape_list.currentRow()
        if self.project is None or not 0 <= row < len(self.project.shapes):
            return None
        return self.project.shapes[row]

    def _set_motion(self, attribute: str, value, refresh: bool = False) -> None:
        shape = self.selected()
        if shape is None:
            return
        self.apply(lambda: setattr(shape.motion, attribute, value))
        if self._loading:
            return
        self.shape_list.item(self.shape_list.currentRow()).setText(self._list_text(shape))
        if refresh:
            self._show_shape(self.shape_list.currentRow())
        else:
            self._show_mass(shape)

    def _show_mass(self, shape: Shape) -> None:
        """Tell the user what a floating body weighs, so a wrong density or size is noticed early."""
        if shape.role != "wall" or shape.motion.kind != "floating" or shape.motion.density <= 0:
            self.motion_mass.setText("")
            return
        try:
            mass, _centre, _inertia = geometry.mass_properties(
                shape, self.case_dir or Path("."), shape.motion.density
            )
        except (ValueError, OSError) as exc:
            self.motion_mass.setText(str(exc))
            return
        self.motion_mass.setText(
            f"Mass {mass:.3g} kg (volume {mass / shape.motion.density:.3g} m³). "
            "The body starts at rest where it is drawn."
        )

    def _show_shape(self, _row: int) -> None:
        shape = self.selected()
        if not self._loading:
            self.selection_changed.emit(shape.name if shape else "")
        self.details.setEnabled(shape is not None)
        if shape is None:
            return
        with self.loading():
            self.role.setCurrentIndex(self.role.findData(shape.role))
            self.centre.set_value(shape.centre)
            self.radius.set_value(shape.radius)
            self.box_min.set_value(shape.min)
            self.box_max.set_value(shape.max)
            self.point1.set_value(shape.point1)
            self.point2.set_value(shape.point2)
            self.radius2.set_value(shape.radius2)
            self.rise.setCurrentIndex(max(0, self.rise.findData(shape.rise)))
            self.plane.setCurrentIndex(max(0, self.plane.findData(shape.plane)))
            self.extent_from.set_value(shape.extent[0])
            self.extent_to.set_value(shape.extent[1])
            self.level_min.setValue(shape.level_min)
            self.level_max.setValue(shape.level_max)
            self.layers.setValue(shape.layers)
            self.region_level.setValue(shape.region_level)
            self.near_distance.set_value(shape.near_distance)
            self.near_level.setValue(shape.near_level)
            motion = shape.motion
            self.motion_kind.setCurrentIndex(max(0, self.motion_kind.findData(motion.kind)))
            self.motion_displacement.set_value(motion.displacement)
            self.motion_start.set_value(motion.start)
            self.motion_duration.set_value(motion.duration)
            self.motion_amplitude.set_value(motion.amplitude)
            self.motion_period.set_value(motion.period)
            self.motion_density.set_value(motion.density)
            self.motion_freedom.setCurrentIndex(max(0, self.motion_freedom.findData(motion.freedom)))
            self._fill_regions(shape)
        is_wall = shape.role == "wall"
        moves = shape.motion.kind if is_wall else "none"
        self._show_mass(shape)
        visible = {
            self.motion_kind: is_wall,
            self.motion_displacement: moves == "move",
            self.motion_start: moves == "move",
            self.motion_duration: moves == "move",
            self.motion_amplitude: moves == "oscillate",
            self.motion_period: moves == "oscillate",
            self.motion_density: moves == "floating",
            self.motion_freedom: moves == "floating",
            self.motion_mass: moves == "floating",
            self.role: shape.kind not in ("stl", "structure"),
            self.design_summary: shape.kind == "structure",
            self.design_button: shape.kind == "structure",
            self.centre: shape.kind == "sphere",
            self.radius: shape.kind in ("sphere", "cylinder", "cone"),
            self.box_min: shape.kind in ("box", "wedge"),
            self.box_max: shape.kind in ("box", "wedge"),
            self.point1: shape.kind in ("cylinder", "cone"),
            self.point2: shape.kind in ("cylinder", "cone"),
            self.radius2: shape.kind == "cone",
            self.rise: shape.kind == "wedge",
            self.plane: shape.kind == "profile",
            self.extent_row: shape.kind == "profile",
            self.outline_button: shape.kind == "profile",
            self.outline_summary: shape.kind == "profile",
            self.handles: shape.kind in ("box", "wedge", "sphere", "cylinder", "cone"),
            self.level_min: is_wall,
            self.level_max: is_wall,
            self.layers: is_wall,
            self.region_level: not is_wall,
            self.near_distance: is_wall,
            self.near_level: is_wall,
            self.regions: len(shape.regions) > 1,
        }
        for widget, show in visible.items():
            self.form.setRowVisible(widget, show)
        self._show_outline(shape)
        self._show_design(shape)

    def _set(self, attribute: str, value, refresh: bool = False) -> None:
        shape = self.selected()
        if shape is None:
            return
        self.apply(lambda: setattr(shape, attribute, value))
        if refresh and not self._loading:
            self._show_shape(self.shape_list.currentRow())

    # -- drawn shapes
    def _set_extent(self) -> None:
        self._set("extent", [self.extent_from.value(), self.extent_to.value()])

    def _show_outline(self, shape: Shape) -> None:
        if shape.kind != "profile":
            return
        wrong = geometry.shape_problem(shape)
        corners = len(shape.points)
        self.outline_summary.setText(
            f"{corners} corners. Not usable yet: {wrong}." if wrong
            else f"{corners} corners, {abs(shape.extent[1] - shape.extent[0]):g} m long."
        )  # fmt: skip

    def set_outline(self, points) -> None:
        """Give the selected outline shape new corners."""
        shape = self.selected()
        if shape is None or shape.kind != "profile":
            return
        self.apply(lambda: setattr(shape, "points", [[float(u), float(v)] for u, v in points]))
        self._show_outline(shape)

    def outline_reference(self, shape: Shape) -> tuple[float, float, float, float]:
        """The base mesh as a rectangle in the plane the outline is drawn in."""
        from easyfoam.drawn import PLANES

        first, second, _along = PLANES.get(shape.plane, PLANES["xz"])
        lo, hi = self.project.mesh.base.min, self.project.mesh.base.max
        return lo[first], lo[second], hi[first], hi[second]

    def edit_outline(self) -> None:
        from easyfoam.gui.sketch import SketchDialog

        shape = self.selected()
        if shape is None or shape.kind != "profile":
            return
        dialog = SketchDialog(shape.points, shape.plane, self.outline_reference(shape), self)
        if dialog.exec() == SketchDialog.DialogCode.Accepted:
            self.set_outline(dialog.values())

    # -- hydraulic structures
    def _show_design(self, shape: Shape) -> None:
        if shape.kind != "structure":
            return
        if shape.structure is None:
            self.design_summary.setText("This structure has no design values.")
            return
        wrong = geometry.shape_problem(shape)
        if wrong:
            self.design_summary.setText(f"Not usable yet: {wrong}.")
            return
        st = shape.structure
        lines = sm.build(st).info
        self.design_summary.setText(
            f"{sm.KINDS[st.kind][0]} starting at x = {st.station:g} m on a bed at {st.bed:g} m, across a channel "
            f"{st.width:g} m wide. " + (lines[0] if lines else "")
        )

    def _box(self):
        base = self.project.mesh.base
        return list(base.min), list(base.max)

    def new_structure(self, kind: str) -> None:
        """Design a new structure of the given kind; it is added when the dialog is accepted."""
        from easyfoam.gui.structure_dialog import StructureDialog

        if self.project is None:
            return
        dialog = StructureDialog(sm.place(kind, *self._box()), self._box(), self)
        if dialog.exec() == StructureDialog.DialogCode.Accepted:
            self.add_structure(dialog.structure())

    def add_structure(self, structure) -> None:
        """Add a structure as a new shape; snappyHexMesh is switched on to cut it out of the mesh."""
        if self.project is None:
            return
        shape = Shape(self._unique_name(structure.kind), kind="structure", structure=structure, level_min=1,
                      level_max=2)  # fmt: skip

        def add():
            self.project.shapes.append(shape)
            self.project.mesh.snappy = True

        self.apply(add)
        self._refill(select=len(self.project.shapes) - 1)

    def edit_structure(self) -> None:
        from easyfoam.gui.structure_dialog import StructureDialog

        shape = self.selected()
        if shape is None or shape.kind != "structure" or shape.structure is None:
            return
        dialog = StructureDialog(shape.structure, self._box(), self)
        if dialog.exec() == StructureDialog.DialogCode.Accepted:
            self.set_structure(dialog.structure())

    def set_structure(self, structure) -> None:
        """Give the selected structure a new place or new design values."""
        shape = self.selected()
        if shape is None or shape.kind != "structure":
            return
        self.apply(lambda: setattr(shape, "structure", structure))
        row = self.shape_list.currentRow()
        self.shape_list.item(row).setIcon(icon(shape_icon(shape)))
        self.shape_list.item(row).setText(self._list_text(shape))
        self._show_design(shape)

    # -- changes made with the mouse in the 3D view
    def _apply_from_view(self, edit) -> None:
        shape = self.selected()
        if shape is None:
            return
        self.apply(lambda: edit(shape))
        self._show_shape(self.shape_list.currentRow())

    def apply_box(self, lo, hi) -> None:
        def edit(shape):
            shape.min, shape.max = [round(float(c), 6) for c in lo], [round(float(c), 6) for c in hi]

        self._apply_from_view(edit)

    def apply_centre(self, centre) -> None:
        self._apply_from_view(lambda shape: setattr(shape, "centre", [round(float(c), 6) for c in centre]))

    def apply_axis(self, start, end) -> None:
        def edit(shape):
            shape.point1, shape.point2 = [round(float(c), 6) for c in start], [round(float(c), 6) for c in end]

        self._apply_from_view(edit)

    def _fill_regions(self, shape: Shape) -> None:
        self._region_types = {}
        self.regions.setRowCount(len(shape.regions))
        for row, (name, kind) in enumerate(shape.regions.items()):
            item = QTableWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.regions.setItem(row, 0, item)
            combo = QComboBox()
            combo.addItem("Wall", "wall")
            combo.addItem("Opening (inlet / outlet)", "patch")
            combo.setCurrentIndex(max(0, combo.findData(kind)))
            combo.currentIndexChanged.connect(
                lambda _i, n=name, c=combo: self._region_edited(n, c.currentData())
            )
            self.regions.setCellWidget(row, 1, combo)
            self._region_types[name] = combo
        if shape.regions:
            self.regions.setFixedHeight(self.regions.rowHeight(0) * len(shape.regions) + 30)

    def set_region_type(self, region: str, kind: str) -> None:
        """Make one region of the selected STL a wall or an opening."""
        combo = self._region_types[region]
        combo.setCurrentIndex(combo.findData(kind))

    def _region_edited(self, region: str, kind: str) -> None:
        shape = self.selected()
        if shape is None or shape.regions.get(region) == kind:
            return

        def edit():
            shape.regions[region] = kind

        self.apply(edit)

    def _set_level_min(self, value: int) -> None:
        self._set("level_min", value)
        if not self._loading and self.level_max.value() < value:
            self.level_max.setValue(value)

    def _set_level_max(self, value: int) -> None:
        self._set("level_max", value)
        if not self._loading and self.level_min.value() > value:
            self.level_min.setValue(value)

    # -- actions
    def rename_selected(self, new_name: str) -> None:
        """Rename the selected shape (and with it the boundary it creates)."""
        shape = self.selected()
        if shape is None or self.project is None:
            return
        row = self.shape_list.currentRow()
        try:
            self.apply(lambda: geometry.rename_shape(self.project, shape.name, new_name))
        except ValueError as exc:
            QMessageBox.information(self, "Rename", str(exc))
            return
        self._refill(select=row)

    def _ask_new_name(self) -> None:
        shape = self.selected()
        if shape is None:
            return
        name, ok = QInputDialog.getText(self, "Rename shape", "New name", text=shape.name)
        if ok and name.strip():
            self.rename_selected(name)

    def _unique_name(self, stem: str) -> str:
        taken = {s.name for s in self.project.shapes}
        n = 1
        while f"{stem}{n}" in taken:
            n += 1
        return f"{stem}{n}"

    def add_primitive(self, kind: str) -> None:
        if self.project is None:
            return
        shape = geometry.new_shape(kind, self._unique_name("outline" if kind == "profile" else kind), self.project)
        self.apply(lambda: self.project.shapes.append(shape))
        self._refill(select=len(self.project.shapes) - 1)

    def remove_selected(self) -> None:
        shape = self.selected()
        if shape is None:
            return
        row = self.shape_list.currentRow()
        self.apply(lambda: self.project.shapes.remove(shape))
        self._refill(select=row)

    def import_file(self, path: Path, unit: str = "m", faces_as_regions: bool = False) -> None:
        """Add a geometry file (STL, STEP, IGES, BREP) drawn in the given length unit."""
        if self.project is None or self.case_dir is None:
            return
        options = {"faces_as_regions": True} if faces_as_regions else {}
        shape = geometry.import_geometry(self.case_dir, Path(path), unit=unit, **options)

        def add():
            self.project.shapes[:] = [s for s in self.project.shapes if s.name != shape.name]
            self.project.shapes.append(shape)

        self.apply(add)
        self._refill(select=len(self.project.shapes) - 1)

    def _import_stl(self) -> None:
        if self.project is None or self.case_dir is None:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import geometry", "",
            "Geometry (*.stl *.step *.stp *.iges *.igs *.brep);;STL surfaces (*.stl);;CAD (*.step *.stp *.iges *.igs *.brep)",
        )  # fmt: skip
        if files:
            self.import_files([Path(f) for f in files])

    def import_files(self, files: list[Path]) -> None:
        """Import geometry files, asking once for the unit they are drawn in (and, for CAD, how to treat faces)."""
        if self.project is None or self.case_dir is None or not files:
            return
        units = {"metres": "m", "millimetres": "mm", "centimetres": "cm", "inches": "in"}
        choice, ok = QInputDialog.getItem(self, "Import geometry", "The file is drawn in", list(units), 0, False)
        if not ok:
            return
        for file in files:
            per_face = False
            if Path(file).suffix.lower() in geometry.CAD_SUFFIXES:
                answer = QMessageBox.question(
                    self, "Import geometry",
                    f"Keep each face of {Path(file).name} as its own boundary?\n\n"
                    "Choose Yes if single faces will be inlets or outlets (internal flow). "
                    "Choose No to treat the whole part as one wall.",
                )  # fmt: skip
                per_face = answer == QMessageBox.StandardButton.Yes
            try:
                self.import_file(Path(file), units[choice], per_face)
            except (ValueError, OSError, RuntimeError) as exc:
                QMessageBox.warning(self, "Import geometry", str(exc))


# ---------------------------------------------------------------------------


class MeshPanel(Panel):
    generate_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.case_dir: Path | None = None

        self.base_min = VectorEdit(unit="m")
        self.base_max = VectorEdit(unit="m")
        self.cells = [_spin(1, 5000) for _ in range(3)]
        cells_row = QHBoxLayout()
        for axis, spin in zip("xyz", self.cells):
            cells_row.addWidget(QLabel(axis))
            cells_row.addWidget(spin, 1)
        self.summary = _hint("")
        fit = QPushButton(icon("wand"), " Size the base mesh automatically")
        fit.setToolTip("A wind tunnel around the shapes for external flow, or a snug box for internal flow.")
        fit.clicked.connect(self._fit)

        base_form = QFormLayout()
        base_form.addRow("Corner (min)", self.base_min)
        base_form.addRow("Corner (max)", self.base_max)
        base_form.addRow("Cells", cells_row)
        base_form.addRow(self.summary)
        base_form.addRow(fit)
        base = FoldingGroup("Base mesh (box of cubes)", "mesh.base")
        base.setLayout(base_form)
        self.base_box = base
        self.channel_note = _hint(
            "The mesh follows the channel built in the Geometry step (its cell size is set there): the base "
            "mesh below is not used. Shapes drawn in the channel are cut out of it with the settings further down."
        )

        self.faces = QTableWidget(len(FACES), 3)
        self.faces.setHorizontalHeaderLabels(["Face", "Boundary name", "Type"])
        self.faces.verticalHeader().setVisible(False)
        self.faces.horizontalHeader().setStretchLastSection(True)
        self._face_names: dict[str, QLineEdit] = {}
        self._face_types: dict[str, QComboBox] = {}
        for row, face in enumerate(FACES):
            item = QTableWidgetItem(face)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.faces.setItem(row, 0, item)
            name = QLineEdit()
            kind = QComboBox()
            kind.addItems(FACE_TYPES)
            self.faces.setCellWidget(row, 1, name)
            self.faces.setCellWidget(row, 2, kind)
            self._face_names[face], self._face_types[face] = name, kind
            name.editingFinished.connect(lambda f=face: self._face_edited(f))
            kind.currentIndexChanged.connect(lambda _i, f=face: self._face_edited(f))
        self.faces.setFixedHeight(self.faces.rowHeight(0) * len(FACES) + 30)

        self.snappy = QCheckBox("Refine and cut around the geometry (snappyHexMesh)")
        self.snap = QCheckBox("Snap cells onto the surfaces")
        self.add_layers = QCheckBox("Add boundary layers where shapes ask for them")
        self.auto_location = QCheckBox("Pick the point inside the fluid automatically")
        self.location = VectorEdit(unit="m")
        self.snappy.setToolTip(
            "Refines the base mesh near the shapes and cuts it to their surfaces. "
            "Switch off to use the plain base mesh."
        )
        self.snap.setToolTip("Moves cell corners onto the surfaces so the mesh follows the true shape, not a staircase.")
        self.add_layers.setToolTip("Adds the boundary-layer cells requested per shape in the Geometry step.")
        self.auto_location.setToolTip(
            "EasyFOAM picks a point in the fluid: a corner for external flow, the inside of the chosen shape for internal flow."
        )
        self.location.setToolTip(
            "Any point that lies in the fluid. The mesh is kept on the side of the surfaces where this point is. "
            "In the 3D view you can drag the red ball."
        )
        self.fluid_region = QComboBox()
        options = QFormLayout()
        options.addRow("The fluid is", self.fluid_region)
        options.addRow(self.snappy)
        options.addRow(self.snap)
        options.addRow(self.add_layers)
        options.addRow(self.auto_location)
        options.addRow("Point inside the fluid", self.location)
        box = FoldingGroup("Around the geometry", "mesh.around")
        box.setLayout(options)

        self.generate = QPushButton(icon("mesh", "#ffffff"), "  Generate mesh")
        set_primary(self.generate)
        self.generate.clicked.connect(self.generate_requested)

        layout = QVBoxLayout(self)
        layout.addWidget(self.channel_note)
        layout.addWidget(base)
        self.faces_label = QLabel("Faces of the base mesh")
        layout.addWidget(self.faces_label)
        layout.addWidget(self.faces)
        layout.addWidget(box)
        layout.addWidget(_hint(
            "For flow inside a part (pipes, ducts) choose that part under “The fluid is”. "
            "To place the point yourself, untick the automatic option and drag the red ball in the 3D view."
        ))
        layout.addStretch(1)
        layout.addWidget(self.generate)

        self.base_min.changed.connect(lambda: self._base("min", self.base_min.value()))
        self.base_max.changed.connect(lambda: self._base("max", self.base_max.value()))
        for i, spin in enumerate(self.cells):
            spin.valueChanged.connect(lambda v, i=i: self._set_cells(i, v))
        self.snappy.toggled.connect(lambda v: self._mesh("snappy", v))
        self.fluid_region.currentIndexChanged.connect(
            lambda: self._mesh("fluid_inside", self.fluid_region.currentData() or "")
        )
        self.snap.toggled.connect(lambda v: self._mesh("snap", v))
        self.add_layers.toggled.connect(lambda v: self._mesh("add_layers", v))
        self.auto_location.toggled.connect(self._set_auto_location)
        self.location.changed.connect(lambda: self._mesh("location_in_mesh", self.location.value()))

    def load(self, project: Project, case_dir: Path | None = None) -> None:
        self.project, self.case_dir = project, case_dir
        mesh = project.mesh
        with self.loading():
            self.base_min.set_value(mesh.base.min)
            self.base_max.set_value(mesh.base.max)
            for spin, n in zip(self.cells, mesh.base.cells):
                spin.setValue(n)
            for face in FACES:
                self._face_names[face].setText(mesh.base.faces[face].name)
                self._face_types[face].setCurrentText(mesh.base.faces[face].type)
            self.fluid_region.clear()
            self.fluid_region.addItem("around the shapes (external flow)", "")
            for shape in project.shapes:
                if shape.role == "wall":
                    self.fluid_region.addItem(f"inside “{shape.name}” (internal flow)", shape.name)
            self.fluid_region.setCurrentIndex(max(0, self.fluid_region.findData(mesh.fluid_inside)))
            self.snappy.setChecked(mesh.snappy)
            self.snap.setChecked(mesh.snap)
            self.add_layers.setChecked(mesh.add_layers)
            auto = mesh.location_in_mesh is None
            self.auto_location.setChecked(auto)
            self.location.setEnabled(not auto)
            if not auto:
                self.location.set_value(mesh.location_in_mesh)
        channel = project.channel is not None
        self.channel_note.setVisible(channel)
        for widget in (self.base_box, self.faces, self.faces_label):
            widget.setEnabled(not channel)
        self._summarise()

    def _summarise(self) -> None:
        base = self.project.mesh.base
        total = base.cells[0] * base.cells[1] * base.cells[2]
        sizes = [(hi - lo) / n for lo, hi, n in zip(base.min, base.max, base.cells)]
        self.summary.setText(
            f"{total:,} base cells, cell size {sizes[0]:.3g} × {sizes[1]:.3g} × {sizes[2]:.3g} m"
        )

    def _base(self, attribute: str, value) -> None:
        self.apply(lambda: setattr(self.project.mesh.base, attribute, value))
        if self.project is not None:
            self._summarise()

    def _set_cells(self, index: int, value: int) -> None:
        def edit():
            self.project.mesh.base.cells[index] = value

        self.apply(edit)
        if self.project is not None:
            self._summarise()

    def _mesh(self, attribute: str, value) -> None:
        self.apply(lambda: setattr(self.project.mesh, attribute, value))

    def _set_auto_location(self, auto: bool) -> None:
        self.location.setEnabled(not auto)
        self._mesh("location_in_mesh", None if auto else self.location.value())

    def set_face(self, face: str, name: str, kind: str) -> None:
        """Rename / retype one face of the base mesh."""
        with self.loading():
            self._face_names[face].setText(name)
            self._face_types[face].setCurrentText(kind)
        self._face_edited(face)

    def _face_edited(self, face: str) -> None:
        name = geometry.safe_name(self._face_names[face].text() or face)
        kind = self._face_types[face].currentText()
        current = self.project.mesh.base.faces[face] if self.project else None
        if current is None or (current.name, current.type) == (name, kind):
            return

        def edit():
            self.project.mesh.base.faces[face] = BaseFace(name, kind)

        self.apply(edit)
        with self.loading():
            self._face_names[face].setText(name)

    def _fit(self) -> None:
        if self.project is None:
            return
        try:
            self.apply(lambda: geometry.fit_base_mesh(self.project, self.case_dir or Path(".")))
        except (ValueError, OSError) as exc:
            QMessageBox.information(self, "Fit base mesh", str(exc))
            return
        self.load(self.project, self.case_dir)


# ---------------------------------------------------------------------------


class PhysicsPanel(Panel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.solver = QComboBox()
        for key, spec in SOLVERS.items():
            self.solver.addItem(spec.label, key)
        self.turbulence = QComboBox()
        for key, (label, _fields) in TURBULENCE.items():
            self.turbulence.addItem(label, key)
        self.material = QComboBox()
        for name in MATERIALS:
            self.material.addItem(name.capitalize(), name)
        self.material.addItem("Custom", "custom")
        self.nu = FloatEdit(check=POSITIVE)
        self.rho = FloatEdit(check=POSITIVE)
        self.velocity = VectorEdit()
        self.intensity = FloatEdit(check=FRACTION)
        self.length = FloatEdit(check=POSITIVE)
        self.nu.setToolTip(
            "How easily the fluid flows: kinematic viscosity = dynamic viscosity / density. "
            "Air is about 1.5e-5 m²/s, water 1e-6 m²/s."
        )
        self.intensity.setToolTip(
            "Strength of the turbulence in the incoming flow as a fraction of its speed. "
            "0.05 (5 %) is a common guess, 0.01 for a quiet wind tunnel."
        )
        self.length.setToolTip("Typical size of the incoming eddies. A common guess is 7 % of the inlet width or body size.")
        self.velocity.setToolTip("Velocity everywhere at the start. Close to the inlet velocity speeds up convergence.")
        self.numerics = QComboBox()
        self.numerics.addItem("Robust (first-order turbulence, forgiving)", "robust")
        self.numerics.addItem("Accurate (second order, needs a good mesh)", "accurate")
        self.potential = QCheckBox("Start from a potential-flow solution")
        self.wall_treatment = QComboBox()
        self.wall_treatment.addItem("Wall functions (coarser mesh near walls)", "wallFunctions")
        self.wall_treatment.addItem("Resolve the boundary layer (fine mesh, y+ about 1)", "lowRe")
        self.wall_treatment.setToolTip(
            "Wall functions model the thin layer next to a wall; resolving it needs very thin cells there (see y+ in Results)."
        )
        self.max_velocity = FloatEdit(check=NOT_NEGATIVE)
        self.max_velocity.setToolTip(
            "Caps the velocity everywhere. A safety net against runaway speeds, e.g. in the air above a water surface. 0 = off."
        )
        self.viscosity_model = QComboBox()
        for key, (label, _defaults) in VISCOSITY_MODELS.items():
            self.viscosity_model.addItem(label, key)
        self.coeff_table = QTableWidget(0, 2)
        self.coeff_table.setHorizontalHeaderLabels(["Coefficient", "Value"])
        self.coeff_table.verticalHeader().setVisible(False)
        self.coeff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.coeff_table.setFixedHeight(150)
        self.coeff_table.itemChanged.connect(self._coefficient_edited)
        self.tracer_table = QTableWidget(0, 4)
        self.tracer_table.setHorizontalHeaderLabels(["Name", "Carries", "Diffusivity [m²/s]", "Decay [1/h]"])
        self.tracer_table.verticalHeader().setVisible(False)
        self.tracer_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tracer_table.setFixedHeight(120)
        self.tracer_table.setToolTip(
            "Quantities carried by the flow. A concentration (dye, chlorine, a pollutant) enters at the inlets "
            "with the value set in Boundaries and can decay at a first-order rate; the age of the water counts "
            "the seconds since it entered (dead zones show up as old water)."
        )
        self.tracer_table.itemChanged.connect(self._tracer_cell_edited)
        self.add_tracer_button = QPushButton(icon("plus"), " Add tracer")
        self.add_age_button = QPushButton(icon("timer"), " Add water age")
        self.remove_tracer_button = QPushButton(icon("trash-2"), " Remove")
        self.add_tracer_button.clicked.connect(lambda: self.add_tracer())
        self.add_age_button.clicked.connect(lambda: self.add_tracer("age", kind="age"))
        self.remove_tracer_button.clicked.connect(self._remove_selected_tracer)
        self.adaptive = _spin(0, 4)
        self.adaptive.setSpecialValueText("off")
        self.adaptive.setToolTip(
            "Refines the mesh by this many levels where the water surface is, while the run goes on. "
            "Needs a fully 3D mesh; each level multiplies the cells there by eight."
        )

        flow = QFormLayout()
        flow.addRow("Flow type", self.solver)
        flow.addRow("Turbulence", self.turbulence)
        flow.addRow("Near walls", self.wall_treatment)
        flow.addRow("Numerics", self.numerics)
        flow.addRow("Limit velocity [m/s], 0 = off", self.max_velocity)
        flow_box = FoldingGroup("Model", "physics.model")
        flow_box.setLayout(flow)

        fluid = QFormLayout()
        fluid.addRow("Fluid", self.material)
        fluid.addRow("Kinematic viscosity [m²/s]", self.nu)
        fluid.addRow("Density [kg/m³]", self.rho)
        fluid.addRow("Behaviour", self.viscosity_model)
        fluid.addRow(self.coeff_table)
        fluid_box = FoldingGroup("Fluid", "physics.fluid")
        fluid_box.setLayout(fluid)

        start = QFormLayout()
        start.addRow("Initial velocity [m/s]", self.velocity)
        start.addRow("Turbulence intensity (0–1)", self.intensity)
        start.addRow("Turbulence length scale [m]", self.length)
        start.addRow(self.potential)
        self.start_box = start_box = FoldingGroup("Starting state and inlet turbulence", "physics.start", folded=True)
        start_box.setLayout(start)

        self.gravity = VectorEdit()
        self.gravity.setToolTip("Gravity vector. On Earth with z pointing up: (0, 0, -9.81).")
        self.air_nu = FloatEdit(check=POSITIVE)
        self.air_rho = FloatEdit(check=POSITIVE)
        self.surface_tension = FloatEdit(check=NOT_NEGATIVE)
        self.surface_tension.setToolTip("Surface tension between water and air: 0.07 N/m at room temperature.")
        self.water_table = QTableWidget(0, 6)
        self.water_table.setHorizontalHeaderLabels(["x min", "y min", "z min", "x max", "y max", "z max"])
        self.water_table.verticalHeader().setVisible(False)
        self.water_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.water_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.water_table.setFixedHeight(112)
        self.water_table.setToolTip("Boxes that are full of water at the start. Everything else starts as air.")
        self.water_table.itemChanged.connect(self._water_edited)
        fill_button = QPushButton(icon("droplet"), " Fill to a level")
        fill_button.setToolTip("Fill the whole base mesh with water up to a height.")
        fill_button.clicked.connect(self._ask_level)
        add_region = QPushButton(icon("plus"), " Add box")
        add_region.clicked.connect(lambda: self.add_water_region())
        remove_region = QPushButton(icon("trash-2"), " Remove")
        remove_region.clicked.connect(self.remove_water_region)
        water_buttons = QHBoxLayout()
        for button in (fill_button, add_region, remove_region):
            water_buttons.addWidget(button)
        water_buttons.addStretch(1)
        water = QFormLayout()
        water.addRow("Gravity [m/s²]", self.gravity)
        water.addRow("Air viscosity [m²/s]", self.air_nu)
        water.addRow("Air density [kg/m³]", self.air_rho)
        water.addRow("Surface tension [N/m]", self.surface_tension)
        water.addRow("Refine at the water surface", self.adaptive)
        water.addRow(_hint("Water at the start, as boxes [m]. The fluid chosen above is the water."))
        water.addRow(self.water_table)
        water.addRow(water_buttons)
        self.water_box = FoldingGroup("Water and air (free surface)", "physics.water")
        self.water_box.setLayout(water)

        tracer_buttons = QHBoxLayout()
        for button in (self.add_tracer_button, self.add_age_button, self.remove_tracer_button):
            tracer_buttons.addWidget(button)
        tracer = QVBoxLayout()
        tracer.addWidget(self.tracer_table)
        tracer.addLayout(tracer_buttons)
        self.tracer_box = tracer_box = FoldingGroup("Tracers", "physics.tracers", folded=True)
        tracer_box.setLayout(tracer)

        layout = QVBoxLayout(self)
        for box in (flow_box, fluid_box, self.water_box, start_box, tracer_box):
            layout.addWidget(box)
        layout.addWidget(_hint(
            "Pressure is the kinematic pressure p/ρ in m²/s². Multiply by the density to get pascals."
        ))
        layout.addStretch(1)

        self.solver.currentIndexChanged.connect(self._solver_chosen)
        self.turbulence.currentIndexChanged.connect(
            lambda: self._set("turbulence", self.turbulence.currentData())
        )
        self.numerics.currentIndexChanged.connect(lambda: self._set("numerics", self.numerics.currentData()))
        self.material.currentIndexChanged.connect(self._material_chosen)
        self.nu.changed.connect(lambda v: self._custom("nu", v))
        self.rho.changed.connect(lambda v: self._custom("rho", v))
        self.velocity.changed.connect(lambda: self._set("initial_velocity", self.velocity.value()))
        self.intensity.changed.connect(lambda v: self._set("turbulence_intensity", v))
        self.length.changed.connect(lambda v: self._set("turbulence_length", v))
        self.potential.toggled.connect(lambda v: self._set("potential_init", v))
        self.gravity.changed.connect(lambda: self._set("gravity", self.gravity.value()))
        self.air_nu.changed.connect(lambda v: self._set("air_nu", v))
        self.air_rho.changed.connect(lambda v: self._set("air_rho", v))
        self.surface_tension.changed.connect(lambda v: self._set("surface_tension", v))
        self.wall_treatment.currentIndexChanged.connect(
            lambda: self._set("wall_treatment", self.wall_treatment.currentData())
        )
        self.max_velocity.changed.connect(lambda v: self._set("max_velocity", v))
        self.viscosity_model.currentIndexChanged.connect(self._viscosity_chosen)
        self.adaptive.valueChanged.connect(lambda v: self._set("adaptive_levels", v))

    def load(self, project: Project) -> None:
        self.project = project
        ph = project.physics
        with self.loading():
            self.solver.setCurrentIndex(max(0, self.solver.findData(ph.solver)))
            self.turbulence.setCurrentIndex(max(0, self.turbulence.findData(ph.turbulence)))
            self.numerics.setCurrentIndex(max(0, self.numerics.findData(ph.numerics)))
            index = self.material.findData(ph.material)
            self.material.setCurrentIndex(index if index >= 0 else self.material.findData("custom"))
            self.nu.set_value(ph.nu)
            self.rho.set_value(ph.rho)
            self.velocity.set_value(ph.initial_velocity)
            self.intensity.set_value(ph.turbulence_intensity)
            self.length.set_value(ph.turbulence_length)
            self.potential.setChecked(ph.potential_init)
            self.gravity.set_value(ph.gravity)
            self.air_nu.set_value(ph.air_nu)
            self.air_rho.set_value(ph.air_rho)
            self.surface_tension.set_value(ph.surface_tension)
            self.wall_treatment.setCurrentIndex(max(0, self.wall_treatment.findData(ph.wall_treatment)))
            self.max_velocity.set_value(ph.max_velocity)
            self.viscosity_model.setCurrentIndex(max(0, self.viscosity_model.findData(ph.viscosity_model)))
            self.adaptive.setValue(ph.adaptive_levels)
        self._fill_coefficients()
        self._fill_tracers()
        multiphase = ph.solver in SOLVERS and SOLVERS[ph.solver].multiphase
        self.water_box.setVisible(multiphase)
        self.potential.setEnabled(not multiphase)
        self._fill_water()
        self.update_notes()

    def update_notes(self) -> None:
        if self.project is None:
            return
        ph = self.project.physics
        moving = any(ph.initial_velocity)
        start = ("U = " + ", ".join(f"{c:g}" for c in ph.initial_velocity) + " m/s") if moving else "at rest"
        self.start_box.set_note(start + (", potential flow first" if ph.potential_init else ""))
        self.tracer_box.set_note(", ".join(t.name for t in self.project.tracers) or "none")

    def _fill_coefficients(self) -> None:
        ph = self.project.physics
        with self.loading():
            self.coeff_table.setRowCount(len(ph.viscosity_coeffs))
            for row, (name, value) in enumerate(ph.viscosity_coeffs.items()):
                label = QTableWidgetItem(name)
                label.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.coeff_table.setItem(row, 0, label)
                self.coeff_table.setItem(row, 1, QTableWidgetItem(f"{value:g}"))
        newtonian = ph.viscosity_model == "Newtonian"
        self.coeff_table.setVisible(not newtonian)
        self.nu.setEnabled(newtonian)

    def _viscosity_chosen(self) -> None:
        name = self.viscosity_model.currentData()

        def edit():
            self.project.physics.viscosity_model = name
            self.project.physics.viscosity_coeffs = dict(VISCOSITY_MODELS[name][1])

        self.apply(edit)
        if self.project is not None and not self._loading:
            self._fill_coefficients()

    def set_coefficient(self, name: str, value: float) -> None:
        """Change one coefficient of the non-Newtonian viscosity model."""
        def edit():
            self.project.physics.viscosity_coeffs[name] = float(value)

        self.apply(edit)
        self._fill_coefficients()

    def _coefficient_edited(self, item) -> None:
        if self._loading or self.project is None or item.column() != 1:
            return
        name = self.coeff_table.item(item.row(), 0).text()
        try:
            self.set_coefficient(name, float(item.text().replace(",", ".")))
        except ValueError:
            self._fill_coefficients()

    # -- tracers
    def _fill_tracers(self) -> None:
        with self.loading():
            tracers = self.project.tracers if self.project else []
            self.tracer_table.setRowCount(len(tracers))
            for row, tracer in enumerate(tracers):
                self.tracer_table.setItem(row, 0, QTableWidgetItem(tracer.name))
                carries = QTableWidgetItem("age of the water" if tracer.kind == "age" else "concentration")
                carries.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.tracer_table.setItem(row, 1, carries)
                self.tracer_table.setItem(row, 2, QTableWidgetItem(f"{tracer.diffusivity:g}"))
                decay = QTableWidgetItem("" if tracer.kind == "age" else f"{tracer.decay * 3600:g}")
                if tracer.kind == "age":
                    decay.setFlags(Qt.ItemFlag.ItemIsEnabled)
                elif tracer.decay > 0:
                    decay.setToolTip(f"Half-life {0.6931 / tracer.decay / 3600:.3g} h")
                self.tracer_table.setItem(row, 3, decay)

    def add_tracer(self, name: str | None = None, kind: str = "concentration", diffusivity: float = 1e-09,
                   decay: float = 0.0) -> None:  # fmt: skip
        """Add a tracer (a concentration) or the age of the water."""
        if self.project is None:
            return
        taken = {t.name for t in self.project.tracers}
        stem = geometry.safe_name(name or "tracer")
        unique, n = stem, 1
        while unique in taken:
            n += 1
            unique = f"{stem}{n}"
        new = Tracer(unique, diffusivity, decay, kind)
        self.apply(lambda: self.project.tracers.append(new))
        self._fill_tracers()

    def set_tracer(self, row: int, name: str | None = None, diffusivity: float | None = None,
                   decay_per_hour: float | None = None) -> None:  # fmt: skip
        tracer = self.project.tracers[row]

        def edit():
            if name is not None and name.strip():
                tracer.name = geometry.safe_name(name)
            if diffusivity is not None:
                tracer.diffusivity = max(0.0, diffusivity)
            if decay_per_hour is not None and tracer.kind != "age":
                tracer.decay = max(0.0, decay_per_hour) / 3600.0

        self.apply(edit)
        self._fill_tracers()

    def remove_tracer(self, row: int) -> None:
        if self.project is not None and 0 <= row < len(self.project.tracers):
            self.apply(lambda: self.project.tracers.pop(row))
            self._fill_tracers()

    def _remove_selected_tracer(self, _checked: bool = False) -> None:
        self.remove_tracer(self.tracer_table.currentRow())

    def _tracer_cell_edited(self, item) -> None:
        if self._loading or self.project is None:
            return
        row, column, text = item.row(), item.column(), item.text().replace(",", ".")
        try:
            if column == 0:
                self.set_tracer(row, name=text)
            elif column == 2:
                self.set_tracer(row, diffusivity=float(text))
            elif column == 3:
                self.set_tracer(row, decay_per_hour=float(text or 0))
        except ValueError:
            self._fill_tracers()

    def _solver_chosen(self) -> None:
        name = self.solver.currentData()

        def edit():
            ph = self.project.physics
            ph.solver = name
            if SOLVERS[name].multiphase and ph.rho < 100:  # the main fluid of a free-surface case is the water
                ph.material = "water"
                ph.nu, ph.rho = MATERIALS["water"]

        self.apply(edit)
        if self.project is not None and not self._loading:
            self.load(self.project)

    def _fill_water(self) -> None:
        with self.loading():
            regions = self.project.physics.water_regions
            self.water_table.setRowCount(len(regions))
            for row, box in enumerate(regions):
                for column, value in enumerate(box[:6]):
                    self.water_table.setItem(row, column, QTableWidgetItem(f"{value:g}"))

    def add_water_region(self, box=None) -> None:
        """Add a box of water (default: the lower half of the base mesh)."""
        if self.project is None:
            return
        if box is None:
            lo, hi = self.project.mesh.base.min, self.project.mesh.base.max
            box = [*lo, hi[0], hi[1], (lo[2] + hi[2]) / 2]
        new = [float(c) for c in box]
        self.apply(lambda: self.project.physics.water_regions.append(new))
        self._fill_water()

    def fill_to_level(self, level: float) -> None:
        """Water everywhere in the base mesh below a height (along z)."""
        lo, hi = self.project.mesh.base.min, self.project.mesh.base.max
        self.add_water_region([lo[0], lo[1], lo[2], hi[0], hi[1], level])

    def _ask_level(self) -> None:
        if self.project is None:
            return
        lo, hi = self.project.mesh.base.min, self.project.mesh.base.max
        level, ok = QInputDialog.getDouble(
            self, "Fill to a level", "Water surface height z [m]", (lo[2] + hi[2]) / 2, lo[2], hi[2], 4
        )
        if ok:
            self.fill_to_level(level)

    def remove_water_region(self) -> None:
        row = self.water_table.currentRow()
        if self.project is None or not 0 <= row < len(self.project.physics.water_regions):
            return
        self.apply(lambda: self.project.physics.water_regions.pop(row))
        self._fill_water()

    def _water_edited(self, item) -> None:
        if self._loading or self.project is None:
            return
        try:
            value = float(item.text().replace(",", "."))
        except ValueError:
            self._fill_water()
            return

        def edit():
            self.project.physics.water_regions[item.row()][item.column()] = value

        self.apply(edit)

    def _set(self, attribute: str, value) -> None:
        self.apply(lambda: setattr(self.project.physics, attribute, value))

    def _material_chosen(self) -> None:
        name = self.material.currentData()

        def edit():
            ph = self.project.physics
            ph.material = name
            if name in MATERIALS:
                ph.nu, ph.rho = MATERIALS[name]

        self.apply(edit)
        if self.project is not None and not self._loading:
            self.nu.set_value(self.project.physics.nu)
            self.rho.set_value(self.project.physics.rho)

    def _custom(self, attribute: str, value: float) -> None:
        def edit():
            setattr(self.project.physics, attribute, value)
            self.project.physics.material = "custom"

        self.apply(edit)
        with self.loading():
            self.material.setCurrentIndex(self.material.findData("custom"))


# ---------------------------------------------------------------------------


class BoundaryPanel(Panel):
    selection_changed = Signal(str)  # name of the selected boundary

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.patches: list[Patch] = []
        self.source = _hint("")
        self.patch_list = QListWidget()
        self.kind = QComboBox()
        self.velocity = VectorEdit()
        self.pressure = FloatEdit()
        self.hint = _hint("")
        self.flow_rate = FloatEdit(check=NOT_NEGATIVE)
        self.flow_rate.setToolTip("Volume flow rate through this boundary in cubic metres per second.")
        self.water_fraction = FloatEdit(1.0, check=FRACTION)
        self.water_fraction.setToolTip("Free-surface flow: 1 if water enters here, 0 if air enters.")
        self.level = FloatEdit()
        self.level.setToolTip("Height of the tailwater surface, measured upwards (against gravity) in the mesh's coordinates.")
        self.wave_height = FloatEdit(0.05, check=POSITIVE)
        self.wave_height.setToolTip("Wave height from trough to crest.")
        self.wave_period = FloatEdit(2.0, check=POSITIVE)
        self.wave_period.setToolTip("Time between two wave crests.")
        self.wave_model = QComboBox()
        for key, label in WAVE_MODELS.items():
            self.wave_model.addItem(label, key)
        self.contact_angle = FloatEdit(90.0, check=between(0, 180))
        self.contact_angle.setToolTip(
            "Angle at which the water surface meets this wall, in degrees. 90 is neutral; "
            "below 90 the water wets the wall, above 90 it is repelled."
        )
        self.tracer_value = FloatEdit(check=NOT_NEGATIVE)
        self.tracer_value.setToolTip(
            "Concentration of the tracers in the water entering here (for example 1, or 2 mg/L of chlorine)."
        )
        self.tracer_inlet = QTableWidget(0, 2)
        self.tracer_inlet.setHorizontalHeaderLabels(["Tracer", "Concentration entering here"])
        self.tracer_inlet.verticalHeader().setVisible(False)
        self.tracer_inlet.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tracer_inlet.setFixedHeight(96)
        self.tracer_inlet.itemChanged.connect(self._tracer_inlet_edited)
        self.flow_series_button = QPushButton(icon("activity"), " Varies in time…")
        self.flow_series_button.setToolTip("Give an inflow hydrograph: the discharge at a list of times.")
        self.flow_series_hint = _hint("")
        self.level_series_button = QPushButton(icon("activity"), " Varies in time…")
        self.level_series_button.setToolTip(
            "Give a tailwater that rises and falls (a tide, a flood): the level at a list of times."
        )
        self.level_series_hint = _hint("")
        self.flow_series_button.clicked.connect(self._edit_flow_series)
        self.level_series_button.clicked.connect(self._edit_level_series)
        self.roughness = QComboBox()
        self.roughness.addItem("Smooth", "smooth")
        self.roughness.addItem("Sand-grain roughness height", "ks")
        self.roughness.addItem("Manning's n", "manning")
        self.roughness.setToolTip(
            "How rough the wall is. Give Manning's n as for a 1D model, or the equivalent sand-grain roughness "
            "height ks. Needs a turbulence model with wall functions."
        )
        self.ks_mm = FloatEdit(0.0, check=NOT_NEGATIVE)
        self.ks_mm.setToolTip(
            "Equivalent sand-grain roughness height in millimetres: about 0.3–3 for concrete, 2–3 times the "
            "d90 of a gravel bed. Keep it below the height of the first cell at the wall."
        )
        self.manning = FloatEdit(0.013, check=POSITIVE)
        self.manning.setToolTip(
            "Manning's n in s/m^(1/3): 0.012–0.015 finished concrete, 0.025–0.035 earth and gravel channels, "
            "0.035–0.05 natural rivers with stones and weeds."
        )
        self.roughness_hint = _hint("")

        self.form = QFormLayout()
        self.form.addRow("Condition", self.kind)
        self.form.addRow("Velocity [m/s]", self.velocity)
        self.form.addRow("Pressure p/ρ [m²/s²]", self.pressure)
        self.form.addRow("Flow rate [m³/s]", self.flow_rate)
        self.form.addRow(self.flow_series_button)
        self.form.addRow(self.flow_series_hint)
        self.form.addRow("Share of water (0–1)", self.water_fraction)
        self.form.addRow("Water level [m]", self.level)
        self.form.addRow(self.level_series_button)
        self.form.addRow(self.level_series_hint)
        self.form.addRow("Wave height [m]", self.wave_height)
        self.form.addRow("Wave period [s]", self.wave_period)
        self.form.addRow("Wave theory", self.wave_model)
        self.form.addRow("Contact angle [°]", self.contact_angle)
        self.form.addRow("Roughness", self.roughness)
        self.form.addRow("Roughness height ks [mm]", self.ks_mm)
        self.form.addRow("Manning's n [s/m^1/3]", self.manning)
        self.form.addRow(self.roughness_hint)
        self.form.addRow("Tracer concentration", self.tracer_value)
        self.form.addRow(self.tracer_inlet)
        self.form.addRow(self.hint)
        self.details = QGroupBox("Selected boundary")
        self.details.setLayout(self.form)

        layout = QVBoxLayout(self)
        layout.addWidget(self.source)
        layout.addWidget(self.patch_list, 1)
        layout.addWidget(self.details)

        self.patch_list.currentRowChanged.connect(self._show_patch)
        self.kind.currentIndexChanged.connect(self._edited)
        self.velocity.changed.connect(self._edited)
        self.pressure.changed.connect(lambda _v: self._edited())
        self.flow_rate.changed.connect(lambda _v: self._edited())
        self.water_fraction.changed.connect(lambda _v: self._edited())
        self.level.changed.connect(lambda _v: self._edited())
        self.wave_height.changed.connect(lambda _v: self._edited())
        self.wave_period.changed.connect(lambda _v: self._edited())
        self.wave_model.currentIndexChanged.connect(lambda _i: self._edited())
        self.contact_angle.changed.connect(lambda _v: self._edited())
        self.tracer_value.changed.connect(lambda _v: self._edited())
        self.roughness.currentIndexChanged.connect(lambda _i: self._edited())
        self.ks_mm.changed.connect(lambda _v: self._edited())
        self.manning.changed.connect(lambda _v: self._edited())

    def load(self, project: Project, patches: Sequence[Patch], from_mesh: bool = False) -> None:
        self.project, self.patches = project, list(patches)
        self.source.setText(
            "Boundaries of the generated mesh." if from_mesh
            else "Expected boundaries (the list is confirmed once the mesh is generated)."
        )
        with self.loading():
            self.patch_list.clear()
            for patch in self.patches:
                item = QListWidgetItem(f"{patch.name}   ({patch.type})")
                item.setData(NAME_ROLE, patch.name)
                item.setIcon(icon(KIND_ICONS[project.boundary_for(patch.name, patch.type).kind]))
                self.patch_list.addItem(item)
            if self.patches:
                self.patch_list.setCurrentRow(0)
        self._show_patch(self.patch_list.currentRow())

    def selected(self) -> Patch | None:
        row = self.patch_list.currentRow()
        return self.patches[row] if 0 <= row < len(self.patches) else None

    def _show_patch(self, _row: int) -> None:
        patch = self.selected()
        if not self._loading:
            self.selection_changed.emit(patch.name if patch else "")
        self.details.setEnabled(patch is not None)
        if patch is None or self.project is None:
            return
        bc = self.project.boundary_for(patch.name, patch.type)
        with self.loading():
            self.kind.clear()
            kinds = KINDS_FOR_TYPE.get(patch.type, ())
            if patch.type in CONSTRAINT_TYPES or not kinds:
                self.kind.addItem(icon(KIND_ICONS["constraint"]), f"Set by the mesh ({patch.type})", "constraint")
                self.kind.setEnabled(False)
            else:
                for kind in kinds:
                    self.kind.addItem(icon(KIND_ICONS[kind]), KIND_LABELS[kind], kind)
                self.kind.setEnabled(True)
                self.kind.setCurrentIndex(max(0, self.kind.findData(bc.kind)))
            self.velocity.set_value(bc.velocity)
            self.pressure.set_value(bc.pressure)
            self.flow_rate.set_value(bc.flow_rate)
            self.water_fraction.set_value(bc.water_fraction)
            self.level.set_value(bc.level)
            self.wave_height.set_value(bc.wave_height)
            self.wave_period.set_value(bc.wave_period)
            self.wave_model.setCurrentIndex(max(0, self.wave_model.findData(bc.wave_model)))
            self.contact_angle.set_value(bc.contact_angle)
            self.tracer_value.set_value(bc.tracer_value)
            self._fill_tracer_inlet(bc)
            self.flow_series_hint.setText(describe_series(bc.flow_series, "m³/s"))
            self.level_series_hint.setText(describe_series(bc.level_series, "m"))
            self.flow_rate.setEnabled(not bc.flow_series)
            self.level.setEnabled(not bc.level_series)
            self.roughness.setCurrentIndex(max(0, self.roughness.findData(bc.roughness)))
            self.ks_mm.set_value(bc.ks * 1000.0)
            self.manning.set_value(bc.manning if bc.manning > 0 else 0.013)
        self._show_rows(bc.kind)

    def _show_rows(self, kind: str) -> None:
        self.form.setRowVisible(self.velocity, kind in ("velocityInlet", "movingWall"))
        self.form.setRowVisible(self.pressure, kind == "pressureOutlet")
        self.form.setRowVisible(self.flow_rate, kind == "flowRateInlet")
        self.form.setRowVisible(self.flow_series_button, kind == "flowRateInlet")
        self.form.setRowVisible(self.flow_series_hint, kind == "flowRateInlet" and bool(self.flow_series_hint.text()))
        self.form.setRowVisible(self.level_series_button, kind == "waterLevelOutlet")
        self.form.setRowVisible(
            self.level_series_hint, kind == "waterLevelOutlet" and bool(self.level_series_hint.text())
        )
        multiphase = self.project is not None and SOLVERS.get(self.project.physics.solver, SOLVERS["simpleFoam"]).multiphase
        self.form.setRowVisible(self.water_fraction, kind == "velocityInlet" and multiphase)
        self.form.setRowVisible(self.level, kind == "waterLevelOutlet")
        for widget in (self.wave_height, self.wave_period, self.wave_model):
            self.form.setRowVisible(widget, kind == "waveInlet")
        if kind == "waveInlet" and self.wave_model.currentData() == "solitary":
            self.form.setRowVisible(self.wave_period, False)  # a single crest has no period
        self.form.setRowVisible(self.contact_angle, kind in ("wall", "movingWall") and multiphase)
        rough = kind in ("wall", "movingWall")
        mode = self.roughness.currentData()
        self.form.setRowVisible(self.roughness, rough)
        self.form.setRowVisible(self.ks_mm, rough and mode == "ks")
        self.form.setRowVisible(self.manning, rough and mode == "manning")
        self.form.setRowVisible(self.roughness_hint, rough and mode != "smooth")
        if mode == "manning":
            self.roughness_hint.setText(
                f"n = {self.manning.value():g} is taken as a sand-grain roughness of "
                f"{ks_from_manning(self.manning.value()) * 1000:.3g} mm (Strickler)."
            )
        elif mode == "ks":
            self.roughness_hint.setText(
                f"ks = {self.ks_mm.value():g} mm corresponds to Manning's n = "
                f"{manning_from_ks(self.ks_mm.value() / 1000):.3g} (Strickler)."
            )
        concentrations = [t for t in self.project.tracers if t.kind != "age"] if self.project else []
        inlet = kind in ("velocityInlet", "flowRateInlet", "waveInlet")
        self.form.setRowVisible(self.tracer_value, inlet and len(concentrations) == 1)
        self.form.setRowVisible(self.tracer_inlet, inlet and len(concentrations) > 1)
        self.hint.setText(KIND_HINTS.get(kind, ""))

    def _fill_tracer_inlet(self, bc: Boundary) -> None:
        concentrations = [t for t in self.project.tracers if t.kind != "age"] if self.project else []
        self.tracer_inlet.setRowCount(len(concentrations))
        for row, tracer in enumerate(concentrations):
            name = QTableWidgetItem(tracer.name)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tracer_inlet.setItem(row, 0, name)
            value = bc.tracer_values.get(tracer.name, bc.tracer_value)
            self.tracer_inlet.setItem(row, 1, QTableWidgetItem(f"{value:g}"))

    def set_tracer_value(self, tracer: str, value: float) -> None:
        """The concentration of one tracer entering through the selected inlet."""
        patch = self.selected()
        if patch is None or self.project is None:
            return
        current = self.project.boundary_for(patch.name, patch.type)
        changed = dataclasses.replace(current, tracer_values={**current.tracer_values, tracer: float(value)})
        self.apply(lambda: self.project.boundaries.__setitem__(patch.name, changed))

    def _tracer_inlet_edited(self, item) -> None:
        if self._loading or item.column() != 1:
            return
        name = self.tracer_inlet.item(item.row(), 0).text()
        try:
            self.set_tracer_value(name, float(item.text().replace(",", ".")))
        except ValueError:
            pass

    def set_flow_series(self, series) -> None:
        """Give the selected flow-rate inlet a hydrograph (an empty list makes it constant again)."""
        self._set_series("flow_series", series)

    def set_level_series(self, series) -> None:
        """Give the selected tailwater outlet levels that change in time (empty = constant)."""
        self._set_series("level_series", series)

    def _set_series(self, attribute: str, series) -> None:
        patch = self.selected()
        if patch is None or self.project is None:
            return
        current = self.project.boundary_for(patch.name, patch.type)
        values = [[float(t), float(v)] for t, v in series]
        changed = dataclasses.replace(current, **{attribute: values})
        self.apply(lambda: self.project.boundaries.__setitem__(patch.name, changed))
        self._show_patch(self.patch_list.currentRow())

    def _edit_series(self, attribute: str, title: str, unit: str, constant: float, positive: bool) -> None:
        from easyfoam.gui.series import SeriesDialog

        patch = self.selected()
        if patch is None or self.project is None:
            return
        bc = self.project.boundary_for(patch.name, patch.type)
        duration = self.project.run.end_time if self.project.run.end_time > 0 else 60.0
        dialog = SeriesDialog(getattr(bc, attribute), title, unit, constant, positive, duration, self)
        if dialog.exec() == SeriesDialog.DialogCode.Accepted:
            self._set_series(attribute, [] if dialog.cleared else dialog.values())

    def _edit_flow_series(self, _checked: bool = False) -> None:
        self._edit_series("flow_series", "Inflow hydrograph", "m³/s", self.flow_rate.value(), True)

    def _edit_level_series(self, _checked: bool = False) -> None:
        self._edit_series("level_series", "Tailwater level in time", "m", self.level.value(), False)

    def _edited(self) -> None:
        patch = self.selected()
        kind = self.kind.currentData()
        if patch is None or kind in (None, "constraint"):
            return

        def edit():
            # keep what this panel does not show (time series, …) and replace what it does
            current = self.project.boundary_for(patch.name, patch.type)
            self.project.boundaries[patch.name] = dataclasses.replace(
                current,
                kind=kind, velocity=self.velocity.value(), pressure=self.pressure.value(),
                flow_rate=self.flow_rate.value(), water_fraction=self.water_fraction.value(),
                level=self.level.value(), wave_height=self.wave_height.value(),
                wave_period=self.wave_period.value(), wave_model=self.wave_model.currentData(),
                contact_angle=self.contact_angle.value(), tracer_value=self.tracer_value.value(),
                roughness=self.roughness.currentData(), ks=self.ks_mm.value() / 1000.0,
                manning=self.manning.value(),
            )  # fmt: skip

        self.apply(edit)
        if not self._loading:
            self._show_rows(kind)
            current = self.patch_list.currentItem()
            if current is not None:
                current.setIcon(icon(KIND_ICONS[kind]))


# ---------------------------------------------------------------------------


class RunPanel(Panel):
    tracer_test_requested = Signal()
    run_requested = Signal()
    stop_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.end_label = QLabel()
        self.end_time = FloatEdit(check=POSITIVE)
        self.delta_t = FloatEdit(check=POSITIVE)
        self.write_label = QLabel()
        self.write_interval = FloatEdit(check=POSITIVE)
        self.adjust = QCheckBox("Keep the Courant number below")
        self.adjust.setToolTip(
            "Transient runs: the time step is adapted so the flow crosses at most this many cells per step. "
            "1 or less is safe; larger is faster but less accurate."
        )
        self.max_courant = FloatEdit(check=POSITIVE)
        self.processors = _spin(1, max(1, os.cpu_count() or 1))
        self.purge = _spin(0, 1000)
        self.purge.setSpecialValueText("keep all")
        self.residual_target = FloatEdit(check=NOT_NEGATIVE)
        self.case_dir: Path | None = None
        self.residual_target.setToolTip(
            "A steady run stops by itself once every residual has dropped below this value. 0 runs all iterations."
        )
        self.processors.setToolTip(
            "Number of processor cores to use. The case is split up and put back together automatically."
        )
        self.forces_on = QCheckBox("Record drag and lift every iteration")
        self.force_patches = QLineEdit()
        self.force_patches.setPlaceholderText("all surfaces that come from shapes")
        self.ref_area = FloatEdit(check=POSITIVE)
        self.ref_length = FloatEdit(check=POSITIVE)
        self.ref_velocity = FloatEdit(check=NOT_NEGATIVE)
        self.drag_dir = VectorEdit()
        self.lift_dir = VectorEdit()
        self._force_inputs = [self.force_patches, self.ref_area, self.ref_length, self.ref_velocity,
                              self.drag_dir, self.lift_dir]  # fmt: skip

        self.form = QFormLayout()
        self.form.addRow(self.end_label, self.end_time)
        self.form.addRow("Time step [s]", self.delta_t)
        self.form.addRow(self.adjust, self.max_courant)
        self.form.addRow(self.write_label, self.write_interval)
        self.form.addRow("Saved results to keep", self.purge)
        self.form.addRow("Processor cores", self.processors)
        self.form.addRow("Stop below residual", self.residual_target)
        box = FoldingGroup("Run control", "run.control")
        box.setLayout(self.form)

        self.run_button = QPushButton(icon("play", "#ffffff"), "  Run")
        set_primary(self.run_button)
        self.stop_button = QPushButton(icon("square"), " Stop")
        self.stop_button.setToolTip("Once: save the current state and finish. Twice: end at once.")
        self.stop_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.continue_button = QPushButton(icon("step-forward"), " Continue")
        self.continue_button.setToolTip(
            "Carry on from the latest saved result, for example after raising the number of iterations."
        )
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.continue_requested)
        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button, 2)
        buttons.addWidget(self.continue_button, 1)
        buttons.addWidget(self.stop_button, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.issues = QLabel()
        self.issues.setWordWrap(True)

        layout = QVBoxLayout(self)
        forces = QFormLayout()
        forces.addRow(self.forces_on)
        forces.addRow("On boundaries", self.force_patches)
        self.estimate_area = QPushButton(icon("ruler"), "")
        self.estimate_area.setToolTip("Estimate the frontal area from the shapes, seen along the drag direction.")
        self.estimate_area.clicked.connect(self._estimate_area)
        area_row = QHBoxLayout()
        area_row.addWidget(self.ref_area, 1)
        area_row.addWidget(self.estimate_area)
        forces.addRow("Reference area [m²]", area_row)
        forces.addRow("Reference length [m]", self.ref_length)
        forces.addRow("Speed [m/s] (0 = inlet)", self.ref_velocity)
        forces.addRow("Drag direction", self.drag_dir)
        forces.addRow("Lift direction", self.lift_dir)
        self.force_box = force_box = FoldingGroup("Forces", "run.forces", folded=True)
        force_box.setLayout(forces)

        self.probe_table = QTableWidget(0, 3)
        self.probe_table.setHorizontalHeaderLabels(["x [m]", "y [m]", "z [m]"])
        self.probe_table.verticalHeader().setVisible(False)
        self.probe_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.probe_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.probe_table.setFixedHeight(104)
        self.probe_table.itemChanged.connect(self._probe_edited)
        add_probe = QPushButton(icon("plus"), " Add point")
        add_probe.clicked.connect(lambda: self.add_probe())
        remove_probe = QPushButton(icon("trash-2"), " Remove")
        remove_probe.clicked.connect(self.remove_probe)
        probe_buttons = QHBoxLayout()
        probe_buttons.addWidget(add_probe)
        probe_buttons.addWidget(remove_probe)
        probe_buttons.addStretch(1)
        probes = QVBoxLayout()
        probes.addWidget(_hint("Pressure and speed are recorded at these points every iteration."))
        probes.addWidget(self.probe_table)
        probes.addLayout(probe_buttons)
        self.probe_box = probe_box = FoldingGroup("Probes", "run.probes", folded=True)
        probe_box.setLayout(probes)

        self.flow_monitors = QLineEdit()
        self.flow_monitors.setPlaceholderText("boundary names, e.g. outlet")
        self.flow_monitors.setToolTip(
            "The volume flow through these boundaries is recorded every step (water only in free-surface runs). "
            "Positive values leave the domain."
        )
        self.flow_monitors.editingFinished.connect(self._flows_edited)
        flows = QFormLayout()
        flows.addRow("Through", self.flow_monitors)
        self.flow_box = flow_box = FoldingGroup("Discharge", "run.discharge", folded=True)
        flow_box.setLayout(flows)

        self.rating_discharges = QLineEdit()
        self.rating_discharges.setPlaceholderText("for example 0.02, 0.04, 0.06")
        self.rating_discharges.setToolTip("The discharges to measure the head at, in m³/s, smallest first.")
        self.rating_hold = FloatEdit(10.0, check=POSITIVE)
        self.rating_hold.setToolTip(
            "How long each discharge is held. The water level upstream must have settled by the end of it; "
            "a large reservoir needs longer."
        )
        self.rating_gauge = _spin(1, 99)
        self.rating_gauge.setToolTip("The probe point (gauge) that measures the water level upstream of the structure.")
        self.rating_auto = QCheckBox("Crest at the top of the highest structure")
        self.rating_auto.setChecked(True)
        self.rating_crest = FloatEdit(0.0)
        self.rating_crest.setEnabled(False)
        self.rating_auto.toggled.connect(lambda on: self.rating_crest.setEnabled(not on))
        self.rating_button = QPushButton(icon("chart-line"), " Set up the rating-curve run")
        self.rating_button.setToolTip(
            "Gives the flow-rate inlet the discharges one after the other and sets the end time; "
            "after the run, Rating curve in the Results step shows head against discharge."
        )
        self.rating_button.clicked.connect(self._setup_rating)
        self.rating_status = _hint("")
        rating = QFormLayout()
        rating.addRow("Discharges [m³/s]", self.rating_discharges)
        rating.addRow("Hold each for [s]", self.rating_hold)
        rating.addRow("Gauge (probe number)", self.rating_gauge)
        rating.addRow(self.rating_auto)
        rating.addRow("Crest level [m]", self.rating_crest)
        rating.addRow(self.rating_button)
        rating.addRow(self.rating_status)
        self.rating_box = FoldingGroup("Rating curve", "run.rating", folded=True)
        self.rating_box.setLayout(rating)

        self.test_inlet = QComboBox()
        self.test_outlet = QComboBox()
        self.test_kind = QComboBox()
        self.test_kind.addItem("Step: switched on and left on", "step")
        self.test_kind.addItem("Pulse: a short dose", "pulse")
        self.test_kind.setToolTip("A step test gives T10 directly, as in the field; a pulse gives the spread of times.")
        self.test_duration = FloatEdit(0.0, unit="s", check=NOT_NEGATIVE)
        self.test_duration.setToolTip("How long to follow the tracer, in seconds. 0 = three theoretical residence times V/Q.")
        self.test_button = QPushButton(icon("timer"), " Run the tracer test")
        self.test_button.setToolTip(
            "Feeds a tracer in at the inlet of the finished steady flow, keeps the flow as it is and records the "
            "concentration at the outlet: T10, mean residence time and baffling factor. Runs in a folder of its "
            "own (tracer-test), so the flow results stay."
        )
        self.test_button.clicked.connect(self.tracer_test_requested)
        self.test_status = _hint("")
        test = QFormLayout()
        test.addRow("Tracer fed in at", self.test_inlet)
        test.addRow("Recorded at", self.test_outlet)
        test.addRow("Dose", self.test_kind)
        test.addRow("Follow it for [s]", self.test_duration)
        test.addRow(self.test_button)
        test.addRow(self.test_status)
        self.test_box = FoldingGroup("Tracer test (residence time)", "run.tracer_test", folded=True)
        self.test_box.setLayout(test)

        layout.addWidget(box)
        layout.addWidget(force_box)
        layout.addWidget(probe_box)
        layout.addWidget(flow_box)
        layout.addWidget(self.rating_box)
        layout.addWidget(self.test_box)
        layout.addWidget(_hint("Running replaces earlier results of this case."))
        layout.addWidget(self.issues)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.end_time.changed.connect(lambda v: self._set("end_time", v))
        self.delta_t.changed.connect(lambda v: self._set("delta_t", v))
        self.write_interval.changed.connect(lambda v: self._set("write_interval", v))
        self.adjust.toggled.connect(lambda v: self._set("adjust_time_step", v))
        self.max_courant.changed.connect(lambda v: self._set("max_courant", v))
        self.processors.valueChanged.connect(lambda v: self._set("processors", v))
        self.purge.valueChanged.connect(lambda v: self._set("purge_write", v))
        self.residual_target.changed.connect(lambda v: self._set("residual_target", v))
        self.forces_on.toggled.connect(self._forces_toggled)
        self.force_patches.editingFinished.connect(self._patches_edited)
        self.ref_area.changed.connect(lambda v: self._force("ref_area", v))
        self.ref_length.changed.connect(lambda v: self._force("ref_length", v))
        self.ref_velocity.changed.connect(lambda v: self._force("ref_velocity", v))
        self.drag_dir.changed.connect(lambda: self._force("drag_dir", self.drag_dir.value()))
        self.lift_dir.changed.connect(lambda: self._force("lift_dir", self.lift_dir.value()))

    def load(self, project: Project, case_dir: Path | None = None) -> None:
        self.project, self.case_dir = project, case_dir
        run = project.run
        steady = solver_spec(project.physics.solver).steady
        with self.loading():
            self.end_label.setText("Iterations" if steady else "End time [s]")
            self.write_label.setText("Save every (iterations)" if steady else "Save every [s]")
            self.end_time.set_value(run.end_time)
            self.delta_t.set_value(run.delta_t)
            self.write_interval.set_value(run.write_interval)
            self.adjust.setChecked(run.adjust_time_step)
            self.max_courant.set_value(run.max_courant)
            self.processors.setValue(min(run.processors, self.processors.maximum()))
            self.purge.setValue(run.purge_write)
            self.residual_target.set_value(run.residual_target)
            monitor = project.forces
            self.forces_on.setChecked(monitor.enabled)
            self.force_patches.setText(", ".join(monitor.patches))
            self.flow_monitors.setText(", ".join(project.flow_monitors))
            self.ref_area.set_value(monitor.ref_area)
            self.ref_length.set_value(monitor.ref_length)
            self.ref_velocity.set_value(monitor.ref_velocity)
            self.drag_dir.set_value(monitor.drag_dir)
            self.lift_dir.set_value(monitor.lift_dir)
            rating = project.rating
            self.rating_discharges.setText(", ".join(f"{q:g}" for q in rating.discharges))
            self.rating_hold.set_value(rating.hold)
            self.rating_gauge.setValue(rating.gauge + 1)
            self.rating_auto.setChecked(rating.crest is None)
            self.rating_crest.set_value(rating.crest or 0.0)
        for widget in (self.delta_t, self.adjust, self.max_courant):
            widget.setEnabled(not steady)
        self.residual_target.setEnabled(steady)
        self._enable_force_inputs(project.forces.enabled)
        self._fill_probes()
        multiphase = solver_spec(project.physics.solver).multiphase
        self.force_box.setEnabled(not multiphase)
        self.force_box.setToolTip(
            "Drag and lift coefficients assume one fluid; they are not recorded in free-surface runs." if multiphase else ""
        )
        if multiphase:
            self.adjust.setEnabled(False)  # free-surface runs always adapt the time step
        self.rating_box.setEnabled(multiphase)
        self.rating_box.setToolTip("" if multiphase else "Rating curves need a free-surface run with a flow-rate inlet.")
        self._fill_test_boundaries()
        self.test_box.setEnabled(not multiphase)
        self.test_box.setToolTip(
            "For a tank, model the water surface as a frictionless lid (symmetry) and use a single-fluid flow type."
            if multiphase else ""
        )
        self.update_notes()

    def update_notes(self) -> None:
        p = self.project
        if p is None:
            return
        multiphase = solver_spec(p.physics.solver).multiphase
        self.force_box.set_note("not in free-surface runs" if multiphase else ("on" if p.forces.enabled else "off"))
        count = len(p.probes)
        self.probe_box.set_note(f"{count} point{'' if count == 1 else 's'}" if count else "none")
        self.flow_box.set_note(", ".join(p.flow_monitors) or "none")
        discharges = ", ".join(f"{q:g}" for q in p.rating.discharges)
        self.rating_box.set_note(f"{discharges} m³/s" if discharges else "not set up")

    def _fill_test_boundaries(self) -> None:
        from easyfoam.casegen.mesh import predicted_patches
        from easyfoam.foam.boundaryfile import read_boundary

        patches = (read_boundary(self.case_dir) if self.case_dir else []) or predicted_patches(self.project)
        kinds = {p.name: self.project.boundary_for(p.name, p.type).kind for p in patches}
        inlets = [n for n, k in kinds.items() if k in ("velocityInlet", "flowRateInlet")]
        outlets = [n for n, k in kinds.items() if k in ("pressureOutlet", "freeOutflow", "waterLevelOutlet")]
        with self.loading():
            for combo, names in ((self.test_inlet, inlets), (self.test_outlet, outlets)):
                current = combo.currentText()
                combo.clear()
                combo.addItems(names)
                if current in names:
                    combo.setCurrentText(current)

    def test_settings(self):
        """What the tracer test should do, as set in the panel."""
        from easyfoam.tracertest import TestSettings

        if not self.test_inlet.currentText() or not self.test_outlet.currentText():
            raise ValueError("the tracer test needs an inlet and an outlet (Boundaries step)")
        return TestSettings(self.test_inlet.currentText(), self.test_outlet.currentText(),
                            self.test_kind.currentData(), max(0.0, self.test_duration.value()))  # fmt: skip

    def setup_rating(self, discharges, hold: float, gauge: int = 0, crest: float | None = None) -> str:
        """Prepare a rating-curve run; returns what was done, or raises ValueError saying what is missing."""
        from easyfoam.model import RatingCurve, staircase

        if self.project is None:
            raise ValueError("there is no project")
        values = [float(q) for q in discharges]
        if len(values) < 2 or any(q <= 0 for q in values):
            raise ValueError("give at least two discharges above zero")
        if hold <= 0:
            raise ValueError("the hold time must be above zero")
        inlets = [name for name, bc in self.project.boundaries.items() if bc.kind == "flowRateInlet"]
        if not inlets:
            raise ValueError("make one boundary an inlet by flow rate first (Boundaries step)")
        if not self.project.probes:
            raise ValueError("add a probe point upstream of the structure to measure the water level (below)")
        ramp = min(1.0, 0.1 * hold)

        def edit():
            project = self.project
            project.rating = RatingCurve(values, hold, ramp, min(gauge, len(project.probes) - 1), crest, inlets[0])
            inlet = project.boundaries[inlets[0]]
            project.boundaries[inlets[0]] = dataclasses.replace(inlet, flow_series=staircase(values, hold, ramp))
            project.run.end_time = len(values) * hold
            project.run.write_interval = min(project.run.write_interval, hold / 2)

        self.apply(edit)
        self.load(self.project, self.case_dir)
        text = (
            f"{inlets[0]} steps through {len(values)} discharges, {hold:g} s each; the run ends at "
            f"{len(values) * hold:g} s. After the run, choose Rating curve in the Results step."
        )
        self.rating_status.setText(text)
        return text

    def _setup_rating(self, _checked: bool = False) -> None:
        text = self.rating_discharges.text().replace(";", ",").replace(" ", ",")
        try:
            values = [float(v) for v in text.split(",") if v.strip()]
            crest = None if self.rating_auto.isChecked() else self.rating_crest.value()
            self.setup_rating(values, self.rating_hold.value(), self.rating_gauge.value() - 1, crest)
        except ValueError as exc:
            QMessageBox.information(self, "Rating curve", str(exc).capitalize() + ".")

    def _force(self, attribute: str, value) -> None:
        self.apply(lambda: setattr(self.project.forces, attribute, value))

    def _enable_force_inputs(self, on: bool) -> None:
        for widget in (*self._force_inputs, self.estimate_area):
            widget.setEnabled(on)

    def _forces_toggled(self, on: bool) -> None:
        self._force("enabled", on)
        self._enable_force_inputs(on)

    def _estimate_area(self) -> None:
        if self.project is None:
            return
        try:
            area = geometry.frontal_area(self.project, self.case_dir or Path("."), self.drag_dir.value())
        except (ValueError, OSError) as exc:
            QMessageBox.information(self, "Reference area", str(exc))
            return
        if area <= 0:
            QMessageBox.information(self, "Reference area", "There are no solid shapes to measure.")
            return
        self.ref_area.set_value(area)
        self._force("ref_area", area)

    def show_issues(self, issues) -> None:
        """List what stands in the way of a run (or say that all is ready)."""
        if issues:
            self.issues.setProperty("role", "issues")
            self.issues.setText("Before running:\n" + "\n".join(f"•  {issue.text}" for issue in issues))
        else:
            self.issues.setProperty("role", "ready")
            self.issues.setText("Ready to run.")
        self.issues.style().unpolish(self.issues)
        self.issues.style().polish(self.issues)

    def _fill_probes(self) -> None:
        with self.loading():
            self.probe_table.setRowCount(len(self.project.probes))
            for row, point in enumerate(self.project.probes):
                for column, value in enumerate(point):
                    self.probe_table.setItem(row, column, QTableWidgetItem(f"{value:g}"))

    def add_probe(self, point=None) -> None:
        if self.project is None:
            return
        new = [float(c) for c in (point or (0.0, 0.0, 0.0))]
        self.apply(lambda: self.project.probes.append(new))
        self._fill_probes()

    def set_probe(self, row: int, point) -> None:
        def edit():
            self.project.probes[row] = [float(c) for c in point]

        self.apply(edit)
        self._fill_probes()

    def remove_probe(self) -> None:
        row = self.probe_table.currentRow()
        if self.project is None or not 0 <= row < len(self.project.probes):
            return
        self.apply(lambda: self.project.probes.pop(row))
        self._fill_probes()

    def _probe_edited(self, item) -> None:
        if self._loading or self.project is None:
            return
        try:
            value = float(item.text().replace(",", "."))
        except ValueError:
            self._fill_probes()
            return

        def edit():
            self.project.probes[item.row()][item.column()] = value

        self.apply(edit)

    def _flows_edited(self) -> None:
        names = [n.strip() for n in self.flow_monitors.text().split(",") if n.strip()]
        if self.project is not None and names != self.project.flow_monitors:
            self.apply(lambda: setattr(self.project, "flow_monitors", names))

    def _patches_edited(self) -> None:
        names = [n.strip() for n in self.force_patches.text().split(",") if n.strip()]
        if self.project is not None and names != self.project.forces.patches:
            self._force("patches", names)

    def _set(self, attribute: str, value) -> None:
        self.apply(lambda: setattr(self.project.run, attribute, value))

    def set_running(self, running: bool, status: str = "") -> None:
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.status.setText(status)


# ---------------------------------------------------------------------------


class ResultsPanel(Panel):
    view_changed = Signal()
    refresh_requested = Signal()
    paraview_requested = Signal()
    compute_requested = Signal(str)
    hydraulics_requested = Signal(str)  # long | pressure | loads | shear
    export_requested = Signal()
    report_requested = Signal()  # write a report of the project and its results

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source = QComboBox()
        self.source.addItem("The flow run", "flow")
        self.source.addItem("The tracer test", "tracer-test")
        self.source.setToolTip("Which results to show: the flow itself, or the tracer test that followed it.")
        self.time = QComboBox()
        self.field = QComboBox()
        self.mode = QComboBox()
        self.mode.addItem("Slice through the flow", "slice")
        self.mode.addItem("On the surfaces", "surface")
        self.mode.addItem("Mesh only", "mesh")
        self.mode.addItem("Water surface (free-surface runs)", "water")
        self.normal = QComboBox()
        for axis in "yzx":
            self.normal.addItem(f"Normal to {axis}", axis)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 100)
        self.position.setValue(50)
        self.edges = QCheckBox("Show cell edges")

        form = QFormLayout()
        form.addRow("Results of", self.source)
        form.addRow("Saved time", self.time)
        form.addRow("Quantity", self.field)
        self.display_form = form
        form.addRow("Show", self.mode)
        form.addRow("Slice plane", self.normal)
        form.addRow("Slice position", self.position)
        form.addRow(self.edges)
        box = FoldingGroup("Display", "results.display")
        box.setLayout(form)

        self.function = QComboBox()
        for key, label in POST_FUNCTIONS.items():
            self.function.addItem(label, key)
        self.compute = QPushButton(icon("calculator"), " Compute for the latest result")
        self.compute.clicked.connect(lambda: self.compute_requested.emit(self.function.currentData()))
        calc = QFormLayout()
        calc.addRow("Quantity", self.function)
        calc.addRow(self.compute)
        calc_box = FoldingGroup("Derived quantities", "results.derived", folded=True)
        calc_box.setLayout(calc)

        self.long_button = QPushButton(icon("chart-line"), " Long section")
        self.long_button.setToolTip(
            "Bed, water level, energy line, discharge and Froude number station by station along the channel, "
            "with any hydraulic jump and control section found in it."
        )
        self.residence_button = QPushButton(icon("timer"), " Residence time")
        self.residence_button.setToolTip("T10, mean residence time and baffling factor from the tracer test (Run step).")
        self.residence_button.clicked.connect(lambda: self.hydraulics_requested.emit("residence"))
        self.rating_button = QPushButton(icon("chart-line"), " Rating curve")
        self.rating_button.setToolTip(
            "Head over the crest against discharge, from a rating-curve run (set it up in the Run step)."
        )
        self.average = _spin(1, 1000)
        self.average.setToolTip(
            "Average the long section over this many saved times, ending at the one chosen above. "
            "Jumps and waves move about: an average over a few seconds is what to compare with theory."
        )
        self.structure = QComboBox()
        self.structure.setToolTip("A wall of the mesh: a weir, a gate, a pier, a spillway face.")
        self.pressure_button = QPushButton(icon("gauge"), " Pressure along it")
        self.pressure_button.setToolTip(
            "Pressure head along the surface of the structure, across the middle of the channel. "
            "Below zero the pressure is less than atmospheric."
        )
        self.loads_button = QPushButton(icon("force"), " Loads on it")
        self.loads_button.setToolTip("Force of the water on the structure and its overturning moment, at every saved time.")
        self.at_toe = QCheckBox("Moments about its downstream toe")
        self.at_toe.setChecked(True)
        self.moment_point = VectorEdit(unit="m")
        self.moment_point.setEnabled(False)
        self.moment_point.setToolTip("The point the moments are taken about, for example the hinge of a gate.")
        self.at_toe.toggled.connect(lambda on: self.moment_point.setEnabled(not on))
        self.d50 = FloatEdit(2.0, check=POSITIVE)
        self.d50.setToolTip("Median grain size of the bed material, in millimetres: 0.2 fine sand, 2 coarse sand, 20 gravel.")
        self.shear_button = QPushButton(icon("layers"), " Bed shear stress and sediment movement")
        self.shear_button.setToolTip(
            "Shear stress of the flow on the walls, and where it exceeds the stress at which the bed material "
            "starts to move (Shields)."
        )
        self.export_button = QPushButton(icon("save"), " Save the table…")
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("Save the numbers behind the last hydraulic plot as a CSV file, for a spreadsheet.")
        self.hydraulics_info = _hint("")
        pair = QHBoxLayout()
        pair.addWidget(self.pressure_button)
        pair.addWidget(self.loads_button)
        hydraulic = QFormLayout()
        overview = QHBoxLayout()
        overview.addWidget(self.long_button)
        overview.addWidget(self.rating_button)
        hydraulic.addRow(overview)
        hydraulic.addRow(self.residence_button)
        hydraulic.addRow("Average over saved times", self.average)
        hydraulic.addRow("Structure", self.structure)
        hydraulic.addRow(pair)
        hydraulic.addRow(self.at_toe)
        hydraulic.addRow("Moments about [m]", self.moment_point)
        hydraulic.addRow("Bed material d50 [mm]", self.d50)
        hydraulic.addRow(self.shear_button)
        hydraulic.addRow(self.export_button)
        hydraulic.addRow(self.hydraulics_info)
        self.hydraulics_box = FoldingGroup("Hydraulic results", "results.hydraulics")
        self.hydraulics_box.setLayout(hydraulic)
        self.long_button.clicked.connect(lambda: self.hydraulics_requested.emit("long"))
        self.rating_button.clicked.connect(lambda: self.hydraulics_requested.emit("rating"))
        self.pressure_button.clicked.connect(lambda: self.hydraulics_requested.emit("pressure"))
        self.loads_button.clicked.connect(lambda: self.hydraulics_requested.emit("loads"))
        self.shear_button.clicked.connect(lambda: self.hydraulics_requested.emit("shear"))
        self.export_button.clicked.connect(self.export_requested)

        refresh = QPushButton(icon("refresh-cw"), " Reload results")
        refresh.clicked.connect(self.refresh_requested)
        paraview = QPushButton(icon("external-link"), " Open in ParaView")
        paraview.clicked.connect(self.paraview_requested)
        self.report_button = QPushButton(icon("file-text"), " Write a report…")
        self.report_button.setToolTip(
            "The set-up, the mesh, the run, plots and pictures, and the results checked against theory "
            "(continuity, Bélanger, critical depth, the design of structures), as a web page or a PDF."
        )
        self.report_button.clicked.connect(self.report_requested)
        self.info = _hint("")

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(refresh)
        layout.addWidget(paraview)
        layout.addWidget(self.report_button)
        layout.addWidget(calc_box)
        layout.addWidget(self.info)
        layout.addWidget(self.hydraulics_box)
        layout.addStretch(1)

        for combo in (self.time, self.field, self.mode, self.normal):
            combo.currentIndexChanged.connect(self._emit_view)
        self.source.currentIndexChanged.connect(self._source_chosen)
        self.position.sliderReleased.connect(self._emit_view)
        self.edges.toggled.connect(self._emit_view)

    def _emit_view(self, *_args) -> None:
        if not self._loading:
            self.view_changed.emit()

    def _source_chosen(self, _index: int) -> None:
        if not self._loading:
            self.refresh_requested.emit()

    def show_source_choice(self, has_test: bool) -> None:
        """Offer the tracer test's results when there are any."""
        self.display_form.setRowVisible(self.source, has_test)
        if not has_test:
            with self.loading():
                self.source.setCurrentIndex(0)

    def set_available(self, times: Sequence[float], fields: Sequence[str]) -> None:
        with self.loading():
            previous_field = self.field.currentData()
            self.time.clear()
            for t in times:
                self.time.addItem(f"{t:g}", t)
            if times:
                self.time.setCurrentIndex(len(times) - 1)
            self.field.clear()
            for name in fields:
                self.field.addItem(name, name)
            wanted = previous_field if previous_field in fields else ("U" if "U" in fields else None)
            if wanted:
                self.field.setCurrentIndex(self.field.findData(wanted))
        self.info.setText(
            f"{len(times)} saved time(s), {len(fields)} quantities." if fields
            else "No results yet. Run the simulation first."
        )

    def set_structures(self, names: Sequence[str], free_surface: bool) -> None:
        """The walls whose pressure and loads can be shown; hydraulic results need a free-surface run."""
        current = self.structure.currentText()
        with self.loading():
            self.structure.clear()
            self.structure.addItems(list(names))
            if current in names:
                self.structure.setCurrentText(current)
        self.long_button.setEnabled(free_surface)
        self.rating_button.setEnabled(free_surface)
        for button in (self.pressure_button, self.loads_button):
            button.setEnabled(bool(names))
        self.hydraulics_box.setToolTip("" if free_surface else "The long section needs a free-surface run.")

    def chosen_point(self) -> list[float] | None:
        """The point for moments, or ``None`` for the structure's downstream toe."""
        return None if self.at_toe.isChecked() else self.moment_point.value()

    def select_field(self, name: str, mode: str | None = None) -> None:
        """Show a quantity (and optionally switch how it is displayed)."""
        with self.loading():
            index = self.field.findData(name)
            if index >= 0:
                self.field.setCurrentIndex(index)
            if mode is not None:
                self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        self.view_changed.emit()

    def selection(self) -> dict:
        return {
            "time": self.time.currentData(),
            "field": self.field.currentData(),
            "mode": self.mode.currentData(),
            "normal": self.normal.currentData(),
            "position": self.position.value() / 100.0,
            "edges": self.edges.isChecked(),
        }
