import re

import pytest

from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.model import Boundary, Project, Shape
from easyfoam.pipeline import Job, StepTracker, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes


def test_tracker_separates_marker_lines_from_program_output():
    out, steps = [], []
    t = StepTracker(on_line=out.append, on_step=steps.append)
    for line in [
        "@@EASYFOAM pid 4242",
        "@@EASYFOAM step blockMesh",
        "Creating block mesh",
        "@@EASYFOAM step simpleFoam",
        "Time = 1",
        "@@EASYFOAM done",
    ]:
        t.feed(line)
    assert out == ["Creating block mesh", "Time = 1"]
    assert steps == ["blockMesh", "simpleFoam"]
    assert (t.pid, t.done, t.failed_step) == (4242, True, None)


def test_tracker_remembers_which_step_failed():
    t = StepTracker()
    for line in ["@@EASYFOAM step snappyHexMesh", "boom", "@@EASYFOAM failed snappyHexMesh 1"]:
        t.feed(line)
    assert (t.done, t.failed_step, t.current) == (False, "snappyHexMesh", "snappyHexMesh")


def test_tracker_feeds_solver_output_to_the_log_parser_only_during_the_parsed_step():
    t = StepTracker(parse_step="simpleFoam")
    for line in [
        "@@EASYFOAM step potentialFoam",
        "Time = 99",
        "@@EASYFOAM step simpleFoam",
        "Time = 1",
        "GAMG:  Solving for p, Initial residual = 1, Final residual = 0.1, No Iterations 3",
    ]:
        t.feed(line)
    assert t.parser.times == [1.0]
    assert t.parser.residuals["p"] == [(1.0, 1.0)]


def test_prepare_run_refuses_to_start_without_a_mesh(tmp_path):
    with pytest.raises(RuntimeError, match="no mesh"):
        prepare_run(tmp_path, Project(name="x"))


# ---------------------------------------------------------------------------
# End-to-end: real meshing and solving. Needs an OpenFOAM runtime.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def sphere_in_tunnel():
    p = Project(name="sphere")
    p.shapes.append(Shape("ball", kind="sphere", centre=[0, 0, 0], radius=0.5, level_min=1, level_max=1))
    base = p.mesh.base
    base.min, base.max, base.cells = [-2, -1.5, -1.5], [4, 1.5, 1.5], [16, 8, 8]
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[1.0, 0.0, 0.0])
    p.boundaries["outlet"] = Boundary(kind="pressureOutlet")
    p.physics.initial_velocity = [1.0, 0.0, 0.0]
    p.run.end_time, p.run.write_interval = 15, 15
    return p


@pytest.mark.openfoam
def test_sphere_in_a_tunnel_meshes_and_solves_in_parallel(tmp_path, runtime):
    case = tmp_path / "sphere"
    project = sphere_in_tunnel()
    project.run.processors = 2
    project.save(case)

    lines = []
    mesh = Job(case, runtime, "mesh", prepare_mesh(case, project), on_line=lines.append).run()
    assert mesh.ok, "\n".join(lines[-40:])
    patches = {p.name: p.type for p in read_boundary(case)}
    assert patches == {"inlet": "patch", "outlet": "patch", "sides": "patch", "ball": "wall"}

    lines.clear()
    job = Job(case, runtime, "run", prepare_run(case, project), on_line=lines.append,
              parse_step="simpleFoam")  # fmt: skip
    result = job.run()
    assert result.ok, "\n".join(lines[-40:])
    assert result.parser.finished and result.parser.error is None
    assert result.parser.times[-1] == 15.0
    assert {"Ux", "p", "k", "omega"} <= set(result.parser.residuals)
    assert (case / "15" / "U").is_file()  # reconstructed result on the Windows side
    assert (case / "log.simpleFoam").is_file()


@pytest.mark.openfoam
def test_results_of_a_finished_run_can_be_read_back(tmp_path, runtime):
    from easyfoam.results import CaseResults

    case = tmp_path / "sphere"
    project = sphere_in_tunnel()
    project.save(case)
    assert Job(case, runtime, "mesh", prepare_mesh(case, project)).run().ok
    mesh_only = CaseResults(case, project.name)
    assert mesh_only.times == [] or mesh_only.times == [0.0]
    assert set(mesh_only.read().patches) == {"inlet", "outlet", "sides", "ball"}

    assert Job(case, runtime, "run", prepare_run(case, project)).run().ok
    results = CaseResults(case, project.name)
    assert results.times == [0.0, 15.0]
    assert {"U", "p", "k", "omega"} <= set(results.fields)
    data = results.read(15.0)
    assert data.internal.n_cells > 700
    assert set(data.patches) == {"inlet", "outlet", "sides", "ball"}
    speed = data.internal["U"]
    assert speed.shape[1] == 3 and abs(speed).max() > 0.5


@pytest.mark.openfoam
def test_an_imported_stl_is_meshed_with_its_sharp_edges_and_layers(tmp_path, runtime):
    pv = pytest.importorskip("pyvista")
    from easyfoam.geometry import fit_base_mesh, import_stl

    source = tmp_path / "Test Block.stl"
    pv.Box(bounds=(0, 1, -0.3, 0.3, 0, 0.4)).triangulate().save(str(source))
    case = tmp_path / "block"
    project = Project(name="block")
    shape = import_stl(case, source)
    shape.level_min, shape.level_max, shape.layers = 1, 2, 2
    project.shapes.append(shape)
    fit_base_mesh(project, case, cell_size=0.25, upstream=1, downstream=2, lateral=1)
    project.save(case)

    lines = []
    result = Job(case, runtime, "mesh", prepare_mesh(case, project), on_line=lines.append).run()
    assert result.ok, "\n".join(lines[-40:])
    patches = {p.name: p for p in read_boundary(case)}
    assert patches["Test_Block"].type == "wall" and patches["Test_Block"].n_faces > 100
    assert (case / "constant" / "triSurface" / "Test_Block.eMesh").is_file()
    log = (case / "log.snappyHexMesh").read_text(errors="replace")
    assert re.search(r"^Test_Block\s+\d+\s+2\s+2\s", log, re.MULTILINE), "both requested layers should be added"
    assert "Mesh OK." in (case / "log.checkMesh").read_text(errors="replace")


@pytest.mark.openfoam
def test_a_running_job_can_be_stopped_and_leaves_no_process_behind(tmp_path, runtime):
    import subprocess
    import threading
    import time

    from easyfoam.runtime import Step

    job = Job(tmp_path, runtime, "long", [Step("sleeper", "sleep 321")])
    results = []
    worker = threading.Thread(target=lambda: results.append(job.run()))
    started = time.time()
    worker.start()
    while job.tracker.current != "sleeper":
        assert time.time() - started < 30, "the job never started"
        time.sleep(0.05)
    job.stop()
    worker.join(30)
    assert not worker.is_alive()
    assert results[0].stopped and not results[0].ok
    left = subprocess.run([*runtime._prefix(), "pgrep", "-f", "sleep 321"], capture_output=True, text=True)
    assert left.stdout.strip() == ""
