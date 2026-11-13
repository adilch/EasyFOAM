"""v0.10 end-to-end: roughness, a rating-curve sweep, an inflow hydrograph and a rising tailwater, with OpenFOAM."""

import numpy as np
import pytest

from easyfoam import hydraulics as hy
from easyfoam.examples import weir
from easyfoam.foam.monitors import read_discharge, read_level_elevations
from easyfoam.model import BaseFace, Boundary, Project, RatingCurve, staircase
from easyfoam.pipeline import Job, prepare_mesh, prepare_run
from easyfoam.results import CaseResults
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def solve(case, runtime, project):
    project.save(case)
    for name, steps, parse in (("mesh", prepare_mesh, None), ("run", prepare_run, project.physics.solver)):
        lines = []
        result = Job(case, runtime, name, steps(case, project), on_line=lines.append, parse_step=parse).run()
        assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-45:])


def slice_channel(name, length, height, cells, water):
    """A thin slice of a wide channel: inlet, outlet, a bed and the atmosphere above."""
    p = Project(name=name)
    b = p.mesh.base
    b.min, b.max, b.cells = [0, 0, 0], [length, 0.05, height], cells
    b.faces["xMin"] = BaseFace("inlet", "patch")
    b.faces["xMax"] = BaseFace("outlet", "patch")
    b.faces["yMin"] = b.faces["yMax"] = BaseFace("sides", "patch")
    b.faces["zMin"] = BaseFace("bed", "wall")
    b.faces["zMax"] = BaseFace("atmosphere", "patch")
    p.mesh.snappy = False
    p.physics.solver, p.physics.turbulence = "interFoam", "kOmegaSST"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1e-6, 998.0
    p.physics.water_regions = [[0, 0, 0, length, 0.05, water]]
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    return p


def test_a_rough_bed_holds_the_water_up_as_much_as_manning_says(tmp_path, runtime):
    case = tmp_path / "rough"
    p = slice_channel("rough", 40, 0.6, [800, 1, 24], 0.34)
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.3 * 0.05)
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=0.30)
    p.boundaries["bed"] = Boundary(kind="wall", roughness="manning", manning=0.017)
    p.run.end_time, p.run.delta_t, p.run.write_interval, p.run.max_courant, p.run.processors = 120, 0.002, 30, 0.6, 4
    solve(case, runtime, p)
    results = CaseResults(case, p.name)
    section = hy.average_sections([hy.long_section(results.read(t), p, case, time=t) for t in results.times[-2:]])
    level = section.value_at("water_level", 2.0)
    # the 1D backwater curve with the n that was set reaches the same level 38 m upstream (within ~10 % in n)
    assert level == pytest.approx(np.interp(2.0, section.chainage, hy.backwater(section, 0.017)), abs=0.007)
    assert level > np.interp(2.0, section.chainage, hy.backwater(section, 0.010)) + 0.02  # well above a smooth bed


def test_a_rating_curve_sweep_over_a_weir(tmp_path, runtime):
    case = tmp_path / "rating"
    p = weir("rating")
    p.mesh.base.max, p.mesh.base.cells = [6, 0.05, 1.5], [96, 1, 24]  # a slice: the weir spans the channel
    p.physics.water_regions = [[0, 0, 0, 2.52, 0.05, 0.5]]
    p.probes = [[1.2, 0.025, 0.3]]
    discharges, hold = [0.0025, 0.005], 20.0
    p.rating = RatingCurve(discharges, hold, 2.0, 0, None, "inlet")
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=discharges[0],
                                     flow_series=staircase(discharges, hold, 2.0))  # fmt: skip
    p.run.end_time, p.run.write_interval, p.run.processors = 2 * hold, hold / 2, 2
    solve(case, runtime, p)
    points = hy.rating_curve(p, case)
    assert [pt.discharge for pt in points] == discharges
    assert 0.05 < points[0].head < points[1].head < 0.25  # more water, more head over the crest
    assert all(1.3 < pt.coefficient < 1.9 for pt in points)  # C = Q / (b H^1.5) of a short broad crest
    assert points[-1].steady  # the level settled at the larger discharge


@pytest.mark.parametrize("processors", [1, 2])
def test_an_inflow_hydrograph_and_a_rising_tailwater(tmp_path, runtime, processors):
    case = tmp_path / f"series{processors}"
    p = slice_channel("series", 4, 0.4, [80, 1, 16], 0.2)
    p.physics.turbulence = "laminar"
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.002,
                                     flow_series=[[0, 0.002], [20, 0.004], [100, 0.004]])  # fmt: skip
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=0.2,
                                      level_series=[[0, 0.2], [20, 0.26], [100, 0.26]])  # fmt: skip
    p.probes = [[3.8, 0.025, 0.1], [0.5, 0.025, 0.1]]
    p.flow_monitors = ["inlet", "outlet"]
    p.run.end_time, p.run.write_interval, p.run.processors = 26.0, 2.0, processors
    solve(case, runtime, p)
    t_in, q_in = read_discharge(case)["inlet"]
    for at, flow in ((5.0, 0.0025), (10.0, 0.003), (26.0, 0.004)):
        assert -np.interp(at, t_in, q_in) == pytest.approx(flow, rel=0.02)  # the water let in follows its table
    results = CaseResults(case, p.name)

    def level(times, at):  # averaged over saved times: the short, smooth channel sloshes a little
        sections = [hy.long_section(results.read(t), p, case, time=t) for t in times]
        return hy.average_sections(sections).value_at("water_level", at)

    assert level((8, 10, 12), 3.0) == pytest.approx(0.23, abs=0.01)  # the level follows the rising tailwater
    assert level((22, 24, 26), 3.0) == pytest.approx(0.26, abs=0.01)
    assert level((22, 24, 26), 1.0) == pytest.approx(0.26, abs=0.02)  # and the rise reaches upstream
    _times, gauges = read_level_elevations(case, p.probes)
    assert len(gauges) == 2  # the gauges recorded too (a splash at the outlet can upset a single one)
