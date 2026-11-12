"""v0.8: shapes that are drawn (cone, wedge, sketched outline) next to imported and built-in ones."""

import math

import numpy as np
import pytest

from easyfoam import casegen, geometry
from easyfoam.casegen.mesh import mesh_steps, predicted_patches, snappy_dict
from easyfoam.checks import project_issues
from easyfoam.foam.dictfmt import Q
from easyfoam.model import Project, Shape


def volume_of(triangles: np.ndarray) -> float:
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


L_SHAPE = [[0, 0], [2, 0], [2, 1], [1, 1], [1, 3], [0, 3]]  # area 4, not convex


# --- surfaces of the drawn shapes -------------------------------------------------


def test_a_cone_is_a_closed_solid_of_the_right_volume():
    cone = Shape("c", kind="cone", point1=[0, 0, 0], point2=[0, 0, 2], radius=1.0, radius2=0.5)
    triangles = geometry.triangulate(cone)
    assert geometry._open_edges(triangles) == 0
    exact = math.pi * 2 / 3 * (1 + 0.5 + 0.25)
    assert volume_of(triangles) == pytest.approx(exact, rel=0.01)  # positive: the triangles face outwards
    lo, hi = geometry.shape_bounds(cone, None)
    assert lo == pytest.approx([-1, -1, 0], abs=1e-9) and hi == pytest.approx([1, 1, 2], abs=1e-9)


def test_a_cone_may_end_in_a_point_and_lie_along_any_axis():
    cone = Shape("c", kind="cone", point1=[1, 1, 1], point2=[3, 1, 1], radius=0.5, radius2=0.0)
    triangles = geometry.triangulate(cone)
    assert geometry._open_edges(triangles) == 0
    assert volume_of(triangles) == pytest.approx(math.pi * 0.25 * 2 / 3, rel=0.01)
    assert triangles.reshape(-1, 3)[:, 0].max() == pytest.approx(3.0)


def test_a_wedge_is_half_its_box_and_rises_the_way_it_is_told():
    wedge = Shape("w", kind="wedge", min=[0, 0, 0], max=[4, 1, 2], rise="+x")
    triangles = geometry.triangulate(wedge)
    assert geometry._open_edges(triangles) == 0 and volume_of(triangles) == pytest.approx(4.0)
    points = triangles.reshape(-1, 3)
    assert points[points[:, 0] < 0.01][:, 2].max() == pytest.approx(0.0)  # no height at the low end
    assert points[points[:, 0] > 3.99][:, 2].max() == pytest.approx(2.0)  # full height at the high end
    other = geometry.triangulate(Shape("w", kind="wedge", min=[0, 0, 0], max=[4, 1, 2], rise="-y")).reshape(-1, 3)
    assert other[other[:, 1] > 0.99][:, 2].max() == pytest.approx(0.0)
    assert other[other[:, 1] < 0.01][:, 2].max() == pytest.approx(2.0)


@pytest.mark.parametrize("points", [L_SHAPE, L_SHAPE[::-1]])  # drawn either way round
def test_a_sketched_outline_is_extruded_into_a_closed_solid(points):
    shape = Shape("p", kind="profile", points=points, plane="xz", extent=[-0.5, 1.5])
    triangles = geometry.triangulate(shape)
    assert geometry._open_edges(triangles) == 0
    assert volume_of(triangles) == pytest.approx(4.0 * 2.0)
    lo, hi = geometry.shape_bounds(shape, None)
    assert lo == pytest.approx([0, -0.5, 0]) and hi == pytest.approx([2, 1.5, 3])  # drawn in x-z, extruded along y


def test_the_plane_of_a_sketch_decides_which_way_it_is_extruded():
    for plane, lo, hi in (("xy", [0, 0, 5], [2, 3, 6]), ("yz", [5, 0, 0], [6, 2, 3])):
        shape = Shape("p", kind="profile", points=L_SHAPE, plane=plane, extent=[5, 6])
        triangles = geometry.triangulate(shape)
        assert volume_of(triangles) == pytest.approx(4.0)
        assert geometry.shape_bounds(shape, None) == (pytest.approx(lo), pytest.approx(hi))


def test_what_is_wrong_with_a_drawn_shape_is_said_in_words():
    assert geometry.shape_problem(Shape("p", kind="profile", points=L_SHAPE)) is None
    assert "three" in geometry.shape_problem(Shape("p", kind="profile", points=[[0, 0], [1, 1]]))
    bow_tie = [[0, 0], [1, 1], [1, 0], [0, 1]]
    assert "cross" in geometry.shape_problem(Shape("p", kind="profile", points=bow_tie))
    assert "length" in geometry.shape_problem(Shape("p", kind="profile", points=L_SHAPE, extent=[1, 1]))
    assert "length" in geometry.shape_problem(Shape("c", kind="cone", point1=[0, 0, 0], point2=[0, 0, 0]))
    assert "radius" in geometry.shape_problem(Shape("c", kind="cone", radius=0.0, radius2=0.0))
    assert "size" in geometry.shape_problem(Shape("w", kind="wedge", min=[0, 0, 0], max=[1, 0, 1]))
    assert geometry.shape_problem(Shape("b", kind="box")) is None


def test_mass_and_centre_of_a_drawn_shape_need_no_file():
    wedge = Shape("w", kind="wedge", min=[0, 0, 0], max=[3, 1, 2], rise="+x")
    mass, centre, _inertia = geometry.mass_properties(wedge, None, 1000.0)
    assert mass == pytest.approx(3000.0)
    assert centre == pytest.approx([2.0, 0.5, 2.0 / 3.0])  # a third of the way from the high end


# --- from shape to mesh -----------------------------------------------------------


def tunnel(*shapes):
    p = Project(name="tunnel")
    p.shapes.extend(shapes)
    return p


def test_a_drawn_shape_reaches_the_mesher_as_a_surface_file_written_with_the_case():
    ramp = Shape("ramp", kind="wedge", min=[0, -1, -1], max=[1, 1, 0.5])
    p = tunnel(ramp)
    assert snappy_dict(p)["geometry"]["ramp"] == {"type": "triSurfaceMesh", "file": Q("ramp.stl")}
    files = casegen.mesh_files(p)
    assert files["constant/triSurface/ramp.stl"].startswith("solid ramp")
    assert "ramp.stl" in files["system/surfaceFeatureExtractDict"]
    assert [s.name for s in mesh_steps(p)] == ["blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "checkMesh"]
    assert "ramp" in [patch.name for patch in predicted_patches(p)]


def test_built_in_shapes_still_need_no_file():
    p = tunnel(Shape("ball", kind="sphere"))
    assert not [name for name in casegen.mesh_files(p) if name.endswith(".stl")]
    assert snappy_dict(p)["geometry"]["ball"]["type"] == "sphere"


def test_the_fluid_can_be_inside_a_drawn_shape():
    duct = Shape("duct", kind="profile", points=[[0, 0], [0.2, 0], [0.2, 0.1], [0, 0.1]], plane="yz", extent=[-1, 3])
    p = tunnel(duct)
    p.mesh.base.min, p.mesh.base.max = [0, -0.05, -0.05], [2, 0.25, 0.15]
    p.mesh.fluid_inside = "duct"
    x, y, z = snappy_dict(p)["castellatedMeshControls"]["locationInMesh"]
    assert 0 < x < 2 and 0 < y < 0.2 and 0 < z < 0.1


def test_a_broken_sketch_stops_the_mesh_with_a_clear_message():
    p = tunnel(Shape("weir", kind="profile", points=[[0, 0], [1, 1], [1, 0], [0, 1]]))
    errors = [i.text for i in project_issues(p, predicted_patches(p), False) if i.level == "error"]
    assert any("weir" in text and "cross" in text for text in errors)


def test_drawn_shapes_are_saved_with_the_project(tmp_path):
    p = tunnel(
        Shape("c", kind="cone", radius2=0.1),
        Shape("w", kind="wedge", rise="-y"),
        Shape("p", kind="profile", points=L_SHAPE, plane="xy", extent=[2.0, 3.0]),
    )
    p.save(tmp_path)
    assert Project.load(tmp_path).shapes == p.shapes


# --- where a new shape appears ------------------------------------------------------


@pytest.mark.parametrize("kind", ["box", "sphere", "cylinder", "cone", "wedge", "profile"])
def test_a_new_shape_appears_inside_the_base_mesh_at_a_sensible_size(kind):
    p = Project(name="x")
    p.mesh.base.min, p.mesh.base.max = [10, 0, 0], [16, 0.5, 1.5]
    shape = geometry.new_shape(kind, "s1", p)
    assert shape.kind == kind and geometry.shape_problem(shape) is None
    lo, hi = geometry.shape_bounds(shape, None)
    assert 10 < lo[0] < hi[0] < 16  # inside along the length of the channel
    assert max(h - low for low, h in zip(lo, hi)) <= 6 / 2
    if kind == "profile":
        assert lo[1] < 0 and hi[1] > 0.5  # an outline is extruded right through the side walls
