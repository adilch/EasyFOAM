"""v0.13 end-to-end: hydraulic structures made from design values, meshed and run by a real OpenFOAM."""

import numpy as np
import pytest

from easyfoam import hydraulics as hy
from easyfoam import structures as sm
from easyfoam.examples import basin, ogee, weir
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.model import Shape
from easyfoam.pipeline import Job, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def do(case, runtime, name, steps, parse=None):
    lines = []
    result = Job(case, runtime, name, steps, on_line=lines.append, parse_step=parse).run()
    assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-40:])
    return lines


def solve(case, runtime, project):
    project.save(case)
    do(case, runtime, "mesh", prepare_mesh(case, project))
    do(case, runtime, "run", prepare_run(case, project), parse=project.physics.solver)


def averaged(case, project, count):
    from easyfoam.results import CaseResults

    results = CaseResults(case, project.name)
    times = [t for t in results.times if t > 0][-count:]
    return results, hy.average_sections([hy.long_section(results.read(t), project, case, time=t) for t in times])


@pytest.mark.parametrize(
    ("label", "kind", "values"),
    [
        ("ogee", "ogee", {}), ("stepped", "stepped", {}), ("labyrinth", "labyrinth", {}), ("basin", "basin", {}),
        ("box", "culvert", {}), ("pipe", "culvert", {"circular": 1}),
        ("buried", "culvert", {"circular": 1, "span": 0.18, "count": 2, "invert": -0.02}), ("fishway", "fishway", {}),
    ],
)  # fmt: skip
def test_each_structure_is_cut_cleanly_out_of_the_mesh(tmp_path, runtime, label, kind, values):
    p = weir(label)
    base = p.mesh.base
    st = sm.place(kind, base.min, base.max)
    st.values.update(values)
    p.shapes = [Shape(label, kind="structure", structure=st, level_min=1, level_max=2)]
    case = tmp_path / label
    p.save(case)
    lines = do(case, runtime, "mesh", prepare_mesh(case, p))
    assert any("Mesh OK" in line for line in lines)
    faces = {patch.name: patch.n_faces for patch in read_boundary(case)}
    assert faces[label] > 500, faces  # the structure became a wall of its own


def test_an_ogee_crest_runs_at_its_design_head_with_about_atmospheric_pressure_on_it(tmp_path, runtime):
    case = tmp_path / "ogee"
    p = ogee("ogee")
    solve(case, runtime, p)
    results, section = averaged(case, p, 6)
    st = p.shapes[0].structure
    hd, crest = st.values["design_head"], st.bed + st.values["height"]
    pool = (section.chainage > st.station - 6 * hd) & (section.chainage < st.station - 3 * hd)
    head = float(np.nanmean(section.water_level[pool])) - crest
    assert head == pytest.approx(hd, rel=0.03)  # Q = 2.18 W Hd^1.5 runs at the design head (measured: 0.1 %)
    assert np.nanmean(section.discharge[pool]) == pytest.approx(p.boundaries["inlet"].flow_rate, rel=0.03)
    profile = hy.pressure_profile(results.read(results.times[-1]).patches["ogee"], p)
    apex = st.station + 0.2818 * hd
    top = (profile.x > apex) & (profile.x < st.station + 1.5 * hd)
    assert top.sum() >= 3 and np.abs(profile.head[top]).max() < 0.1 * hd  # atmospheric along the crest (±0.04 Hd)
    face = (profile.x < st.station + 1e-3) & (profile.z > st.bed + 0.02) & (profile.z < crest - 2 * hd)
    assert profile.head[face] == pytest.approx(crest + head - profile.z[face], abs=0.01)  # hydrostatic upstream


def fishway_project(b=0.05, pools=3, drop=0.03, depth=0.2, end=20.0):
    """Three pools of a vertical-slot fishway, the water in each starting at the uniform-flow level."""
    from easyfoam.model import BaseFace, Boundary, Structure

    pool, width, station = 10 * b, 8 * b, 0.5
    rise, x_end = pools * drop, station + pools * pool
    p = weir("fishway")
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [x_end + 0.5, width, 0.5], [125, 20, 25]
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("walls", "wall")
    st = Structure(kind="fishway", station=station, width=width, values={"slot": b, "pools": pools, "drop": drop, "wall": 0.3})
    p.shapes = [Shape("fishway", kind="structure", structure=st, level_min=1, level_max=1)]
    levels = [rise - (k + 0.5) * drop + depth for k in range(pools)]
    p.physics.water_regions = (
        [[0, 0, 0, station, width, levels[0] + drop]]
        + [[station + k * pool, 0, 0, station + (k + 1) * pool, width, levels[k]] for k in range(pools)]
        + [[x_end, 0, 0, x_end + 0.5, width, levels[-1] - drop]]
    )
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=float(0.75 * b * depth * np.sqrt(2 * 9.81 * drop)))
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=levels[-1] - drop)
    p.boundaries["walls"] = Boundary(kind="wall")
    p.probes, p.flow_monitors = [], ["outlet"]
    p.run.end_time, p.run.write_interval, p.run.max_courant, p.run.processors = end, 1.0, 0.6, 4
    return p


def test_the_fastest_water_in_each_slot_of_a_fishway_is_about_sqrt_2_g_dh(tmp_path, runtime):
    case = tmp_path / "fishway"
    p = fishway_project()
    solve(case, runtime, p)
    results, section = averaged(case, p, 5)
    st = p.shapes[0].structure
    b, pools, drop = (st.values[k] for k in ("slot", "pools", "drop"))
    pool, head, x = 10 * b, sm.SLOT_HEAD * b, section.chainage
    shift = head * np.tan(np.radians(sm.SLOT_ANGLE))
    tip = st.y0 + st.width - b - b / np.cos(np.radians(sm.SLOT_ANGLE))  # where the long baffle's slot face starts

    def level(a, c):
        return float(np.nanmean(section.water_level[(x > a) & (x < c)]))

    levels = [level(st.station - 0.35, st.station - 0.1)]
    levels += [level(st.station + k * pool + 0.15, st.station + (k + 1) * pool - 0.15) for k in range(pools)]
    levels += [level(st.station + pools * pool + 0.1, st.station + pools * pool + 0.35)]
    data = results.read(results.times[-1])
    centres = np.asarray(data.internal.cell_centers().points)
    speed = np.linalg.norm(np.asarray(data.internal.cell_data["U"]), axis=1)
    water = np.asarray(data.internal.cell_data["alpha.water"]) > 0.5
    for k in range(pools + 1):
        xk = st.station + k * pool - (head if k == pools else 0.0)
        floor = st.bed + pools * drop - k * drop
        box = ((centres[:, 0] > xk - 0.01) & (centres[:, 0] < xk + head + 2 * b) & (centres[:, 1] > tip - shift - 2 * b)
               & (centres[:, 1] < st.y0 + st.width - 0.75 * b) & (centres[:, 2] > floor + 0.01) & water)  # fmt: skip
        fall = levels[k] - levels[k + 1]
        assert fall > 0.3 * drop, levels  # the water steps down from pool to pool
        # measured: 1.19 to 1.24 times sqrt(2 g dh) in every slot (with the slots in line it was 1.2 to 1.6)
        assert speed[box].max() == pytest.approx(np.sqrt(2 * 9.81 * fall), rel=0.3), (k, levels)


def test_a_type_iii_basin_holds_the_jump_of_a_froude_6_jet_within_its_length(tmp_path, runtime):
    case = tmp_path / "basin"
    p = basin("basin")
    solve(case, runtime, p)
    _results, section = averaged(case, p, 12)
    st = next(s.structure for s in p.shapes if s.kind == "structure")
    design = sm.basin_design(st.values["y1"], st.values["froude"], 3)
    x, depth, y2 = section.chainage, section.hydraulic_depth, design["y2"]
    end = st.station + design["length"]
    reached = x[(x > st.station) & (depth >= 0.9 * y2)]
    # the jump is over by the end sill, 2.7 y2 in (measured: 2.72); a free jump would need about 6 y2
    assert len(reached) and (reached[0] - st.station) / y2 < 3.2
    after = (x > end + 0.2) & (x < 2.2)
    assert np.nanmax(section.froude[after]) < 0.6  # the water leaves calm (measured: 0.27)
    assert np.nanmean(depth[after]) == pytest.approx(y2, rel=0.05)
    y1, v1 = st.values["y1"], design["v1"]
    loss = (y2 - y1) ** 3 / (4 * y1 * y2)  # Bélanger
    assert np.nanmean(section.specific_energy[after]) == pytest.approx(y1 + v1**2 / (2 * 9.81) - loss, rel=0.05)
