"""v0.12: open channels built in the program (sections, slope, bends), meshed by blockMesh alone."""

import math

import numpy as np
import pytest

from easyfoam import channel as chm
from easyfoam.model import Channel, ChannelSegment, Project


def bent(**changes):
    """A trapezoidal channel: 10 m straight, a 90 degree bend to the left, 5 m straight."""
    segments = [ChannelSegment("straight", length=10), ChannelSegment("bend", radius=10, angle=90),
                ChannelSegment("straight", length=5)]  # fmt: skip
    values = {"section": "trapezoidal", "bottom_width": 2.0, "depth": 1.0, "side_slope": 1.5, "slope": 0.001,
              "segments": segments, "freeboard": 0.3, "cell_size": 0.25, "water_depth": 0.6}  # fmt: skip
    values.update(changes)
    return Channel(**values)


def hex_volume(points):
    """Volume of a blockMesh hexahedron from its eight corners (positive when the block is right-handed)."""
    faces = [chm.SIDE_FACES[s] for s in ("right", "left", "bottom", "top")] + [(0, 3, 2, 1), (4, 5, 6, 7)]
    volume = 0.0
    for a, b, c, d in faces:  # split each face into two triangles; divergence theorem with outward normals
        for p, q, r in ((points[a], points[b], points[c]), (points[a], points[c], points[d])):
            volume += np.dot(p, np.cross(q, r)) / 6.0
    return volume


def blocks_of(blocks):
    """(vertices, cells) of each block in a flat blockMesh token list."""
    out, i = [], 0
    while i < len(blocks):
        assert blocks[i] == "hex"
        ids = blocks[i + 1]
        i += 2
        if isinstance(blocks[i], str):  # a cell zone
            i += 1
        out.append((ids, blocks[i]))
        i += 3  # cells, "simpleGrading", grading
    return out


# --- the centreline ---------------------------------------------------------------------------------------


def test_the_centreline_runs_straight_then_bends_and_the_bed_falls_to_zero_at_the_outlet():
    ch = bent()
    ends = chm.stations(ch)
    length = 10 + 10 * math.pi / 2 + 5
    assert chm.total_length(ch) == pytest.approx(length)
    assert (ends[1].x, ends[1].y) == pytest.approx((10, 0))
    assert (ends[2].x, ends[2].y, ends[2].heading) == pytest.approx((20, 10, math.pi / 2))  # a quarter turn left
    assert (ends[3].x, ends[3].y) == pytest.approx((20, 15))
    assert ends[0].bed == pytest.approx(0.001 * length) and ends[-1].bed == pytest.approx(0.0)
    right = chm.stations(bent(segments=[ChannelSegment("bend", radius=10, angle=-90)]))
    assert (right[1].x, right[1].y) == pytest.approx((10, -10))  # negative angles turn right
    line = chm.centreline_points(ch)
    assert np.allclose(line[0], [0, 0]) and np.allclose(line[-1], [20, 15])
    assert np.linalg.norm(np.diff(line, axis=0), axis=1).sum() == pytest.approx(length, rel=1e-3)


# --- the cross-section -------------------------------------------------------------------------------------


def test_a_trapezoid_is_split_at_the_initial_water_depth():
    sec = chm.section(bent())
    assert len(sec.quads) == 2 and sec.height == pytest.approx(1.3)
    low, high = sec.quads
    assert low.zone == chm.WATER_ZONE and high.zone == ""
    assert low.sides == {"right": "banks", "left": "banks", "bottom": "bed"}
    assert high.sides == {"right": "banks", "left": "banks", "top": "atmosphere"}
    corners = np.array([sec.points[i] for i in low.corners])
    assert np.allclose(corners, [(-1, 0), (1, 0), (1.9, 0.6), (-1.9, 0.6)])  # anticlockwise from the right bank
    assert low.across == high.across  # the blocks share a side: the same cells along it
    assert (low.up, high.up) == (3, 3)  # 0.6 m and 0.7 m in 0.25 m cells
    assert sec.half_width == pytest.approx(1 + 1.5 * 1.3)
    dry = chm.section(bent(water_depth=0))
    assert len(dry.quads) == 1 and dry.quads[0].zone == ""


def test_a_compound_section_has_floodplains_and_shares_its_corners():
    ch = bent(section="compound", berm_width=3.0, berm_depth=0.5, berm_slope=2.0, water_depth=1.2)
    sec = chm.section(ch)
    assert sec.height == pytest.approx(1.8)
    # the main channel up to the floodplains, then middle, left and right blocks below and above the water level
    assert len(sec.quads) == 1 + 3 * 2
    assert sum(q.sides.get("bottom") == "floodplain" for q in sec.quads) == 2
    assert all(q.zone == chm.WATER_ZONE for q in sec.quads[:4]) and all(not q.zone for q in sec.quads[4:])
    assert len(sec.points) == len(set(sec.points))  # each corner once: neighbouring blocks share it
    names = {name for q in sec.quads for name in q.sides.values()}
    assert names == {"bed", "banks", "floodplain", "atmosphere"}


def test_a_circular_culvert_is_an_o_grid_with_its_barrel_on_arcs():
    ch = bent(section="circular", diameter=1.2, segments=[ChannelSegment("straight", length=8)], water_depth=0.5)
    sec = chm.section(ch)
    assert len(sec.quads) == 5 and sum(len(q.arcs) for q in sec.quads) == 4
    assert all(q.sides == {side: "barrel" for side in q.arcs} for q in sec.quads)
    assert sec.height == pytest.approx(1.2) and sec.half_width == pytest.approx(0.6)
    regions = chm.water_regions(ch)  # the O-grid does not split at the water: a box tilted with the bed
    assert len(regions) == 1 and regions[0].name == "rotatedBoxToCell"
    box = regions[0].body
    assert box["k"] == pytest.approx([0, 0, 0.25 + 1.2 + 0.5])
    assert box["i"][2] == pytest.approx(-0.001 * 8 * (8 + 0.5) / 8)  # down the slope of the bed
    assert "a circular culvert is built straight" in " ".join(chm.problems(bent(section="circular")))


# --- blockMesh ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("section", ["rectangular", "trapezoidal", "compound", "circular"])
def test_every_block_is_right_handed_and_the_cells_match_across_shared_sides(section):
    segments = None if section != "circular" else [ChannelSegment("straight", length=6)]
    ch = bent(section=section, **({"segments": segments} if segments else {}))
    d = chm.block_mesh_dict(ch)
    sec, ends = chm.section(ch), chm.stations(ch)
    vertices = np.asarray(d["vertices"], float)
    assert len(vertices) == len(sec.points) * len(ends)
    found = blocks_of(d["blocks"])
    assert len(found) == len(sec.quads) * len(ch.segments)
    assert all(hex_volume(vertices[ids]) > 0 for ids, _cells in found)
    total = sum(np.prod(cells) for _ids, cells in found)
    assert total == chm.cell_count(ch)
    names = [b.name for b in d["boundary"]]
    assert names[:2] == ["inlet", "outlet"] and {p.name for p in chm.patches(ch)} == set(names)
    inlet = next(b for b in d["boundary"] if b.name == "inlet").body
    assert len(inlet["faces"]) == len(sec.quads) and inlet["type"] == "patch"


def test_bends_are_drawn_with_arcs_and_the_bed_slopes_through_them():
    ch = bent()
    d = chm.block_mesh_dict(ch)
    arcs = [d["edges"][i:i + 4] for i in range(0, len(d["edges"]), 4)]
    points = len(chm.section(ch).points)
    assert len(arcs) == points and all(a[0] == "arc" for a in arcs)  # one per corner, on the bend only
    _kind, start, end, middle = arcs[0]
    vertices = np.asarray(d["vertices"])
    radius = np.hypot(*(vertices[start][:2] - [10, 10]))
    assert np.hypot(middle[0] - 10, middle[1] - 10) == pytest.approx(radius)  # on the circle round the centre
    assert middle[2] == pytest.approx((vertices[start][2] + vertices[end][2]) / 2)


def test_problems_are_explained_before_anything_is_built():
    assert chm.problems(bent()) == []
    assert "half the channel's width" in " ".join(chm.problems(bent(segments=[ChannelSegment("bend", radius=2)])))
    assert "initial water depth" in " ".join(chm.problems(bent(water_depth=2.0)))
    assert "half a cell" in " ".join(chm.problems(bent(water_depth=0.05)))
    assert "bottom width" in " ".join(chm.problems(bent(bottom_width=0)))
    with pytest.raises(ValueError, match="cannot be built"):
        chm.block_mesh_dict(bent(segments=[]))


# --- the channel in a project ---------------------------------------------------------------------------------


def channel_project(**changes):
    p = Project(name="river")
    p.channel = bent(**changes)
    p.physics.solver = "interFoam"
    return p


def test_a_channel_replaces_the_base_mesh_in_the_case():
    from easyfoam.casegen.mesh import block_mesh_dict, location_in_mesh, predicted_patches
    from easyfoam.casegen.setup import set_fields_dict

    p = channel_project()
    assert block_mesh_dict(p)["vertices"] == chm.block_mesh_dict(p.channel)["vertices"]
    assert [(x.name, x.type) for x in predicted_patches(p)] == [
        ("inlet", "patch"), ("outlet", "patch"), ("bed", "wall"), ("banks", "wall"), ("atmosphere", "patch"),
    ]  # fmt: skip
    regions = set_fields_dict(p)["regions"]
    assert [r.name for r in regions] == ["zoneToCell"] and regions[0].body["zones"] == ["water"]
    point = location_in_mesh(p)
    low, high = chm.bounds(p.channel)
    assert all(lo < c < hi for c, lo, hi in zip(point, low, high))


def test_the_long_section_follows_the_channel_round_its_bends():
    from easyfoam.hydraulics import default_centreline

    p = channel_project()
    line = default_centreline(p)
    assert line.length == pytest.approx(chm.total_length(p.channel), rel=1e-3)
    assert line.half_width == pytest.approx(chm.section(p.channel).half_width)
    position, tangent = line.at(np.array([line.length - 1.0]))
    assert position[0] == pytest.approx([20, 14], abs=1e-6) and tangent[0] == pytest.approx([0, 1])


def test_the_bounds_hold_every_corner_and_the_preview_has_each_boundary():
    ch = bent()
    low, high = chm.bounds(ch)
    vertices = np.asarray(chm.block_mesh_dict(ch)["vertices"])
    assert np.all(vertices >= np.asarray(low) - 1e-6) and np.all(vertices <= np.asarray(high) + 1e-6)
    shapes = chm.preview(ch)
    assert set(shapes) == {"bed", "banks", "atmosphere", "inlet", "outlet"}
    points, quads = shapes["bed"]
    assert quads.shape[1] == 4 and quads.max() < len(points)


def test_a_built_channel_gets_times_for_a_transient_run_unless_it_has_them():
    p = Project(name="river")
    done = chm.use_channel(p, bent(cell_size=0.1))
    run = p.run
    # a steady project counts iterations with a time step of 1: that would wreck the water in the first step
    assert run.delta_t == pytest.approx(0.001) and run.adjust_time_step and run.max_courant <= 0.8
    assert run.end_time == pytest.approx(chm._nice(2 * chm.total_length(p.channel) / (p.boundaries["inlet"].flow_rate
                                                   / chm.wetted(p.channel, 0.6)[0])))  # fmt: skip
    assert run.write_interval == pytest.approx(run.end_time / 10) and "the run lasts" in " ".join(done)
    run.end_time, run.delta_t = 30.0, 0.0005  # chosen by hand: kept
    chm.use_channel(p, bent(cell_size=0.1))
    assert (run.end_time, run.delta_t) == (30.0, 0.0005)
    assert [chm._nice(v) for v in (0.0013, 0.03, 70, 460)] == pytest.approx([0.001, 0.02, 50, 500])


def test_the_channel_and_the_ground_can_be_built_from_the_command_line(tmp_path, capsys):
    from easyfoam.cli import main
    from tests.test_v12_terrain import write_asc

    Project(name="river").save(tmp_path / "river")
    assert main(["channel", str(tmp_path / "river"), "--section", "rectangular", "--width", "1.5", "--depth", "0.6",
                 "--piece", "straight:8", "--piece", "bend:6:-45", "--water", "0.3", "--cell", "0.1",
                 "--discharge", "0.4"]) == 0  # fmt: skip
    p = Project.load(tmp_path / "river")
    assert p.channel.section == "rectangular" and [s.kind for s in p.channel.segments] == ["straight", "bend"]
    assert p.channel.segments[1].angle == -45 and p.boundaries["inlet"].flow_rate == 0.4
    assert "Built a rectangular channel" in capsys.readouterr().out
    assert main(["channel", str(tmp_path / "river"), "--piece", "loop:3"]) != 0  # explained, not a crash

    Project(name="reach").save(tmp_path / "reach")
    survey = write_asc(tmp_path / "dem.asc")
    assert main(["terrain", str(tmp_path / "reach"), str(survey), "--cell", "0.5", "--water", "99.8"]) == 0
    p = Project.load(tmp_path / "reach")
    assert [s.name for s in p.shapes] == ["terrain"] and p.physics.water_regions[0][5] == 99.8
    assert "local origin E 512300, N 4181200" in capsys.readouterr().out


def test_a_built_channel_counts_as_water_at_the_start_in_the_checklist():
    from easyfoam.casegen.mesh import predicted_patches
    from easyfoam.checks import project_issues
    from easyfoam.model import Boundary

    p = Project(name="river")
    chm.use_channel(p, bent())
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[0.5, 0, 0], water_fraction=0.0)
    said = " ".join(issue.text for issue in project_issues(p, predicted_patches(p), has_mesh=False))
    assert "There is no water yet" not in said and "Nothing drives the flow" not in said
