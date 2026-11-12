"""v0.7 end-to-end: a lifting gate and a floating box with a real OpenFOAM."""

import numpy as np
import pytest

from easyfoam.examples import floating, gate
from easyfoam.pipeline import Job, prepare_mesh, prepare_run
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
    return result


@pytest.mark.parametrize("processors", [1, 2])
def test_gate_lifts_by_the_set_distance_and_then_holds(tmp_path, runtime, processors):
    from easyfoam.results import CaseResults

    p = gate("gate")
    p.run.end_time, p.run.write_interval, p.run.processors = 0.8, 0.4, processors
    solve(tmp_path / "gate", runtime, p)
    results = CaseResults(tmp_path / "gate", p.name)
    bottom = {round(t, 3): results.read(t).patches["gate"].bounds[4] for t in results.times}
    assert bottom[0.0] == pytest.approx(0.10, abs=0.005)
    assert bottom[0.4] == pytest.approx(0.16, abs=0.01)  # 0.3 s into a 0.5 s lift of 0.1 m
    assert bottom[0.8] == pytest.approx(0.20, abs=0.005)
    bed = results.read(results.times[-1]).patches["bed"].bounds
    assert bed[4] == pytest.approx(0.0, abs=1e-6) and bed[5] == pytest.approx(0.0, abs=1e-6)  # the bed stayed put


def test_a_swinging_plate_is_where_its_period_says_at_each_saved_time(tmp_path, runtime):
    from easyfoam.model import Motion
    from easyfoam.results import CaseResults

    p = gate("paddle")
    p.shapes[0].motion = Motion(kind="oscillate", amplitude=[0.05, 0.0, 0.0], period=0.8)
    p.run.end_time, p.run.write_interval, p.run.processors = 0.6, 0.2, 1
    solve(tmp_path / "paddle", runtime, p)
    results = CaseResults(tmp_path / "paddle", p.name)
    left = {round(t, 3): results.read(t).patches["gate"].bounds[0] for t in results.times}
    assert left[0.0] == pytest.approx(1.5, abs=0.003)
    assert left[0.2] == pytest.approx(1.55, abs=0.003)  # a quarter of a period: furthest one way
    assert left[0.4] == pytest.approx(1.5, abs=0.003)  # back through the middle
    assert left[0.6] == pytest.approx(1.45, abs=0.003)  # furthest the other way


def test_a_floating_body_from_an_stl_file_floats_like_the_same_box(tmp_path, runtime):
    from easyfoam import geometry
    from tests.test_v02_core import ascii_stl, cube

    p = floating("floating")
    case = tmp_path / "floating"
    drawn = p.shapes[0]
    block = cube(scale=(0.3, 0.3, 0.12)) + np.array(drawn.min)  # the example's box, as triangles
    source = tmp_path / "block.stl"
    source.write_text(ascii_stl({"block": block}))
    shape = geometry.import_stl(case, source, name="box")
    shape.level_min, shape.level_max, shape.motion = drawn.level_min, drawn.level_max, drawn.motion
    p.shapes[0] = shape
    p.run.end_time, p.run.write_interval = 1.2, 0.6
    result = solve(case, runtime, p)
    track = result.parser.body_positions["box"]
    t = np.array([time for time, _ in track])
    z = np.array([position[2] for _, position in track])
    assert track[0][1] == pytest.approx([0.5, 0.4, 0.43], abs=0.003)  # the centre found from the triangles
    assert z[(t > 0.4) & (t <= 1.15)].mean() == pytest.approx(0.4034, abs=0.006)


@pytest.mark.parametrize("freedom", ["heave", "free"])
def test_floating_box_bobs_around_its_floating_depth(tmp_path, runtime, freedom):
    from easyfoam.results import CaseResults

    p = floating("floating")
    p.shapes[0].motion.freedom = freedom
    p.run.end_time, p.run.write_interval = 1.6, 0.8
    result = solve(tmp_path / "floating", runtime, p)
    track = result.parser.body_positions["box"]
    t = np.array([time for time, _ in track])
    z = np.array([position[2] for _, position in track])
    assert z[0] == pytest.approx(0.43, abs=0.003)  # released 3 cm above where it floats
    assert z.min() < 0.40 < z.max()  # it dips below and comes back up
    # Half as dense as water, it floats with its centre at the water surface, which its own
    # volume raises from 0.400 to 0.4034 m. One full bob takes about 0.75 s.
    assert z[(t > 0.4) & (t <= 1.15)].mean() == pytest.approx(0.4034, abs=0.006)
    assert abs(z[-1] - 0.4034) < 0.015  # and the bobbing dies away
    sideways = 1e-6 if freedom == "heave" else 0.01  # heave only: no drift at all
    assert track[-1][1][:2] == pytest.approx([0.5, 0.4], abs=sideways)
    tilt = np.array([angles[:2] for _, angles in result.parser.body_rotations["box"]])
    assert np.abs(tilt).max() < (1e-6 if freedom == "heave" else 2.0)  # a flat box stays upright
    results = CaseResults(tmp_path / "floating", p.name)
    start, end = (results.read(t).patches["walls"].bounds for t in (results.times[0], results.times[-1]))
    assert list(end) == pytest.approx(list(start), abs=1e-9)  # the tank itself did not move
    box = results.read(results.times[-1]).patches["box"].bounds
    assert (box[4] + box[5]) / 2 == pytest.approx(z[-1], abs=0.002)  # the saved mesh agrees with the reported position
