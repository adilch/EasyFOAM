"""The six workflow panels. Each one edits the project and emits ``changed``."""

from __future__ import annotations

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
from easyfoam.foam.boundaryfile import Patch
from easyfoam.gui.widgets import FloatEdit, VectorEdit
from easyfoam.model import CONSTRAINT_TYPES, FACES, KINDS_FOR_TYPE, BaseFace, Boundary, Project, Shape
from easyfoam.solvers import MATERIALS, POST_FUNCTIONS, SOLVERS, TURBULENCE, solver_spec

NAME_ROLE = Qt.ItemDataRole.UserRole  # == 0x0100

KIND_LABELS = {
    "velocityInlet": "Velocity inlet",
    "pressureOutlet": "Pressure outlet",
    "slip": "Slip (frictionless)",
    "wall": "Wall (no slip)",
    "movingWall": "Moving wall",
}
KIND_HINTS = {
    "velocityInlet": "Fluid enters with this velocity.",
    "pressureOutlet": "Fluid leaves freely at the given pressure (kinematic gauge pressure, p/rho).",
    "slip": "No flow through the surface and no friction along it. Good for far-field sides.",
    "wall": "Solid surface, the fluid sticks to it.",
    "movingWall": "Solid surface that moves with this velocity (e.g. a belt or lid).",
    "constraint": "This condition is fixed by the patch type chosen in the mesh.",
}
FACE_TYPES = ("patch", "wall", "symmetry", "empty")


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

    def apply(self, edit: Callable[[], None]) -> None:
        """Run an edit of the project unless the panel is being filled."""
        if self._loading or self.project is None:
            return
        edit()
        self.changed.emit()


# ---------------------------------------------------------------------------


class GeometryPanel(Panel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.case_dir: Path | None = None

        self.shape_list = QListWidget()
        self.shape_list.currentRowChanged.connect(self._show_shape)

        import_button = QPushButton("Import STL…")
        import_button.clicked.connect(self._import_stl)
        add_button = QPushButton("Add shape")
        menu = QMenu(add_button)
        for kind, label in (("box", "Box"), ("sphere", "Sphere"), ("cylinder", "Cylinder")):
            menu.addAction(label, lambda k=kind: self.add_primitive(k))
        add_button.setMenu(menu)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.remove_selected)
        buttons = QHBoxLayout()
        for b in (import_button, add_button, remove_button):
            buttons.addWidget(b)

        self.role = QComboBox()
        self.role.addItem("Solid surface (flow goes around it)", "wall")
        self.role.addItem("Refinement region (finer mesh inside)", "refinement")
        self.centre = VectorEdit()
        self.radius = FloatEdit(0.5)
        self.box_min = VectorEdit()
        self.box_max = VectorEdit()
        self.point1 = VectorEdit()
        self.point2 = VectorEdit()
        self.level_min = _spin(0, 10)
        self.level_max = _spin(0, 10)
        self.layers = _spin(0, 20)
        self.region_level = _spin(0, 10)
        self.near_distance = FloatEdit(0.0)
        self.near_level = _spin(0, 10)
        self.regions = QTableWidget(0, 2)
        self.regions.setHorizontalHeaderLabels(["STL region", "Becomes"])
        self.regions.verticalHeader().setVisible(False)
        self.regions.horizontalHeader().setStretchLastSection(True)
        self._region_types: dict[str, QComboBox] = {}

        self.form = QFormLayout()
        self.form.addRow("Use as", self.role)
        self.form.addRow("Centre", self.centre)
        self.form.addRow("Radius", self.radius)
        self.form.addRow("Corner (min)", self.box_min)
        self.form.addRow("Corner (max)", self.box_max)
        self.form.addRow("Axis start", self.point1)
        self.form.addRow("Axis end", self.point2)
        self.form.addRow("Surface refinement, min", self.level_min)
        self.form.addRow("Surface refinement, max", self.level_max)
        self.form.addRow("Boundary-layer cells", self.layers)
        self.form.addRow("Refinement inside", self.region_level)
        self.form.addRow("Also refine within [m]", self.near_distance)
        self.form.addRow("… to level", self.near_level)
        self.form.addRow(self.regions)
        self.details = QGroupBox("Selected shape")
        self.details.setLayout(self.form)

        layout = QVBoxLayout(self)
        layout.addWidget(_hint("Surfaces to mesh around, and regions where the mesh should be finer."))
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
        self.level_min.valueChanged.connect(self._set_level_min)
        self.level_max.valueChanged.connect(self._set_level_max)
        self.layers.valueChanged.connect(lambda v: self._set("layers", v))
        self.region_level.valueChanged.connect(lambda v: self._set("region_level", v))
        self.near_distance.changed.connect(lambda v: self._set("near_distance", v))
        self.near_level.valueChanged.connect(lambda v: self._set("near_level", v))

    # -- model <-> widgets
    def load(self, project: Project, case_dir: Path | None) -> None:
        self.project, self.case_dir = project, case_dir
        self._refill(select=0)

    def _refill(self, select: int) -> None:
        with self.loading():
            self.shape_list.clear()
            for shape in self.project.shapes:
                kind = "STL surface" if shape.kind == "stl" else shape.kind
                self.shape_list.addItem(f"{shape.name}   ({kind})")
            if self.project.shapes:
                self.shape_list.setCurrentRow(max(0, min(select, len(self.project.shapes) - 1)))
        self._show_shape(self.shape_list.currentRow())

    def selected(self) -> Shape | None:
        row = self.shape_list.currentRow()
        if self.project is None or not 0 <= row < len(self.project.shapes):
            return None
        return self.project.shapes[row]

    def _show_shape(self, _row: int) -> None:
        shape = self.selected()
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
            self.level_min.setValue(shape.level_min)
            self.level_max.setValue(shape.level_max)
            self.layers.setValue(shape.layers)
            self.region_level.setValue(shape.region_level)
            self.near_distance.set_value(shape.near_distance)
            self.near_level.setValue(shape.near_level)
            self._fill_regions(shape)
        is_wall = shape.role == "wall"
        visible = {
            self.role: shape.kind != "stl",
            self.centre: shape.kind == "sphere",
            self.radius: shape.kind in ("sphere", "cylinder"),
            self.box_min: shape.kind == "box",
            self.box_max: shape.kind == "box",
            self.point1: shape.kind == "cylinder",
            self.point2: shape.kind == "cylinder",
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

    def _set(self, attribute: str, value, refresh: bool = False) -> None:
        shape = self.selected()
        if shape is None:
            return
        self.apply(lambda: setattr(shape, attribute, value))
        if refresh and not self._loading:
            self._show_shape(self.shape_list.currentRow())

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
    def _unique_name(self, stem: str) -> str:
        taken = {s.name for s in self.project.shapes}
        n = 1
        while f"{stem}{n}" in taken:
            n += 1
        return f"{stem}{n}"

    def add_primitive(self, kind: str) -> None:
        if self.project is None:
            return
        shape = Shape(name=self._unique_name(kind), kind=kind)
        self.apply(lambda: self.project.shapes.append(shape))
        self._refill(select=len(self.project.shapes) - 1)

    def remove_selected(self) -> None:
        shape = self.selected()
        if shape is None:
            return
        row = self.shape_list.currentRow()
        self.apply(lambda: self.project.shapes.remove(shape))
        self._refill(select=row)

    def _import_stl(self) -> None:
        if self.project is None or self.case_dir is None:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Import STL", "", "STL surfaces (*.stl *.STL)")
        for file in files:
            try:
                shape = geometry.import_stl(self.case_dir, Path(file))
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Import STL", str(exc))
                continue

            def add(shape=shape):
                self.project.shapes[:] = [s for s in self.project.shapes if s.name != shape.name]
                self.project.shapes.append(shape)

            self.apply(add)
        if files:
            self._refill(select=len(self.project.shapes) - 1)


# ---------------------------------------------------------------------------


class MeshPanel(Panel):
    generate_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.case_dir: Path | None = None

        self.base_min = VectorEdit()
        self.base_max = VectorEdit()
        self.cells = [_spin(1, 5000) for _ in range(3)]
        cells_row = QHBoxLayout()
        for axis, spin in zip("xyz", self.cells):
            cells_row.addWidget(QLabel(axis))
            cells_row.addWidget(spin, 1)
        self.summary = _hint("")
        fit = QPushButton("Fit a wind tunnel around the geometry")
        fit.clicked.connect(self._fit)

        base_form = QFormLayout()
        base_form.addRow("Corner (min)", self.base_min)
        base_form.addRow("Corner (max)", self.base_max)
        base_form.addRow("Cells", cells_row)
        base_form.addRow(self.summary)
        base_form.addRow(fit)
        base = QGroupBox("Base mesh (box of cubes)")
        base.setLayout(base_form)

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
        self.location = VectorEdit()
        self.fluid_region = QComboBox()
        options = QFormLayout()
        options.addRow("The fluid is", self.fluid_region)
        options.addRow(self.snappy)
        options.addRow(self.snap)
        options.addRow(self.add_layers)
        options.addRow(self.auto_location)
        options.addRow("Point inside the fluid", self.location)
        box = QGroupBox("Around the geometry")
        box.setLayout(options)

        self.generate = QPushButton("Generate mesh")
        self.generate.clicked.connect(self.generate_requested)

        layout = QVBoxLayout(self)
        layout.addWidget(base)
        layout.addWidget(QLabel("Faces of the base mesh"))
        layout.addWidget(self.faces)
        layout.addWidget(box)
        layout.addWidget(_hint(
            "For flow inside a part (pipes, ducts) set the point inside the fluid by hand: "
            "it decides which side of the surfaces is kept."
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
        self.nu = FloatEdit()
        self.rho = FloatEdit()
        self.velocity = VectorEdit()
        self.intensity = FloatEdit()
        self.length = FloatEdit()
        self.numerics = QComboBox()
        self.numerics.addItem("Robust (first-order turbulence, forgiving)", "robust")
        self.numerics.addItem("Accurate (second order, needs a good mesh)", "accurate")
        self.potential = QCheckBox("Start from a potential-flow solution")

        flow = QFormLayout()
        flow.addRow("Flow type", self.solver)
        flow.addRow("Turbulence", self.turbulence)
        flow.addRow("Numerics", self.numerics)
        flow_box = QGroupBox("Model")
        flow_box.setLayout(flow)

        fluid = QFormLayout()
        fluid.addRow("Fluid", self.material)
        fluid.addRow("Kinematic viscosity [m²/s]", self.nu)
        fluid.addRow("Density [kg/m³]", self.rho)
        fluid_box = QGroupBox("Fluid")
        fluid_box.setLayout(fluid)

        start = QFormLayout()
        start.addRow("Initial velocity [m/s]", self.velocity)
        start.addRow("Turbulence intensity (0–1)", self.intensity)
        start.addRow("Turbulence length scale [m]", self.length)
        start.addRow(self.potential)
        start_box = QGroupBox("Starting state and inlet turbulence")
        start_box.setLayout(start)

        layout = QVBoxLayout(self)
        for box in (flow_box, fluid_box, start_box):
            layout.addWidget(box)
        layout.addWidget(_hint(
            "Pressure is the kinematic pressure p/ρ in m²/s². Multiply by the density to get pascals."
        ))
        layout.addStretch(1)

        self.solver.currentIndexChanged.connect(lambda: self._set("solver", self.solver.currentData()))
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
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.patches: list[Patch] = []
        self.source = _hint("")
        self.patch_list = QListWidget()
        self.kind = QComboBox()
        self.velocity = VectorEdit()
        self.pressure = FloatEdit()
        self.hint = _hint("")

        self.form = QFormLayout()
        self.form.addRow("Condition", self.kind)
        self.form.addRow("Velocity [m/s]", self.velocity)
        self.form.addRow("Pressure p/ρ [m²/s²]", self.pressure)
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
                self.patch_list.addItem(item)
            if self.patches:
                self.patch_list.setCurrentRow(0)
        self._show_patch(self.patch_list.currentRow())

    def selected(self) -> Patch | None:
        row = self.patch_list.currentRow()
        return self.patches[row] if 0 <= row < len(self.patches) else None

    def _show_patch(self, _row: int) -> None:
        patch = self.selected()
        self.details.setEnabled(patch is not None)
        if patch is None or self.project is None:
            return
        bc = self.project.boundary_for(patch.name, patch.type)
        with self.loading():
            self.kind.clear()
            kinds = KINDS_FOR_TYPE.get(patch.type, ())
            if patch.type in CONSTRAINT_TYPES or not kinds:
                self.kind.addItem(f"Set by the mesh ({patch.type})", "constraint")
                self.kind.setEnabled(False)
            else:
                for kind in kinds:
                    self.kind.addItem(KIND_LABELS[kind], kind)
                self.kind.setEnabled(True)
                self.kind.setCurrentIndex(max(0, self.kind.findData(bc.kind)))
            self.velocity.set_value(bc.velocity)
            self.pressure.set_value(bc.pressure)
        self._show_rows(bc.kind)

    def _show_rows(self, kind: str) -> None:
        self.form.setRowVisible(self.velocity, kind in ("velocityInlet", "movingWall"))
        self.form.setRowVisible(self.pressure, kind == "pressureOutlet")
        self.hint.setText(KIND_HINTS.get(kind, ""))

    def _edited(self) -> None:
        patch = self.selected()
        kind = self.kind.currentData()
        if patch is None or kind in (None, "constraint"):
            return

        def edit():
            self.project.boundaries[patch.name] = Boundary(
                kind=kind, velocity=self.velocity.value(), pressure=self.pressure.value()
            )

        self.apply(edit)
        if not self._loading:
            self._show_rows(kind)


# ---------------------------------------------------------------------------


class RunPanel(Panel):
    run_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.end_label = QLabel()
        self.end_time = FloatEdit()
        self.delta_t = FloatEdit()
        self.write_label = QLabel()
        self.write_interval = FloatEdit()
        self.adjust = QCheckBox("Adapt the time step to keep the Courant number below")
        self.max_courant = FloatEdit()
        self.processors = _spin(1, max(1, os.cpu_count() or 1))
        self.purge = _spin(0, 1000)
        self.purge.setSpecialValueText("keep all")
        self.residual_target = FloatEdit()
        self.forces_on = QCheckBox("Record drag and lift coefficients every iteration")
        self.force_patches = QLineEdit()
        self.force_patches.setPlaceholderText("all surfaces that come from shapes")
        self.ref_area = FloatEdit()
        self.ref_length = FloatEdit()
        self.ref_velocity = FloatEdit()
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
        self.form.addRow("Stop when residuals fall below", self.residual_target)
        box = QGroupBox("Run control")
        box.setLayout(self.form)

        self.run_button = QPushButton("Run")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.stop_button)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        forces = QFormLayout()
        forces.addRow(self.forces_on)
        forces.addRow("On boundaries", self.force_patches)
        forces.addRow("Reference area [m²]", self.ref_area)
        forces.addRow("Reference length [m]", self.ref_length)
        forces.addRow("Reference speed [m/s], 0 = inlet", self.ref_velocity)
        forces.addRow("Drag direction", self.drag_dir)
        forces.addRow("Lift direction", self.lift_dir)
        force_box = QGroupBox("Forces")
        force_box.setLayout(forces)

        layout.addWidget(box)
        layout.addWidget(force_box)
        layout.addWidget(_hint("Running replaces earlier results of this case."))
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

    def load(self, project: Project) -> None:
        self.project = project
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
            self.ref_area.set_value(monitor.ref_area)
            self.ref_length.set_value(monitor.ref_length)
            self.ref_velocity.set_value(monitor.ref_velocity)
            self.drag_dir.set_value(monitor.drag_dir)
            self.lift_dir.set_value(monitor.lift_dir)
        for widget in (self.delta_t, self.adjust, self.max_courant):
            widget.setEnabled(not steady)
        self.residual_target.setEnabled(steady)
        self._enable_force_inputs(project.forces.enabled)

    def _force(self, attribute: str, value) -> None:
        self.apply(lambda: setattr(self.project.forces, attribute, value))

    def _enable_force_inputs(self, on: bool) -> None:
        for widget in self._force_inputs:
            widget.setEnabled(on)

    def _forces_toggled(self, on: bool) -> None:
        self._force("enabled", on)
        self._enable_force_inputs(on)

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.time = QComboBox()
        self.field = QComboBox()
        self.mode = QComboBox()
        self.mode.addItem("Slice through the flow", "slice")
        self.mode.addItem("On the surfaces", "surface")
        self.mode.addItem("Mesh only", "mesh")
        self.normal = QComboBox()
        for axis in "yzx":
            self.normal.addItem(f"Normal to {axis}", axis)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 100)
        self.position.setValue(50)
        self.edges = QCheckBox("Show cell edges")

        form = QFormLayout()
        form.addRow("Saved time", self.time)
        form.addRow("Quantity", self.field)
        form.addRow("Show", self.mode)
        form.addRow("Slice plane", self.normal)
        form.addRow("Slice position", self.position)
        form.addRow(self.edges)
        box = QGroupBox("Display")
        box.setLayout(form)

        self.function = QComboBox()
        for key, label in POST_FUNCTIONS.items():
            self.function.addItem(label, key)
        self.compute = QPushButton("Compute for the latest result")
        self.compute.clicked.connect(lambda: self.compute_requested.emit(self.function.currentData()))
        calc = QFormLayout()
        calc.addRow("Quantity", self.function)
        calc.addRow(self.compute)
        calc_box = QGroupBox("Derived quantities")
        calc_box.setLayout(calc)

        refresh = QPushButton("Reload results")
        refresh.clicked.connect(self.refresh_requested)
        paraview = QPushButton("Open in ParaView")
        paraview.clicked.connect(self.paraview_requested)
        self.info = _hint("")

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(refresh)
        layout.addWidget(paraview)
        layout.addWidget(calc_box)
        layout.addWidget(self.info)
        layout.addStretch(1)

        for combo in (self.time, self.field, self.mode, self.normal):
            combo.currentIndexChanged.connect(self._emit_view)
        self.position.sliderReleased.connect(self._emit_view)
        self.edges.toggled.connect(self._emit_view)

    def _emit_view(self, *_args) -> None:
        if not self._loading:
            self.view_changed.emit()

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
