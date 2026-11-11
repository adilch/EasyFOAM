"""The 3D view: geometry preview, mesh and results."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402
from PySide6.QtWidgets import QVBoxLayout, QWidget  # noqa: E402
from pyvistaqt import QtInteractor  # noqa: E402

from easyfoam.casegen.mesh import auto_location_in_mesh, location_in_mesh, uses_snappy  # noqa: E402
from easyfoam.model import FACES, Project, Shape  # noqa: E402
from easyfoam.results import CaseData  # noqa: E402

PATCH_COLOURS = ["#4c78a8", "#f58518", "#54a24b", "#b279a2", "#e45756", "#72b7b2", "#9d755d", "#eeca3b"]
SOLID = "#c8b99a"
REGION = "#4c78a8"
OPEN_TYPES = ("patch", "symmetry", "symmetryPlane", "empty")
AXIS = {"x": 0, "y": 1, "z": 2}


def shape_surface(shape: Shape, case_dir: Path):
    """A PyVista surface for a shape, or ``None`` when its STL file is missing."""
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plotter)
        self.plotter.set_background("#f4f6f8", top="#cfd9e3")
        self.plotter.add_axes()
        self._scene: str | None = None  # what is shown; the camera is kept while it stays the same

    # -- helpers
    def _begin(self, scene: str) -> bool:
        """Clear the view; returns True when the camera should be reset afterwards."""
        fresh = scene != self._scene
        self._scene = scene
        self.plotter.clear()
        return fresh

    def _end(self, fresh: bool) -> None:
        if fresh:
            self.plotter.reset_camera()
            self.plotter.view_isometric()
        self.plotter.render()

    def show_message(self, text: str) -> None:
        self._begin("message:" + text)
        self.plotter.add_text(text, position="upper_left", font_size=11, color="#44505c")
        self.plotter.render()

    def close_view(self) -> None:
        self.plotter.close()

    def screenshot(self):
        return self.plotter.screenshot(return_img=True)

    # -- scenes
    def show_geometry(self, project: Project, case_dir: Path) -> None:
        fresh = self._begin("geometry")
        base = project.mesh.base
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
            if shape.role == "refinement":
                self.plotter.add_mesh(surface, color=REGION, opacity=0.18, reset_camera=False)
                self.plotter.add_mesh(surface, style="wireframe", color=REGION, opacity=0.5, reset_camera=False)
            else:
                self.plotter.add_mesh(surface, color=SOLID, smooth_shading=True, reset_camera=False)
        if uses_snappy(project):
            try:
                point = location_in_mesh(project, case_dir)
            except (ValueError, OSError):
                point = auto_location_in_mesh(base)
            size = 0.012 * math.dist(base.min, base.max)
            self.plotter.add_mesh(pv.Sphere(radius=size, center=point), color="#e45756", reset_camera=False)
        if missing:
            self.plotter.add_text("Missing STL: " + ", ".join(missing), font_size=10, color="#b33")
        self._end(fresh)

    def _add_patches(self, data: CaseData, patch_types: Mapping[str, str], field: str | None, edges: bool):
        for index, (name, surface) in enumerate(data.patches.items()):
            if surface is None or surface.n_cells == 0:
                continue
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
        if mode == "surface":
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
