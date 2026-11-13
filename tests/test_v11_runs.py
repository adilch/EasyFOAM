"""v0.11 end-to-end: the age of the water and a tracer test in a contact tank, checked against V/Q."""

import pytest

from easyfoam import tracertest as tt
from easyfoam.examples import tank
from easyfoam.foam.monitors import read_outlet_tracers
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


def tracer_test(case, runtime, project):
    """A step test from the finished steady flow, followed for four theoretical residence times."""
    flow = CaseResults(case, project.name)
    volume, inflow = tt.volume_and_flow(flow.read(flow.times[-1]), project, ["inlet"])
    theoretical = volume / inflow
    target, steps = tt.prepare(case, project, tt.TestSettings("inlet", "outlet", "step", 4 * theoretical), theoretical)
    lines = []
    result = Job(target, runtime, "tracer test", steps, on_line=lines.append, parse_step="pimpleFoam").run()
    assert result.ok, "\n".join(lines[-30:])
    times, concentration = tt.read_test(case, "outlet")
    return tt.residence_times(times, concentration, "step", theoretical)


def test_the_age_of_the_water_and_a_tracer_test_agree_with_v_over_q(tmp_path, runtime):
    case = tmp_path / "tank"
    p = tank("tank")
    solve(case, runtime, p)
    rtd = tracer_test(case, runtime, p)
    assert rtd.theoretical == pytest.approx(7680, rel=0.01)  # 768 m³ at 0.1 m³/s
    _times, (age, chlorine) = read_outlet_tracers(case)["outlet"]
    # the mean age of the water leaving is V/Q (a hair less: some age diffuses out through the inlet)
    assert age[-1] == pytest.approx(rtd.theoretical, rel=0.01)
    # all tracer fed in is either still in the tank or has left: the mean residence time is V/Q too
    assert rtd.complete > 0.98 and rtd.mean == pytest.approx(rtd.theoretical, rel=0.01)
    assert 0.4 < rtd.baffling_factor < 0.6 and 2 < rtd.morrill < 4.5  # nine baffles: average baffling
    # with a first-order decay, the residual at the outlet follows from the residence times alone
    assert chlorine[-1] / 2.0 == pytest.approx(rtd.remaining(0.3 / 3600), rel=0.02)


def test_without_its_baffles_the_tank_short_circuits(tmp_path, runtime):
    p = tank("open")
    p.shapes = [s for s in p.shapes if not s.name.startswith("baffle")]
    p.tracers = []  # the flow and the tracer test are enough
    solve(tmp_path / "open", runtime, p)
    rtd = tracer_test(tmp_path / "open", runtime, p)
    assert rtd.baffling_factor < 0.3  # about 0.5 with the nine baffles
    assert rtd.mean == pytest.approx(rtd.theoretical, rel=0.02)
