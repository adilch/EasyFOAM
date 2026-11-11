"""v0.3 end-to-end: graceful stop, continuing a run and probes with a real solver."""

import threading
import time

import pytest

from easyfoam.examples import cavity
from easyfoam.foam.probes import read_probes
from easyfoam.pipeline import Job, computed_times, prepare_mesh, prepare_run, request_stop
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def test_a_run_can_be_stopped_gracefully_then_continued_with_probes(tmp_path, runtime):
    case = tmp_path / "cavity"
    project = cavity("cavity")
    project.mesh.base.cells = [80, 80, 1]  # slow enough to catch in the act
    project.run.end_time, project.run.write_interval = 100000, 100000
    project.run.residual_target = 0
    project.probes = [[0.5, 0.5, 0.05], [0.5, 0.9, 0.05]]
    project.save(case)
    assert Job(case, runtime, "mesh", prepare_mesh(case, project)).run().ok

    job = Job(case, runtime, "run", prepare_run(case, project), parse_step="simpleFoam")
    results = []
    worker = threading.Thread(target=lambda: results.append(job.run()), daemon=True)
    worker.start()
    try:
        deadline = time.time() + 120
        while (job.parser.time or 0) < 20:
            assert time.time() < deadline, "the solver never got going"
            time.sleep(0.1)
        assert request_stop(case)
        worker.join(60)
        assert not worker.is_alive(), "the solver did not finish after the graceful stop"
    finally:
        if worker.is_alive():
            job.stop()  # never leave a solver running behind a failed test
            worker.join(30)

    first = results[0]
    assert first.ok and not first.stopped  # it ended normally, having saved its state
    stopped_at = computed_times(case)[-1]
    assert 20 <= stopped_at < 100000
    assert (case / f"{stopped_at:g}" / "U").is_file()

    project.run.end_time = stopped_at + 10
    again = Job(case, runtime, "run", prepare_run(case, project, resume=True), parse_step="simpleFoam").run()
    assert again.ok
    assert again.parser.times[0] == stopped_at + 1  # carried on, did not start over
    assert computed_times(case)[-1] == stopped_at + 10

    times, series = read_probes(case)["p"]
    assert len(series) == 2 and len(times) == int(stopped_at) + 10
    assert times == sorted(times)
