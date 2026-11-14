"""The 3D view: geometry preview, mesh and results."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402
from PySide6.QtCore import Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QActionGroup, QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import QtInteractor  # noqa: E402

from easyfoam.casegen.mesh import auto_location_in_mesh, location_in_mesh, uses_snappy  # noqa: E402
from easyfoam.drawn import is_drawn, triangulate
from easyfoam.gui import style  # noqa: E402
from easyfoam.gui.icons import icon  # noqa: E402
from easyfoam.model import FACES, Project, Shape  # noqa: E402
from easyfoam.results import CaseData  # noqa: E402

PATCH_COLOURS = ["#4c78a8", "#f58518", "#54a24b", "#b279a2", "#e45756", "#72b7b2", "#9d755d", "#eeca3b"]
SOLID = "#c8b99a"
#: how the boundaries of a built channel are drawn
CHANNEL_STYLE = {
    "bed": {"color": "#8c6d46"}, "banks": {"color": "#9aa66a"}, "floodplain": {"color": "#b8c78f"},
    "barrel": {"color": "#9aa3ad", "opacity": 0.45}, "atmosphere": {"color": "#9ecae1", "opacity": 0.12},
    "inlet": {"color": "#3182bd", "opacity": 0.55}, "outlet": {"color": "#e6550d", "opacity": 0.55},
}  # fmt: skip
HIGHLIGHT = "#f59e0b"
WATER_BLUE = "#3b82f6"
VIEWS = {  # name -> (direction from the scene to the camera, up)
    "+x": ((-1, 0, 0), (0, 0, 1)), "-x": ((1, 0, 0), (0, 0, 1)),
    "+y": ((0, -1, 0), (0, 0, 1)), "-y": ((0, 1, 0), (0, 0, 1)),
    "+z": ((0, 0, -1), (0, 1, 0)), "-z": ((0, 0, 1), (0, 1, 0)),
}  # fmt: skip
REGION = "#4c78a8"
OPEN_TYPES = ("patch", "symmetry", "symmetryPlane", "empty")
#: what a click in the 3D view does
PICK_MODES = {
    "values": "Read values under the cursor",
    "probe": "Place gauges and probes",
    "measure": "Measure a distance",
    "line": "Draw the long-section line",
    "off": "Off",
}
PICK_HINTS = {
    "values": "Hover over the model to read the position and the value shown there.",
    "probe": "Click to place a gauge (free surface: it measures the water level there) or a probe.",
    "measure": "Click two points on the model to measure the distance between them.",
    "line": "Click along the channel to draw the line the long section follows; double-click, right-click or press "
            "Enter to finish, Esc to start again.",
    "off": "",
}  # fmt: skip
FIELD_UNITS = {"U": "m/s", "p": "m²/s²", "p_rgh": "Pa", "k": "m²/s²", "omega": "1/s", "epsilon": "m²/s³",
               "nut": "m²/s", "alpha.water": "", "yPlus": "", "vorticity": "1/s", "wallShearStress": "m²/s²",
               "age": "s", "bedShear": "Pa", "shieldsRatio": ""}  # fmt: skip
MARKER = "#e45756"
LINE = "#f59e0b"
ACCENT_LINE = "#2563eb"
AXIS = {"x": 0, "y": 1, "z": 2}


def shape_surface(shape: Shape, case_dir: Path):
    """A PyVista surface for a shape, or ``None`` when its file is missing or it cannot be drawn yet."""
    if is_drawn(shape):
        try:
            triangles = triangulate(shape)
        except ValueError:
            return None  # for example an outline with two corners so far
        faces = np.column_stack([np.full(len(triangles), 3), np.arange(3 * len(triangles)).reshape(-1, 3)])
        surface = pv.PolyData(triangles.reshape(-1, 3), faces.ravel()).clean()
        if shape.kind == "structure" and shape.structure is not None:
            return inside_channel(surface, shape.structure)
        return surface
    if shape.kind == "stl":
        path = Path(case_dir) / "constant" / "triSurface" / shape.file
        return pv.read(str(path)) if path.is_file() else None
    if shape.kind == "sphere":
        return pv.Sphere(radius=shape.radius, center=shape.centre, theta_resolution=40, phi_resolution=40)
    if shape.kind == "cylinder":
        p1, p2 = np.array(shape.point1, float), np.array(shape.point2, float)
        height = float(np.linalg.norm(p2 - p1)) or 1e-9
        return pv.Cylinder(
            center=(p1 + p2) / 2, direction=p2 - p1, radius=shape.radius, height=height, resolution=48
        )
    (x0, y0, z0), (x1, y1, z1) = shape.min, shape.max
    return pv.Box(bounds=(x0, x1, y0, y1, z0, z1))


def inside_channel(surface, structure):
    """The part of a structure between its channel's walls and above its bed, closed where it is cut.

    The structure reaches past the walls and below the bed only so that the mesher cuts it cleanly.
    """
    from vtkmodules.vtkCommonDataModel import vtkPlane, vtkPlaneCollection
    from vtkmodules.vtkFiltersGeneral import vtkClipClosedSurface

    planes = vtkPlaneCollection()
    for normal, origin in (((0, 1, 0), (0, structure.y0, 0)), ((0, -1, 0), (0, structure.y0 + structure.width, 0)),
                           ((0, 0, 1), (0, 0, structure.bed))):  # fmt: skip
        plane = vtkPlane()  # the side its normal points to is kept
        plane.SetNormal(*normal)
        plane.SetOrigin(*origin)
        planes.AddItem(plane)
    clipper = vtkClipClosedSurface()  # all planes in one pass: clipping again would cut into the caps just made
    clipper.SetClippingPlanes(planes)
    clipper.SetInputData(surface)
    clipper.Update()
    cut = pv.wrap(clipper.GetOutput())
    return cut if cut.n_cells else surface


def _face_centres(base) -> dict[str, list[float]]:
    lo, hi = base.min, base.max
    mid = [(a + b) / 2 for a, b in zip(lo, hi)]
    centres = {}
    for face in FACES:
        axis = AXIS[face[0]]
        point = list(mid)
        point[axis] = lo[axis] if face.endswith("Min") else hi[axis]
        centres[face] = point
    return centres


def is_enclosure(patch_bounds, domain_bounds) -> bool:
    """True for a wall that wraps (nearly) the whole domain, e.g. the wall of a pipe.

    Such walls are drawn see-through, otherwise they hide everything inside.
    """
    def diagonal(b):
        return math.dist((b[0], b[2], b[4]), (b[1], b[3], b[5]))

    return diagonal(patch_bounds) >= 0.8 * diagonal(domain_bounds)


class ElidedLabel(QLabel):
    """A one-line label that shortens its text to the room it has (all of it in the tooltip): it never makes the
    window wider."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setContentsMargins(10, 0, 4, 0)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt's name
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(QColor(style.MUTED))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)


class Viewer(QWidget):
    probe_picked = Signal(list)  # a gauge or probe placed with a click: [x, y, z]
    section_line_drawn = Signal(list)  # the line the long section follows: [[x, y], ...]
    section_line_cleared = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plotter = QtInteractor(self)
        bar = QWidget()
        bar.setObjectName("viewbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(2)

        def button(text, tip, slot, icon_name=None, checkable=False) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            if icon_name:
                b.setIcon(icon(icon_name, size=16))
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        button("Fit", "Zoom so that everything is visible", self.fit, "maximize")
        button("3D", "Three-quarter view", lambda: self.set_view("iso"), "rotate-3d")
        for key in ("+x", "-x", "+y", "-y", "+z", "-z"):
            label = key.replace("-", "−").upper()
            button(label, f"Look along {label}", lambda _checked=False, k=key: self.set_view(k))
        self.parallel_button = button(
            "Flat", "Parallel projection: no perspective, sizes compare directly", self.toggle_parallel,
            "grid-2x2", checkable=True,
        )  # fmt: skip
        button("Picture", "Save the 3D view as an image file", self.save_picture, "camera")
        self.pick_button = QToolButton()
        self.pick_button.setIcon(icon("mouse-pointer-click", size=16))
        self.pick_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.pick_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.pick_button)
        modes = QActionGroup(self)
        self.pick_actions = {}
        for key, label in PICK_MODES.items():
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setToolTip(PICK_HINTS[key])
            modes.addAction(act)
            act.triggered.connect(lambda _checked=False, k=key: self.set_pick_mode(k))
            self.pick_actions[key] = act
        menu.addSeparator()
        self.clear_line_action = menu.addAction("Clear the long-section line", self.section_line_cleared.emit)
        self.pick_button.setMenu(menu)
        row.addWidget(self.pick_button)
        self.readout = ElidedLabel()  # what is under the cursor, or what a pick mode asks for
        self.readout.setObjectName("readout")
        row.addWidget(self.readout, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.plotter, 1)
        self._parts: dict = {}  # name -> surface of what is on screen, for highlighting
        self._highlighted = ""
        self.apply_theme()
        self.plotter.add_axes()
        self._scene: str | None = None  # what is shown; the camera is kept while it stays the same
        # picking: what a click does, and what it knows of the project
        self._names: dict = {}  # actor -> the shape or boundary it shows
        self._field: str | None = None  # the quantity on screen
        self._bounds = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))  # of the domain
        self._cell = 0.05  # size of a base cell
        self._free_surface = False
        self._probes: list[list[float]] = []
        self._section_line: list[list[float]] = []
        self._drawing: list[list[float]] = []  # the long-section line being drawn
        self._measure: list[np.ndarray] = []
        self._press: tuple[int, int] | None = None
        self._right_press: tuple[int, int] | None = None
        self._hover = QTimer(self, singleShot=True, interval=60)
        self._hover.timeout.connect(self._read_under_cursor)
        iren = self.plotter.iren
        iren.add_observer("LeftButtonPressEvent", self._left_pressed)
        iren.add_observer("LeftButtonReleaseEvent", self._left_released)
        iren.add_observer("RightButtonPressEvent", self._right_pressed)
        iren.add_observer("RightButtonReleaseEvent", self._right_released)
        iren.add_observer("MouseMoveEvent", self._mouse_moved)
        iren.add_observer("KeyPressEvent", self._key_pressed)
        self.set_pick_mode("values")

    # -- helpers
    def _begin(self, scene: str) -> bool:
        """Clear the view; returns True when the camera should be reset afterwards."""
        fresh = scene != self._scene
        self._scene = scene
        self.plotter.clear_sphere_widgets()
        self.plotter.clear_box_widgets()
        self.plotter.clear_line_widgets()
        self.plotter.clear()
        self._parts = {}
        self._names = {}
        self._field = None
        return fresh

    def _end(self, fresh: bool) -> None:
        if fresh:
            self.plotter.reset_camera()
            self.plotter.view_isometric()
        self._draw_highlight()
        self._draw_markers()
        self.plotter.render()

    def _add(self, mesh, name: str | None = None, **kw):
        """Add a mesh to the scene, remembering which shape or boundary it shows (for picking)."""
        actor = self.plotter.add_mesh(mesh, **kw)
        if name:
            self._names[actor] = name
        return actor

    # -- picking: values under the cursor, gauges and probes, distances, the long-section line
    def set_project(self, project: Project) -> None:
        """What picking needs to know: the domain, its cells, the gauges and the long-section line."""
        from easyfoam.solvers import solver_spec

        base = project.mesh.base
        lo, hi = [float(c) for c in base.min], [float(c) for c in base.max]
        if project.channel is not None:
            from easyfoam import channel

            lo, hi = channel.bounds(project.channel)
            self._cell = float(project.channel.cell_size)
        else:
            self._cell = min((b - a) / max(1, n) for a, b, n in zip(lo, hi, base.cells))
        self._bounds = (tuple(lo), tuple(hi))
        self._free_surface = solver_spec(project.physics.solver).multiphase
        self._probes = [list(map(float, p)) for p in project.probes]
        self._section_line = [list(map(float, p)) for p in project.section_line]

    def set_pick_mode(self, mode: str) -> None:
        self._pick_mode = mode
        self.pick_actions[mode].setChecked(True)
        short = {"values": "Values", "probe": "Gauges", "measure": "Measure", "line": "Long-section line", "off": "Pick"}
        self.pick_button.setText(short[mode])
        self.pick_button.setToolTip("What a click in the 3D view does. " + PICK_HINTS[mode])
        self._drawing, self._measure = [], []
        self.readout.setText(PICK_HINTS[mode] if mode not in ("values", "off") else "")
        self._draw_markers()
        self.plotter.render()

    def pick_mode(self) -> str:
        return self._pick_mode

    def _event_position(self) -> tuple[int, int]:
        x, y = self.plotter.iren.get_event_position()
        return int(x), int(y)

    def _pick(self, x: int, y: int):
        """What lies under a point of the view: (picker, position) or (None, None)."""
        from vtkmodules.vtkRenderingCore import vtkCellPicker

        picker = vtkCellPicker()
        picker.SetTolerance(0.0005)
        if picker.Pick(x, y, 0, self.plotter.renderer) and picker.GetCellId() >= 0:
            return picker, np.array(picker.GetPickPosition(), float)
        return None, None

    def _on_plane(self, x: int, y: int, z: float) -> np.ndarray | None:
        """Where the line of sight through a point of the view meets the horizontal plane at height z."""
        renderer = self.plotter.renderer
        ends = []
        for depth in (0.0, 1.0):
            renderer.SetDisplayPoint(x, y, depth)
            renderer.DisplayToWorld()
            wx, wy, wz, w = renderer.GetWorldPoint()
            ends.append(np.array([wx, wy, wz]) / (w or 1.0))
        direction = ends[1] - ends[0]
        if abs(direction[2]) < 1e-12:
            return None
        point = ends[0] + (z - ends[0][2]) / direction[2] * direction
        lo, hi = self._bounds
        inside = lo[0] - 1e-9 <= point[0] <= hi[0] + 1e-9 and lo[1] - 1e-9 <= point[1] <= hi[1] + 1e-9
        return point if inside else None

    def _left_pressed(self, *_args) -> None:
        self._press = self._event_position()
        if self._pick_mode == "line" and self.plotter.iren.interactor.GetRepeatCount() > 0:  # a double click
            self._finish_line()

    def _left_released(self, *_args) -> None:
        start, self._press = self._press, None
        if start is None:
            return
        x, y = self._event_position()
        if abs(x - start[0]) + abs(y - start[1]) > 4:
            return  # a drag turns the model; only a click picks
        if self._pick_mode == "probe":
            self._place_probe(x, y)
        elif self._pick_mode == "measure":
            self._measure_at(x, y)
        elif self._pick_mode == "line":
            self._extend_line(x, y)

    def _right_pressed(self, *_args) -> None:
        self._right_press = self._event_position()

    def _right_released(self, *_args) -> None:
        start, self._right_press = self._right_press, None
        if start is not None and self._pick_mode == "line":
            x, y = self._event_position()
            if abs(x - start[0]) + abs(y - start[1]) <= 4:
                self._finish_line()

    def _key_pressed(self, *_args) -> None:
        key = self.plotter.iren.interactor.GetKeySym()
        if key in ("Return", "KP_Enter") and self._pick_mode == "line":
            self._finish_line()
        elif key == "Escape" and self._pick_mode in ("line", "measure"):
            self._drawing, self._measure = [], []
            self.readout.setText(PICK_HINTS[self._pick_mode])
            self._draw_markers()
            self.plotter.render()

    def _mouse_moved(self, *_args) -> None:
        if self._pick_mode == "values" and self._press is None and self._right_press is None:
            self._hover.start()  # read once the mouse rests a moment, not at every step

    def _read_under_cursor(self) -> None:
        if self._pick_mode != "values":
            return
        try:
            x, y = self._event_position()
            picker, point = self._pick(x, y)
        except (RuntimeError, AttributeError):
            return
        self.readout.setText(self.describe(picker, point) if picker is not None else "")

    def describe(self, picker, point) -> str:
        """The position picked, what it is, and the value of the quantity shown there."""
        where = f"x {point[0]:.4g}   y {point[1]:.4g}   z {point[2]:.4g} m"
        name = self._names.get(picker.GetActor(), "")
        value = self._value(picker) if self._field else ""
        return "   ·   ".join(part for part in (where, name, value) if part)

    def _value(self, picker) -> str:
        data = picker.GetDataSet()
        if data is None:
            return ""
        mesh = pv.wrap(data)
        field = self._field
        if field in mesh.cell_data:
            value = np.asarray(mesh.cell_data[field][picker.GetCellId()], float)
        elif field in mesh.point_data and picker.GetPointId() >= 0:
            value = np.asarray(mesh.point_data[field][picker.GetPointId()], float)
        else:
            return ""
        unit = FIELD_UNITS.get(field, "")
        if value.size == 3:
            parts = ", ".join(f"{c:.3g}" for c in value)
            return f"{field} {np.linalg.norm(value):.4g} {unit} ({parts})".replace("  ", " ")
        return f"{field} {float(value.ravel()[0]):.4g} {unit}".strip()

    def gauge_point(self, x: int, y: int) -> np.ndarray | None:
        """Where a click puts a gauge or probe: on what is under it, moved half a cell into the water, or on the bed
        (free surface) or at mid-height of the domain when nothing is."""
        lo, hi = self._bounds
        picker, point = self._pick(x, y)
        if picker is not None:
            normal = np.array(picker.GetPickNormal(), float)
            towards = np.array(self.plotter.camera_position[0], float) - point
            if np.linalg.norm(normal) > 0 and np.dot(normal, towards) < 0:
                normal = -normal  # the side seen: the water side of a wall
            point = point + 0.5 * self._cell * normal
        else:
            level = lo[2] + 0.5 * self._cell if self._free_surface else (lo[2] + hi[2]) / 2
            point = self._on_plane(x, y, level)
            if point is None:
                return None
        inner = [min(max(c, a + 0.5 * self._cell), b - 0.5 * self._cell) for c, a, b in zip(point, lo, hi)]
        return np.round(np.array(inner, float), 6)

    def _place_probe(self, x: int, y: int) -> None:
        point = self.gauge_point(x, y)
        if point is None:
            self.readout.setText("That is outside the domain: click on the model.")
            return
        self.probe_picked.emit([float(c) for c in point])

    def _measure_at(self, x: int, y: int) -> None:
        picker, point = self._pick(x, y)
        if picker is None:
            self.readout.setText("Click on the model: on a shape, a boundary or a slice.")
            return
        self._measure = (self._measure if len(self._measure) == 1 else []) + [point]
        if len(self._measure) == 2:
            a, b = self._measure
            d = b - a
            self.readout.setText(f"Distance {np.linalg.norm(d):.4g} m   (dx {d[0]:.4g}, dy {d[1]:.4g}, dz {d[2]:.4g})   "
                                 f"in plan {np.hypot(d[0], d[1]):.4g} m")  # fmt: skip
        else:
            self.readout.setText(f"From x {point[0]:.4g}, y {point[1]:.4g}, z {point[2]:.4g}: click the second point.")
        self._draw_markers()
        self.plotter.render()

    def _extend_line(self, x: int, y: int) -> None:
        picker, point = self._pick(x, y)
        if picker is None:
            point = self._on_plane(x, y, self._bounds[0][2])
        if point is None:
            self.readout.setText("That is outside the domain: click on the model.")
            return
        self._drawing.append([round(float(point[0]), 6), round(float(point[1]), 6)])
        length = sum(math.dist(a, b) for a, b in zip(self._drawing, self._drawing[1:]))
        self.readout.setText(f"{len(self._drawing)} points, {length:.4g} m. Double-click, right-click or Enter to finish.")
        self._draw_markers()
        self.plotter.render()

    def _finish_line(self) -> None:
        points = [p for i, p in enumerate(self._drawing) if i == 0 or p != self._drawing[i - 1]]
        self._drawing = []
        if len(points) < 2:
            self.readout.setText("A long-section line needs at least two points.")
            return
        self.readout.setText(f"Long-section line of {len(points)} points kept: the long section now follows it.")
        self.section_line_drawn.emit(points)

    def _draw_markers(self) -> None:
        """The gauges and probes, the long-section line (and the one being drawn), and a measurement."""
        for name in ("probe-markers", "probe-labels", "section-line", "section-points", "drawing-line",
                     "drawing-points", "measure-line", "measure-points"):  # fmt: skip
            self.plotter.remove_actor(name, render=False)
        size = max(self._cell * 0.6, 1e-4)
        if self._probes:
            points = np.array(self._probes, float)
            glyphs = pv.PolyData(points).glyph(geom=pv.Sphere(radius=size), scale=False, orient=False)
            self.plotter.add_mesh(glyphs, color=MARKER, name="probe-markers", pickable=False, reset_camera=False,
                                  render=False)  # fmt: skip
            self.plotter.add_point_labels(points + [0, 0, 2.5 * size], [str(i + 1) for i in range(len(points))],
                                          font_size=10, text_color="#27313b", shape_color="white", shape_opacity=0.7,
                                          point_size=1, always_visible=True, name="probe-labels", pickable=False,
                                          reset_camera=False, render=False)  # fmt: skip
        z = self._bounds[0][2] + 0.02 * self._cell
        for key, points, colour in (("section", self._section_line, LINE), ("drawing", self._drawing, ACCENT_LINE)):
            if len(points) >= 1:
                xyz = np.array([[p[0], p[1], z] for p in points], float)
                if len(xyz) >= 2:
                    self.plotter.add_mesh(pv.lines_from_points(xyz), color=colour, line_width=4, name=f"{key}-line",
                                          pickable=False, reset_camera=False, render=False)  # fmt: skip
                self.plotter.add_mesh(pv.PolyData(xyz), color=colour, point_size=9, render_points_as_spheres=True,
                                      name=f"{key}-points", pickable=False, reset_camera=False, render=False)  # fmt: skip
        if self._measure:
            xyz = np.array(self._measure, float)
            if len(xyz) == 2:
                self.plotter.add_mesh(pv.Line(xyz[0], xyz[1]), color=ACCENT_LINE, line_width=3, name="measure-line",
                                      pickable=False, reset_camera=False, render=False)  # fmt: skip
            self.plotter.add_mesh(pv.PolyData(xyz), color=ACCENT_LINE, point_size=10, render_points_as_spheres=True,
                                  name="measure-points", pickable=False, reset_camera=False, render=False)  # fmt: skip

    def show_markers(self, project: Project) -> None:
        """Draw the gauges and the long-section line of the project again (after they change)."""
        self.set_project(project)
        self._draw_markers()
        self.plotter.render()

    # -- camera
    def fit(self) -> None:
        self.plotter.reset_camera()
        self.plotter.render()

    def set_view(self, key: str) -> None:
        """``iso`` or one of ``+x -x +y -y +z -z`` (the direction you look along)."""
        if key == "iso":
            self.plotter.view_isometric()
        else:
            vector, up = VIEWS[key]
            self.plotter.view_vector(vector, viewup=up)
        self.plotter.reset_camera()
        self.plotter.render()

    def toggle_parallel(self, on: bool | None = None) -> None:
        on = self.parallel_button.isChecked() if on is None else on
        if on:
            self.plotter.enable_parallel_projection()
        else:
            self.plotter.disable_parallel_projection()
        self.plotter.render()

    def save_picture(self) -> None:
        file, _ = QFileDialog.getSaveFileName(self, "Save picture", "view.png", "PNG image (*.png)")
        if file:
            self.plotter.screenshot(file)

    # -- highlighting
    def highlight(self, name: str) -> None:
        """Mark one shape or boundary (by name) in the current scene; "" clears the mark."""
        self._highlighted = name
        self._draw_highlight()
        self.plotter.render()

    def _draw_highlight(self) -> None:
        self.plotter.remove_actor("highlight", render=False)
        surface = self._parts.get(self._highlighted)
        if surface is not None and surface.n_cells:
            self.plotter.add_mesh(surface, color=HIGHLIGHT, opacity=0.65, name="highlight",
                                  reset_camera=False, pickable=False, render=False)  # fmt: skip

    def apply_theme(self) -> None:
        """The background of the theme in use (what is drawn takes its colours when it is drawn again)."""
        colours = style.colours()
        self.plotter.set_background(colours["view_bottom"], top=colours["view_top"])

    def show_message(self, text: str) -> None:
        self._begin("message:" + text)
        self.plotter.add_text(text, position="upper_left", font_size=11, color=style.colours()["view_line"])
        self.plotter.render()

    def close_view(self) -> None:
        self.plotter.close()

    def screenshot(self):
        return self.plotter.screenshot(return_img=True)

    # -- scenes
    def _add_handles(self, shape: Shape, target) -> None:
        """Handles to move and resize a shape with the mouse; ``target`` receives the new values."""

        def moved(new, old) -> bool:
            size = max(1e-9, max(abs(float(c)) for c in old))
            return any(abs(float(a) - float(b)) > 1e-6 * size for a, b in zip(new, old))

        if shape.kind in ("box", "wedge"):
            (x0, y0, z0), (x1, y1, z1) = shape.min, shape.max

            def box_moved(box) -> None:
                lo, hi = list(box.bounds[0::2]), list(box.bounds[1::2])
                if moved(lo + hi, list(shape.min) + list(shape.max)):
                    target.apply_box(lo, hi)

            widget = self.plotter.add_box_widget(
                box_moved, bounds=(x0, x1, y0, y1, z0, z1), factor=1.0, rotation_enabled=False,
                color=HIGHLIGHT, interaction_event="end",
            )  # fmt: skip
            widget.SetHandleSize(0.014)  # large enough to grab, in parts of the view
            widget.GetHandleProperty().SetColor(0.145, 0.388, 0.922)
        elif shape.kind == "sphere":

            def centre_moved(centre) -> None:
                if moved(centre, shape.centre):
                    target.apply_centre(centre)

            self.plotter.add_sphere_widget(
                centre_moved, center=shape.centre, radius=1.03 * shape.radius, style="wireframe",
                color=HIGHLIGHT, theta_resolution=16, phi_resolution=16, test_callback=False,
                interaction_event="end",
            )  # fmt: skip
        elif shape.kind in ("cylinder", "cone"):

            placed = []  # the widget reports its own starting position once, before it is put on the axis

            def axis_moved(start, end) -> None:
                if placed and moved(list(start) + list(end), list(shape.point1) + list(shape.point2)):
                    target.apply_axis(start, end)

            widget = self.plotter.add_line_widget(
                axis_moved, use_vertices=True, color=HIGHLIGHT, interaction_event="end"
            )
            widget.SetPoint1(*[float(c) for c in shape.point1])
            widget.SetPoint2(*[float(c) for c in shape.point2])
            widget.SetHandleSize(0.014)
            widget.GetHandleProperty().SetColor(0.145, 0.388, 0.922)
            placed.append(True)

    def show_geometry(self, project: Project, case_dir: Path, on_point_moved=None, handles=None) -> None:
        fresh = self._begin("geometry")
        self.set_project(project)
        base = project.mesh.base
        if project.channel is not None:
            self._show_channel(project.channel)
        else:
            (x0, y0, z0), (x1, y1, z1) = base.min, base.max
            box = pv.Box(bounds=(x0, x1, y0, y1, z0, z1))
            self.plotter.add_mesh(box, style="wireframe", color=style.colours()["view_line"], line_width=1.5,
                                  reset_camera=False, pickable=False)  # an outline: clicks go through it  # fmt: skip
            labels = {face: base.faces[face].name for face in FACES}
            centres = _face_centres(base)
            self.plotter.add_point_labels(
                np.array([centres[f] for f in FACES]), [labels[f] for f in FACES],
                font_size=11, text_color="#27313b", shape_opacity=0.55, shape_color="white",
                point_size=1, always_visible=True, reset_camera=False,
            )  # fmt: skip
        missing = []
        for shape in project.shapes:
            surface = shape_surface(shape, case_dir)
            if surface is None:
                missing.append(shape.name)
                continue
            self._parts[shape.name] = surface
            if shape.role == "refinement":
                self._add(surface, shape.name, color=REGION, opacity=0.18, reset_camera=False, pickable=False)
                self.plotter.add_mesh(surface, style="wireframe", color=REGION, opacity=0.5, reset_camera=False,
                                      pickable=False)  # fmt: skip
            else:
                # the shape that contains the fluid is see-through, so the point inside it shows
                opacity = 0.3 if shape.name == project.mesh.fluid_inside else 1.0
                self._add(surface, shape.name, color=SOLID, smooth_shading=True, opacity=opacity,
                          reset_camera=False)  # fmt: skip
        if uses_snappy(project):
            try:
                point = location_in_mesh(project, case_dir)
            except (ValueError, OSError):
                point = auto_location_in_mesh(base)
            size = 0.012 * math.dist(base.min, base.max)
            if on_point_moved is not None and project.mesh.location_in_mesh is not None:
                # the user places the point by hand: let them drag it
                self.plotter.add_sphere_widget(
                    lambda centre: on_point_moved([float(c) for c in centre]),
                    center=point, radius=1.6 * size, color="#e45756",
                    test_callback=False, interaction_event="end",
                )  # fmt: skip
            else:
                self.plotter.add_mesh(pv.Sphere(radius=size, center=point), color="#e45756", reset_camera=False,
                                      pickable=False)  # fmt: skip
        if handles is not None:
            self._add_handles(*handles)
        if missing:
            self.plotter.add_text("Cannot show yet: " + ", ".join(missing), font_size=10, color="#b33")
        self._end(fresh)

    def _show_channel(self, ch) -> None:
        """A built channel: its boundaries and the water in it at the start."""
        from easyfoam import channel as chm

        try:
            parts = chm.preview(ch)
        except (ValueError, ZeroDivisionError) as exc:
            self.plotter.add_text(f"Cannot show the channel: {exc}", font_size=10, color="#b33")
            return
        caps = {}
        for name, (points, cells) in parts.items():
            faces = np.hstack([np.full((len(cells), 1), cells.shape[1]), cells]).ravel()
            surface = pv.PolyData(np.asarray(points, float), faces)
            self._add(surface, name, reset_camera=False, **CHANNEL_STYLE.get(name, {"color": SOLID}))
            if name in ("inlet", "outlet"):
                caps[name] = np.asarray(points)[cells[0]].mean(axis=0)
        water = chm.water_surface(ch)
        if water is not None:
            points, cells = water
            faces = np.hstack([np.full((len(cells), 1), 4), cells]).ravel()
            self.plotter.add_mesh(pv.PolyData(points, faces), color="#4c8ed9", opacity=0.55, reset_camera=False)
        if caps:
            self.plotter.add_point_labels(
                np.array(list(caps.values())), list(caps), font_size=11, text_color="#27313b", shape_opacity=0.55,
                shape_color="white", point_size=1, always_visible=True, reset_camera=False,
            )  # fmt: skip

    def _add_patches(self, data: CaseData, patch_types: Mapping[str, str], field: str | None, edges: bool):
        for index, (name, surface) in enumerate(data.patches.items()):
            if surface is None or surface.n_cells == 0:
                continue
            self._parts[name] = surface
            is_open = patch_types.get(name, "patch") in OPEN_TYPES
            wraps = not is_open and is_enclosure(surface.bounds, data.internal.bounds)
            colour = PATCH_COLOURS[index % len(PATCH_COLOURS)]
            if is_open:
                self.plotter.add_mesh(
                    surface.extract_feature_edges(boundary_edges=True, feature_edges=False,
                                                  manifold_edges=False, non_manifold_edges=False),
                    color=colour, line_width=2, label=name, reset_camera=False, pickable=False,
                )  # fmt: skip
                if field is None:
                    self._add(surface, name, color=colour, opacity=0.08, show_edges=edges, edge_color=colour,
                              reset_camera=False)  # fmt: skip
            elif field is not None and field in surface.array_names:
                self._add(surface, name, scalars=field, preference="cell", cmap="turbo", show_edges=edges,
                          scalar_bar_args={"title": field, "color": style.colours()["view_text"]},
                          reset_camera=False)  # fmt: skip
            else:
                opacity = (0.12 if field is not None else 0.3) if wraps else 1.0
                self._add(surface, name, color=SOLID if field is not None else colour,
                          show_edges=edges and not (wraps and field is not None), opacity=opacity, label=name,
                          reset_camera=False, pickable=not wraps)  # a see-through wall lets clicks reach inside  # fmt: skip

    def show_mesh(self, data: CaseData, patch_types: Mapping[str, str]) -> None:
        fresh = self._begin("mesh")
        self._add_patches(data, patch_types, None, edges=True)
        internal = data.internal
        if internal is not None and internal.n_cells:
            cut = internal.slice(normal="y", origin=internal.center)
            if cut.n_cells:
                self.plotter.add_mesh(cut, color="#eef2f6", show_edges=True, edge_color="#55616d",
                                      reset_camera=False)  # fmt: skip
            self.plotter.add_text(f"{internal.n_cells:,} cells", position="upper_left", font_size=11,
                                  color=style.colours()["view_text"])  # fmt: skip
        self.plotter.add_legend(bcolor=None, face="rectangle", size=(0.16, 0.16))
        self._end(fresh)

    def show_results(
        self,
        data: CaseData,
        patch_types: Mapping[str, str],
        field: str | None,
        mode: str = "slice",
        normal: str = "y",
        position: float = 0.5,
        edges: bool = False,
        time: float | None = None,
    ) -> None:
        if mode == "mesh" or field is None:
            self.show_mesh(data, patch_types)
            return
        fresh = self._begin("results")
        self._field = field
        internal = data.internal
        if mode == "water" and "alpha.water" in internal.array_names:
            # the free surface: where the cells are half water, half air
            self._add_patches(data, patch_types, "", edges=False)
            surface = internal.cell_data_to_point_data().contour([0.5], scalars="alpha.water")
            if surface.n_points:
                if field != "alpha.water" and field in surface.array_names:
                    self._add(surface, "water surface", scalars=field, cmap="turbo", smooth_shading=True,
                              show_edges=edges, reset_camera=False,
                              scalar_bar_args={"title": field, "color": style.colours()["view_text"]})  # fmt: skip
                else:
                    self._add(surface, "water surface", color=WATER_BLUE, smooth_shading=True, show_edges=edges,
                              reset_camera=False)  # fmt: skip
        elif mode == "surface":
            self._add_patches(data, patch_types, field, edges)
        else:
            self._add_patches(data, patch_types, "", edges=False)  # walls in plain colour for context
            bounds = internal.bounds
            axis = AXIS[normal]
            lo, hi = bounds[2 * axis], bounds[2 * axis + 1]
            origin = list(internal.center)
            origin[axis] = lo + (hi - lo) * min(max(position, 0.001), 0.999)
            cut = internal.slice(normal=normal, origin=origin)
            if cut.n_cells and field in cut.array_names:
                self._add(cut, f"slice normal to {normal}", scalars=field, preference="cell", cmap="turbo",
                          show_edges=edges, scalar_bar_args={"title": field, "color": style.colours()["view_text"]},
                          reset_camera=False)  # fmt: skip
        label = field if time is None else f"{field}   at {time:g}"
        self.plotter.add_text(label, position="upper_left", font_size=11, color=style.colours()["view_text"])
        self._end(fresh)
