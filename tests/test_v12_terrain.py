"""v0.12: ground surfaces from survey files (XYZ, ESRI ASCII grid, GeoTIFF, LandXML) closed into a solid."""

import math

import numpy as np
import pytest

from easyfoam import terrain as tr
from easyfoam.model import Project

X0, Y0 = 512_340.0, 4_181_270.0  # survey coordinates the size of UTM ones


def plane(x, y):
    """A valley side falling to the east and to the north: 100 m, minus 2 % in x and 1 % in y."""
    return 100.0 - 0.02 * (x - X0) - 0.01 * (y - Y0)


def write_asc(path, nx=21, ny=11, size=2.0, centre=False, hole=None):
    xs = X0 + size * np.arange(nx)
    ys = Y0 + size * np.arange(ny)[::-1]  # the first row is the northernmost
    z = plane(*np.meshgrid(xs, ys))
    if hole:
        z[hole] = -9999
    corner = ("xllcenter", X0, "yllcenter", Y0) if centre else ("xllcorner", X0 - size / 2, "yllcorner", Y0 - size / 2)
    header = (f"ncols {nx}\nnrows {ny}\n{corner[0]} {corner[1]}\n{corner[2]} {corner[3]}\ncellsize {size}\n"
              "NODATA_value -9999\n")  # fmt: skip
    path.write_text(header + "\n".join(" ".join(f"{v:.4f}" for v in row) for row in z) + "\n")
    return path


# --- reading ----------------------------------------------------------------------------------------------------------


def test_xyz_points_are_read_whatever_separates_them(tmp_path):
    path = tmp_path / "survey.xyz"
    path.write_text("easting,northing,level\n1.0, 2.0, 3.0\n4;5;6\n7\t8\t9\nnot a point\n")
    survey = tr.read_survey(path)
    assert survey.kind == "XYZ points" and survey.points.tolist() == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


@pytest.mark.parametrize("centre", [False, True])
def test_an_ascii_grid_is_placed_by_its_header_and_its_holes_are_left_out(tmp_path, centre):
    survey = tr.read_survey(write_asc(tmp_path / "dem.asc", centre=centre, hole=(0, 0)))
    x, y, z = survey.grid
    assert x[0] == pytest.approx(X0) and y[0] == pytest.approx(Y0) and y[-1] == pytest.approx(Y0 + 20)
    assert np.isnan(z[-1, 0])  # the north-west corner had no data
    assert len(survey.points) == 21 * 11 - 1
    assert survey.points[:, 2] == pytest.approx(plane(survey.points[:, 0], survey.points[:, 1]), abs=1e-3)
    assert survey.spacing() == pytest.approx(2.0)


def test_a_geotiff_is_placed_by_its_pixel_scale_and_tie_point(tmp_path):
    from PIL import Image

    size, nx, ny = 2.0, 15, 9
    xs = X0 + size * (np.arange(nx) + 0.5)  # pixel centres: the tie point is the corner of the first pixel
    ys = Y0 - size * (np.arange(ny) + 0.5)
    z = plane(*np.meshgrid(xs, ys)).astype(np.float32)
    z[2, 3] = -9999
    path = tmp_path / "dem.tif"
    Image.fromarray(z, mode="F").save(path, tiffinfo={33550: (size, size, 0.0), 33922: (0.0, 0.0, 0.0, X0, Y0, 0.0),
                                                      42113: "-9999"})  # fmt: skip
    survey = tr.read_survey(path)
    assert survey.kind == "GeoTIFF" and len(survey.points) == nx * ny - 1
    assert survey.points[:, 2] == pytest.approx(plane(survey.points[:, 0], survey.points[:, 1]), abs=1e-3)
    gx, gy, _ = survey.grid
    assert gx[0] == pytest.approx(X0 + 1) and gy[-1] == pytest.approx(Y0 - 1)  # rows run north to south


def test_a_landxml_tin_gives_points_and_triangles(tmp_path):
    corners = [(X0, Y0), (X0 + 40, Y0), (X0 + 40, Y0 + 20), (X0, Y0 + 20), (X0 + 20, Y0 + 10)]
    points = "".join(f'<P id="{k + 1}">{y} {x} {plane(x, y)}</P>' for k, (x, y) in enumerate(corners))
    faces = "<F>1 2 5</F><F>2 3 5</F><F>3 4 5</F><F>4 1 5</F><F i=\"1\">1 2 3</F>"
    path = tmp_path / "surface.xml"
    path.write_text('<?xml version="1.0"?><LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2"><Surfaces>'
                    f'<Surface name="ground"><Definition surfType="TIN"><Pnts>{points}</Pnts><Faces>{faces}</Faces>'
                    "</Definition></Surface></Surfaces></LandXML>")  # fmt: skip
    survey = tr.read_survey(path)
    assert survey.kind == "LandXML" and survey.points[1].tolist() == [X0 + 40, Y0, plane(X0 + 40, Y0)]
    assert survey.triangles.tolist() == [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]]  # the hidden face is left out


def test_files_of_other_kinds_are_refused_with_the_kinds_that_work(tmp_path):
    with pytest.raises(ValueError, match=r"\.asc"):
        tr.read_survey(tmp_path / "ground.dwg")


# --- the ground on a grid -----------------------------------------------------------------------------------------------


def test_the_ground_is_resampled_in_small_local_coordinates(tmp_path):
    survey = tr.read_survey(write_asc(tmp_path / "dem.asc"))
    origin = tr.default_origin(survey)
    assert origin == (512_300.0, 4_181_200.0)  # a round number near the south-west corner
    g = tr.ground(survey, 1.0, origin)
    assert g.x[0] == pytest.approx(40.0) and g.x[-1] == pytest.approx(80.0) and g.spacing == pytest.approx(1.0)
    qx, qy = np.meshgrid(g.x + origin[0], g.y + origin[1])
    assert g.z == pytest.approx(plane(qx, qy), abs=1e-6)  # a plane is interpolated exactly


def test_scattered_points_are_triangulated_and_holes_filled(tmp_path):
    rng = np.random.default_rng(1)
    xy = np.column_stack([X0 + 60 * rng.random(400), Y0 + 30 * rng.random(400)])
    survey = tr.Survey(np.column_stack([xy, plane(xy[:, 0], xy[:, 1])]))
    g = tr.ground(survey, 2.0, (X0, Y0), region=(5, 5, 55, 25))
    qx, qy = np.meshgrid(g.x + X0, g.y + Y0)
    assert np.all(np.isfinite(g.z)) and g.z == pytest.approx(plane(qx, qy), abs=1e-6)


def test_the_survey_can_be_turned_so_the_river_runs_along_x(tmp_path):
    # a valley falling along a direction 30 degrees north of east
    a = math.radians(30)
    xy = np.array([[X0 + i * 2.0, Y0 + j * 2.0] for i in range(40) for j in range(40)])
    along = (xy[:, 0] - X0) * math.cos(a) + (xy[:, 1] - Y0) * math.sin(a)
    survey = tr.Survey(np.column_stack([xy, 50 - 0.05 * along]))
    g = tr.ground(survey, 1.0, (X0, Y0), angle=30, region=(20, -5, 40, 5))
    assert np.allclose(g.z, (50 - 0.05 * g.x)[None, :], atol=1e-6)  # only x matters now
    back = tr.from_local(tr.to_local(xy[:3], (X0, Y0), 30), (X0, Y0), 30)
    assert back == pytest.approx(xy[:3])


# --- the solid -------------------------------------------------------------------------------------------------------


def edges_of(triangles):
    pairs = {}
    for tri in np.round(triangles, 9):
        for k in range(3):
            a, b = tuple(tri[k]), tuple(tri[(k + 1) % 3])
            pairs[(a, b)] = pairs.get((a, b), 0) + 1
    return pairs


def test_the_solid_is_closed_faces_outwards_and_holds_the_volume_under_the_ground(tmp_path):
    g = tr.Ground(np.linspace(0, 10, 6), np.linspace(0, 4, 3), np.zeros((3, 6)))
    g.z[:] = 5.0 + 0.1 * g.x[None, :]  # a gentle slope
    triangles = tr.solid(g, base=0.0)
    pairs = edges_of(triangles)
    # closed and consistently wound: every edge is walked once each way
    assert all(pairs.get((b, a)) == 1 for (a, b), count in pairs.items() if count == 1)
    assert all(count == 1 for count in pairs.values())
    volume = sum(np.dot(t[0], np.cross(t[1], t[2])) for t in triangles) / 6.0
    assert volume == pytest.approx(10 * 4 * (5.0 + 0.5))  # the mean height times the area
    with pytest.raises(ValueError, match="below the lowest ground"):
        tr.solid(g, base=5.2)


def test_the_solid_is_written_as_a_binary_stl(tmp_path):
    from easyfoam.geometry import stl_triangles

    g = tr.Ground(np.linspace(0, 4, 3), np.linspace(0, 2, 2), np.ones((2, 3)))
    triangles = tr.solid(g, base=-1.0)
    path = tr.write_stl(tmp_path / "ground.stl", triangles)
    assert stl_triangles(path) == pytest.approx(triangles.astype(np.float32))


# --- in a project ------------------------------------------------------------------------------------------------------


def test_the_ground_is_set_up_for_a_free_surface_run_above_it(tmp_path):
    survey = tr.read_survey(write_asc(tmp_path / "dem.asc"))
    g = tr.ground(survey, 1.0, (X0, Y0))
    p = Project(name="reach")
    done = tr.use_terrain(p, tmp_path / "case", g, cell_size=0.5, water_level=99.8, discharge=2.0)
    assert (tmp_path / "case" / "constant" / "triSurface" / "terrain.stl").is_file()
    shape = next(s for s in p.shapes if s.name == "terrain")
    assert shape.kind == "stl" and p.mesh.snappy and p.physics.solver == "interFoam"
    base = p.mesh.base
    # the base mesh stops just inside the ground's edges and its top is above the highest ground
    assert g.x[0] < base.min[0] < base.max[0] < g.x[-1] and base.max[2] > g.z.max()
    assert base.min[2] < g.z.min()
    point = p.mesh.location_in_mesh
    assert point[2] > g.z.max()  # the fluid is above the ground
    assert p.physics.water_regions[0][5] == 99.8 and p.boundaries["outlet"].level == 99.8
    assert p.boundaries["inlet"].flow_rate == 2.0 and p.boundaries["sides"].kind == "slip"
    assert "water fills" in " ".join(done)
