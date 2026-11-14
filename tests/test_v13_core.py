"""v0.13: hydraulic structures made from their design values."""

import math

import numpy as np
import pytest

from easyfoam import casegen, drawn, geometry
from easyfoam import structures as sm
from easyfoam.casegen.mesh import predicted_patches, uses_snappy
from easyfoam.examples import weir
from easyfoam.model import Project, Shape, Structure

BOX = ([0.0, 0.0, 0.0], [6.0, 0.5, 1.5])  # the weir example's base mesh

VARIANTS = [
    ("ogee", {}), ("ogee", {"toe_radius": 0}), ("ogee", {"height": 0.05}),
    ("stepped", {}), ("stepped", {"step_height": 0.2}),
    ("labyrinth", {}), ("labyrinth", {"cycles": 1, "angle": 30}),
    ("basin", {"basin_type": 2, "froude": 9}), ("basin", {}), ("basin", {"basin_type": 4, "froude": 3.5}),
    ("culvert", {}), ("culvert", {"count": 3, "span": 0.1, "invert": -0.03}), ("culvert", {"invert": 0.03}),
    ("culvert", {"circular": 1}), ("culvert", {"circular": 1, "span": 0.15, "count": 2, "invert": -0.02}),
    ("fishway", {}), ("fishway", {"pools": 1}),
]  # fmt: skip


def make(kind: str, **values) -> Structure:
    st = sm.place(kind, *BOX)
    st.values.update(values)
    return st


def directed_edges_pair_up(triangles: np.ndarray) -> bool:
    """Each edge is walked once in each direction: the surface is closed and turned consistently."""
    scale = float(np.ptp(triangles.reshape(-1, 3), axis=0).max())
    keys = np.round(triangles.reshape(-1, 3) / (scale * 1e-7)).astype(np.int64)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    ids = ids.reshape(-1, 3)
    edges = [tuple(e) for e in np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]])]
    walked = set(edges)
    return len(walked) == len(edges) and all((b, a) in walked for a, b in walked)


def volume(triangles: np.ndarray) -> float:
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)


@pytest.mark.parametrize(("kind", "values"), VARIANTS)
def test_every_structure_is_made_of_closed_surfaces_facing_outwards(kind, values):
    st = make(kind, **values)
    assert sm.problems(st) == []
    built = sm.build(st)
    assert built.bodies and built.side and built.plan and built.info
    for body in built.bodies:
        assert geometry._open_edges(body) == 0
        assert directed_edges_pair_up(body)
        assert volume(body) > 0  # outward: snappyHexMesh and the viewer agree on the solid side
    shape = Shape("s", kind="structure", structure=st)
    assert drawn.is_drawn(shape) and drawn.problem(shape) is None
    assert len(drawn.triangulate(shape)) == sum(len(b) for b in built.bodies)


def test_the_wes_crest_follows_the_standard_shape():
    points = np.array(sm.wes_crest(1.0, 0.0, 0.0))
    assert points[0] == pytest.approx([-0.2818, -0.136], abs=5e-4)  # where the upstream face begins
    assert points[-1] == pytest.approx([0.0, 0.0], abs=1e-9)  # the apex
    assert np.all(np.diff(points[:, 0]) > 0) and np.all(np.diff(points[:, 1]) > 0)  # rising to the apex
    # three circles of radii 0.5, 0.2 and 0.04 Hd meet at 0.175 and 0.276 Hd upstream of the apex
    near = points[points[:, 0] > -0.175 + 1e-9]
    assert np.hypot(near[:, 0], near[:, 1] + 0.5) == pytest.approx(0.5, abs=1e-9)
    down, short = sm._wes_downstream(1.0, 0.0, 0.0, 0.75, -10.0)
    down = np.array(down)
    assert not short
    assert down[:, 1] == pytest.approx(-(down[:, 0] ** 1.85) / 2.0)  # x^1.85 = 2 Hd^0.85 y
    tangent = (2 / (1.85 * 0.75)) ** (1 / 0.85)
    assert down[-1, 0] == pytest.approx(tangent)  # it ends where it is as steep as the 0.75:1 face
    assert 1.85 * down[-1, 0] ** 0.85 / 2 == pytest.approx(1 / 0.75)


def test_the_ogee_tells_its_design_discharge_and_sits_on_the_bed():
    st = make("ogee", design_head=0.1, height=0.4)
    built = sm.build(st)
    q = 2.18 * st.width * 0.1**1.5
    assert f"{q:.4g} m³/s" in built.info[0]
    assert "P/Hd = 4.00" in built.info[1]
    side = np.array(built.side[0])
    assert side[:, 1].max() == pytest.approx(st.bed + 0.4)  # the crest is P above the bed
    assert side[0, 0] == pytest.approx(st.station) and side[:, 0].min() == pytest.approx(st.station, abs=1e-12)
    assert side[:, 1].min() < st.bed  # it reaches below the bed, so that the mesh is cut cleanly
    tops = drawn.triangulate(Shape("o", kind="structure", structure=st))
    assert tops[..., 1].min() < st.y0 and tops[..., 1].max() > st.y0 + st.width  # and beyond both walls


def test_a_low_ogee_says_the_approach_flow_lowers_its_coefficient():
    assert "below 1.33" in sm.build(make("ogee", design_head=0.1, height=0.1)).info[1]


def test_a_stepped_chute_has_whole_steps_and_its_flow_regime():
    st = make("stepped", design_head=0.08, height=1.0, face_slope=0.8, step_height=0.06)
    built = sm.build(st)
    side = np.array(built.side[0])
    vertical = np.isclose(np.diff(side[:, 0]), 0) & (np.diff(side[:, 1]) < 0) & (side[1:, 1] >= st.bed - 1e-12)
    risers = np.diff(side[:, 1])[vertical]
    assert len(risers) == int(built.info[0].split()[0])
    assert risers == pytest.approx(risers[0])  # the steps are all the same height ...
    count = int(built.info[0].split()[0])
    assert abs(-risers[0] - 0.06) < 0.06 / count + 1e-9  # ... as close to the wanted height as whole steps allow
    assert "skimming flow" in built.info[1]
    assert "nappe flow" in sm.build(make("stepped", design_head=0.02, step_height=0.2)).info[1]
    with pytest.raises(ValueError, match="too low for steps"):
        sm.build(make("stepped", design_head=0.5, height=0.1))


def test_the_labyrinth_crest_is_folded_into_the_channel():
    st = make("labyrinth", cycles=2, angle=15, apex=0.05, thickness=0.025)
    built = sm.build(st)
    w = st.width / 2
    length = (w / 2 - 0.05) / math.tan(math.radians(15))
    crest = 2 * (2 * 0.05 + 2 * math.hypot(length, w / 2 - 0.05))
    assert f"{crest:.3g} m" in built.info[1] and f"{crest / st.width:.2f} times" in built.info[1]
    plan = np.array(built.plan[0])
    assert plan[:, 0].max() - plan[:, 0].min() == pytest.approx(length + 0.025, rel=0.05)
    assert sm.problems(make("labyrinth", cycles=3, angle=8)) == [
        "the apices take up the whole cycle: use fewer cycles or narrower apices"
    ]
    assert "between 2 and 80 degrees" in sm.problems(make("labyrinth", angle=85))[0]


def test_usbr_basins_follow_engineering_monograph_25():
    y1, froude = 0.03, 6.0
    y2 = 0.5 * y1 * (math.sqrt(1 + 8 * froude**2) - 1)
    two, three, four = (sm.basin_design(y1, froude, k) for k in (2, 3, 4))
    assert three["y2"] == pytest.approx(y2) and three["v1"] == pytest.approx(froude * math.sqrt(9.81 * y1))
    assert two["length"] == pytest.approx(4.3 * y2) and two["sill_h"] == pytest.approx(0.2 * y2)
    assert three["length"] == pytest.approx(2.7 * y2) and three["baffle_x"] == pytest.approx(0.8 * y2)
    assert three["baffle_h"] == pytest.approx(y1 * (0.168 * froude + 0.63))
    assert three["sill_h"] == pytest.approx(y1 * (0.0556 * froude + 1))
    assert four["length"] == pytest.approx(6.1 * y2) and four["tailwater"] == pytest.approx(1.1 * y2)
    assert four["block_h"] == pytest.approx(2 * y1) and four["block_gap"] == pytest.approx(2.5 * y1)
    with pytest.raises(ValueError, match="II, III or IV"):
        sm.basin_design(y1, froude, 1)


def test_a_basin_has_its_blocks_and_sill_and_warns_when_its_type_does_not_suit_the_flow():
    built = sm.build(make("basin", basin_type=3, y1=0.03, froude=6))
    chute, baffles, sill = 8, 6, 1  # in a 0.5 m channel: blocks 3 cm wide and 3 cm apart, baffles staggered
    assert len(built.bodies) == chute + baffles + sill
    assert len(built.info) == 3  # no warning: Type III suits Fr1 = 6
    assert "use Type III" in sm.build(make("basin", basin_type=4, froude=6)).info[-1]
    assert "use Type IV" in sm.build(make("basin", basin_type=3, froude=3.5)).info[-1]
    dentated = sm.build(make("basin", basin_type=2, froude=9))
    assert len(dentated.bodies) > 8 + 1  # the end sill is a row of teeth
    slice_ = make("basin", basin_type=3, froude=6)
    slice_.width = 0.05  # a slice one cell wide holds no blocks: only the end sill
    thin = sm.build(slice_)
    assert len(thin.bodies) == 1 and "no chute blocks" in thin.info[-1]


def test_water_passes_through_the_barrels_of_a_culvert_and_not_through_its_embankment():
    for circular in (0, 1):
        st = make("culvert", circular=circular, span=0.15, count=2, invert=0.03, road=0.4)
        triangles = sm.triangles(st)
        pitch = st.width / 2
        up = st.station - 0.1
        for k in range(2):
            y = st.y0 + pitch * (k + 0.5)
            barrel = np.array([up, y, st.bed + 0.03 + 0.07])
            assert geometry._crossings(barrel, triangles, np.array([1.0, 0, 0])) == 0
            above = np.array([up, y + 0.0123, st.bed + 0.3517])  # off the edges of the triangles
            assert geometry._crossings(above, triangles, np.array([1.0, 0, 0])) == 2


def test_a_buried_barrel_counts_only_its_opening_above_the_bed():
    assert sm._open_area(0.2, 0.15, 0.0, False) == pytest.approx(0.03)
    assert sm._open_area(0.2, 0.15, -0.05, False) == pytest.approx(0.02)
    assert sm._open_area(0.2, 0.2, 0.0, True) == pytest.approx(math.pi * 0.01)
    half = sm._open_area(0.2, 0.2, -0.1, True)  # buried to its axis
    assert half == pytest.approx(math.pi * 0.01 / 2)
    assert "buried 0.02 m in the bed" in sm.build(make("culvert", circular=1, invert=-0.02)).info[0]
    assert sm.problems(make("culvert", rise=0.5, road=0.4)) == ["the barrels must fit below the road"]
    assert sm.problems(make("culvert", span=0.3, count=2)) == ["the barrels do not fit side by side in the channel"]


def test_the_fishway_has_a_slot_through_every_baffle():
    st = make("fishway", pools=3, drop=0.03, wall=0.35)
    b = sm.value(st, "slot")
    assert b == pytest.approx(st.width / 8)  # pools 8 slots wide fill the channel
    triangles = sm.triangles(st)
    high = st.bed + 3 * 0.03 + 0.3
    along = np.array([1.0, 0, 0])
    slot = np.array([st.station - 0.1, st.y0 + st.width - 2.0 * b, high])
    assert geometry._crossings(slot, triangles, along) == 0
    baffle = np.array([st.station - 0.1, st.y0 + 0.2 * st.width, high])
    assert geometry._crossings(baffle, triangles, along) == 2 * 4  # four baffles: three pools
    built = sm.build(st)
    assert f"{math.sqrt(2 * 9.81 * 0.03):.3g} m/s" in built.info[1]
    assert len(built.info) == 2  # the channel is 8 b wide: no advice
    narrow = make("fishway")
    narrow.values["slot"] = 0.04
    assert "Make the channel 0.32 m wide" in sm.build(narrow).info[-1]


def test_design_values_that_are_missing_or_wrong_are_named():
    assert sm.problems(make("ogee", design_head=0)) == ["design head Hd must be above zero"]
    assert sm.problems(Structure(kind="spiral")) == ["unknown structure 'spiral'"]
    assert sm.problems(make("ogee", toe_radius=0)) == []  # a sharp toe is allowed
    st = Structure(kind="culvert", width=0.5)  # values left out take their defaults
    assert sm.value(st, "span") == 0.2 and sm.problems(st) == []
    with pytest.raises(KeyError):
        sm.value(st, "design_head")
    shape = Shape("s", kind="structure")
    assert drawn.problem(shape) == "it has no design values"


def test_a_structure_that_does_not_fit_its_base_mesh_is_pointed_out():
    assert sm.fit_warnings(make("ogee"), *BOX) == []
    narrow = make("ogee")
    narrow.width = 0.4
    assert sm.fit_warnings(narrow, *BOX) == [
        "it spans y = 0 to 0.4 m but the base mesh runs from 0 to 0.5 m: water can pass beside it"
    ]
    raised = make("ogee")
    raised.bed = 0.1
    assert "water can pass under it" in sm.fit_warnings(raised, *BOX)[0]
    assert "higher than the top of the base mesh" in sm.fit_warnings(make("ogee", height=2.0), *BOX)[-1]
    late, early = make("ogee"), make("ogee")
    late.station, early.station = 5.9, 0.0
    assert "past the downstream end" in " ".join(sm.fit_warnings(late, *BOX))
    assert "upstream end" in " ".join(sm.fit_warnings(early, *BOX))


def test_a_new_structure_is_scaled_to_the_base_mesh():
    lab = sm.place("ogee", *BOX)
    assert lab.station == pytest.approx(2.0) and lab.width == 0.5 and lab.bed == 0.0
    assert lab.values["design_head"] == 0.1 and lab.values["height"] == 0.4
    dam = sm.place("ogee", [0, -20, 100], [600, 20, 250])  # 150 m high: a hundred times the laboratory
    assert dam.values["design_head"] == pytest.approx(10.0) and dam.values["height"] == pytest.approx(40.0)
    assert dam.values["face_slope"] == 0.75 and dam.bed == 100 and dam.y0 == -20 and dam.width == 40
    assert sm.place("basin", [0, 0, 0], [60, 10, 15]).values["froude"] == 6.0  # numbers without units stay


def test_a_structure_is_saved_and_loaded_with_its_project(tmp_path):
    p = Project(name="spill")
    p.shapes.append(Shape("ogee1", kind="structure", structure=make("ogee", design_head=0.12)))
    p.save(tmp_path)
    back = Project.load(tmp_path).shapes[0]
    assert back.kind == "structure" and isinstance(back.structure, Structure)
    assert back.structure == p.shapes[0].structure and back.structure.values["design_head"] == 0.12
    assert Project.load(tmp_path).shapes[0].structure.kind == "ogee"


def test_the_examples_bring_a_spillway_crest_and_a_stilling_basin():
    from easyfoam.examples import EXAMPLES

    crest = EXAMPLES["ogee"]("ogee")
    st = crest.shapes[0].structure
    assert sm.problems(st) == [] and st.values["design_head"] == 0.1
    assert crest.boundaries["inlet"].flow_rate == pytest.approx(2.18 * 0.02 * 0.1**1.5, rel=1e-5)  # design discharge
    assert crest.physics.water_regions[0][-1] == pytest.approx(0.5)  # the reservoir starts at the design head
    assert "constant/triSurface/ogee.stl" in casegen.mesh_files(crest)

    basin = EXAMPLES["basin"]("basin")
    st = next(s.structure for s in basin.shapes if s.kind == "structure")
    design = sm.basin_design(0.04, 6.0, 3)
    assert sm.problems(st) == [] and basin.boundaries["outlet"].level == pytest.approx(design["y2"], abs=1e-4)
    assert basin.boundaries["inlet"].velocity[0] == pytest.approx(design["v1"], abs=1e-4)
    assert len(sm.build(st).bodies) == 3 + 2 + 1  # three chute blocks, two baffle blocks and the end sill


def test_the_structure_command_adds_one_to_a_case(tmp_path, capsys):
    from easyfoam.cli import main

    case = tmp_path / "case"
    assert main(["new", str(case), "--example", "weir"]) == 0
    assert main(["structure", str(case), "ogee", "--station", "2.5", "--set", "design_head=0.12"]) == 0
    out = capsys.readouterr().out
    assert "Added the ogee crest 'ogee1'" in out and "design_head = 0.12 m" in out and "m³/s" in out
    p = Project.load(case)
    shape = p.shapes[-1]
    assert shape.kind == "structure" and shape.structure.station == 2.5 and p.mesh.snappy
    assert shape.structure.width == 0.5 and shape.structure.values["design_head"] == 0.12
    assert main(["structure", str(case), "ogee", "--set", "depth=1"]) == 2
    assert "it has design_head, height, face_slope, toe_radius" in capsys.readouterr().err
    assert main(["structure", str(case), "culvert", "--set", "span=5"]) == 2
    assert "do not fit side by side" in capsys.readouterr().err
    assert main(["structure", str(case), "fishway", "--width", "0.4", "--name", "pass"]) == 0
    fishway = Project.load(case).shapes[-1]
    assert fishway.name == "pass" and fishway.structure.values["slot"] == 0.05


def test_a_structure_reaches_the_mesher_as_a_surface_file():
    p = weir("weir")
    p.shapes = [Shape("spillway", kind="structure", structure=make("stepped"), level_min=1, level_max=2)]
    assert uses_snappy(p)
    files = casegen.mesh_files(p)
    stl = files["constant/triSurface/spillway.stl"]
    assert stl.startswith("solid spillway") and stl.count("facet normal") == len(sm.triangles(p.shapes[0].structure))
    assert "spillway.stl" in files["system/snappyHexMeshDict"] and "spillway.stl" in files["system/surfaceFeatureExtractDict"]
    assert ("spillway", "wall") in {(patch.name, patch.type) for patch in predicted_patches(p)}
    _lo, hi = geometry.shape_bounds(p.shapes[0], None)
    assert hi[2] == pytest.approx(1.0)  # the crest, which a rating curve measures heads from
