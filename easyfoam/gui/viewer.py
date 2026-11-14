"""The 3D view: geometry preview, mesh and results."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QToolButton, QVBoxLayout, QWidget  # noqa: E402
from pyvistaqt import QtInteractor  # noqa: E402

from easyfoam.casegen.mesh import auto_location_in_mesh, location_in_mesh, uses_snappy  # noqa: E402
from easyfoam.drawn import is_drawn, triangulate
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


class Viewer(QWidget):
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
        row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.plotter, 1)
        self._parts: dict = {}  # name -> surface of what is on screen, for highlighting
        self._highlighted = ""
        self.plotter.set_background("#f4f6f8", top="#cfd9e3")
        self.plotter.add_axes()
        self._scene: str | None = None  # what is shown; the camera is kept while it stays the same

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
        return fresh

    def _end(self, fresh: bool) -> None:
        if fresh:
            self.plotter.reset_camera()
            self.plotter.view_isometric()
        self._draw_highlight()
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

    def show_message(self, text: str) -> None:
        self._begin("message:" + text)
        self.plotter.add_text(text, position="upper_left", font_size=11, color="#44505c")
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
        base = project.mesh.base
        if project.channel is not None:
            self._show_channel(project.channel)
        else:
            (x0, y0, z0), (x1, y1, z1) = base.min, base.max
            box = pv.Box(bounds=(x0, x1, y0, y1, z0, z1))
            self.plotter.add_mesh(box, style="wireframe", color="#44505c", line_width=1.5, reset_camera=False)
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
                self.plotter.add_mesh(surface, color=REGION, opacity=0.18, reset_camera=False)
                self.plotter.add_mesh(surface, style="wireframe", color=REGION, opacity=0.5, reset_camera=False)
            else:
                # the shape that contains the fluid is see-through, so the point inside it shows
                opacity = 0.3 if shape.name == project.mesh.fluid_inside else 1.0
                self.plotter.add_mesh(surface, color=SOLID, smooth_shading=True, opacity=opacity,
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
                self.plotter.add_mesh(pv.Sphere(radius=size, center=point), color="#e45756", reset_camera=False)
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
            self.plotter.add_mesh(surface, reset_camera=False, **CHANNEL_STYLE.get(name, {"color": SOLID}))
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
                    color=colour, line_width=2, label=name, reset_camera=False,
                )  # fmt: skip
                if field is None:
                    self.plotter.add_mesh(surface, color=colour, opacity=0.08, show_edges=edges,
                                          edge_color=colour, reset_camera=False)  # fmt: skip
            elif field is not None and field in surface.array_names:
                self.plotter.add_mesh(surface, scalars=field, preference="cell", cmap="turbo",
                                      show_edges=edges, scalar_bar_args={"title": field, "color": "#27313b"},
                                      reset_camera=False)  # fmt: skip
            else:
                opacity = (0.12 if field is not None else 0.3) if wraps else 1.0
                self.plotter.add_mesh(surface, color=SOLID if field is not None else colour,
                                      show_edges=edges and not (wraps and field is not None),
                                      opacity=opacity, label=name, reset_camera=False)  # fmt: skip

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
                                  color="#27313b")  # fmt: skip
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
        internal = data.internal
        if mode == "water" and "alpha.water" in internal.array_names:
            # the free surface: where the cells are half water, half air
            self._add_patches(data, patch_types, "", edges=False)
            surface = internal.cell_data_to_point_data().contour([0.5], scalars="alpha.water")
            if surface.n_points:
                if field != "alpha.water" and field in surface.array_names:
                    self.plotter.add_mesh(surface, scalars=field, cmap="turbo", smooth_shading=True,
                                          show_edges=edges, reset_camera=False,
                                          scalar_bar_args={"title": field, "color": "#27313b"})  # fmt: skip
                else:
                    self.plotter.add_mesh(surface, color=WATER_BLUE, smooth_shading=True, show_edges=edges,
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
                self.plotter.add_mesh(cut, scalars=field, preference="cell", cmap="turbo", show_edges=edges,
                                      scalar_bar_args={"title": field, "color": "#27313b"},
                                      reset_camera=False)  # fmt: skip
        label = field if time is None else f"{field}   at {time:g}"
        self.plotter.add_text(label, position="upper_left", font_size=11, color="#27313b")
        self._end(fresh)
