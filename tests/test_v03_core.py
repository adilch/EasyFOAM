"""v0.3 groundwork: project checks, step status, graceful stop, continue, probes, area, rename."""

import math

import pytest

from easyfoam import casegen
from easyfoam.casegen.setup import control_dict, run_steps
from easyfoam.checks import project_issues, step_states
from easyfoam.examples import sphere
from easyfoam.foam.boundaryfile import Patch
from easyfoam.foam.probes import parse_probe_file, read_probes
from easyfoam.geometry import frontal_area, rename_shape
from easyfoam.model import Boundary, Project, Shape
from easyfoam.pipeline import prepare_run, request_stop
from tests.test_v02_core import ascii_stl, cube

PATCHES = [
    Patch("inlet", "patch", 400, 0),
    Patch("outlet", "patch", 400, 400),
    Patch("sides", "patch", 3200, 800),
    Patch("ball", "wall", 744, 4000),
]


def found(project, patches=PATCHES, has_mesh=True):
    return [(i.step, i.level) for i in project_issues(project, patches, has_mesh)]


# --- checks ------------------------------------------------------------------


def test_a_complete_project_has_nothing_to_report():
    assert found(sphere("s")) == []


def test_a_missing_mesh_is_reported_on_the_mesh_step():
    issues = project_issues(sphere("s"), [], has_mesh=False)
    assert [(i.step, i.level) for i in issues] == [("Mesh", "todo")]
    assert "Generate" in issues[0].text


def test_an_inlet_without_any_outlet_is_an_error():
    p = sphere("s")
    p.boundaries["outlet"] = Boundary(kind="slip")
    assert ("Boundaries", "error") in found(p)


def test_a_flow_that_nothing_drives_gets_a_warning():
    p = sphere("s")
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[0.0, 0.0, 0.0])
    assert found(p) == [("Boundaries", "warning")]


def test_impossible_numbers_are_errors_on_their_own_step():
    p = sphere("s")
    p.physics.nu = 0
    p.run.end_time = 0
    p.forces.ref_area = 0
    p.mesh.base.max[0] = p.mesh.base.min[0]
    p.mesh.fluid_inside = "nothing"
    assert set(found(p)) == {("Physics", "error"), ("Run", "error"), ("Mesh", "error")}
    assert len([i for i in project_issues(p, PATCHES, True) if i.step == "Run"]) == 2
    assert len([i for i in project_issues(p, PATCHES, True) if i.step == "Mesh"]) == 2


def test_step_states_summarise_progress_in_plain_words():
    p = sphere("s")
    before = step_states(p, [], has_mesh=False, cells=None, times=[])
    assert (before["Geometry"].state, before["Geometry"].detail) == ("done", "2 shapes")
    assert (before["Mesh"].state, before["Mesh"].detail) == ("todo", "Not generated yet")
    assert before["Run"].state == "todo" and before["Results"].state == "todo"

    after = step_states(p, PATCHES, has_mesh=True, cells=28538, times=[0.0, 100.0, 200.0])
    assert (after["Mesh"].state, after["Mesh"].detail) == ("done", "28,538 cells")
    assert after["Physics"].detail == "Steady, k-omega SST"
    assert (after["Boundaries"].state, after["Boundaries"].detail) == ("done", "4 boundaries")
    assert (after["Run"].state, after["Run"].detail) == ("done", "Finished at 200")
    assert after["Results"].detail == "2 saved results"


def test_a_step_with_a_problem_shows_the_problem_instead_of_the_summary():
    p = sphere("s")
    p.boundaries["outlet"] = Boundary(kind="slip")
    state = step_states(p, PATCHES, True, 100, [])["Boundaries"]
    assert state.state == "error" and "outlet" in state.detail.lower()


# --- graceful stop and continuing --------------------------------------------


def write_run_files(case, project):
    casegen.write_files(case, casegen.setup_files(project, PATCHES))


def test_graceful_stop_asks_the_solver_to_save_and_finish(tmp_path):
    write_run_files(tmp_path, sphere("s"))
    assert request_stop(tmp_path) is True
    text = (tmp_path / "system" / "controlDict").read_text()
    assert "stopAt          writeNow;" in text and "stopAt          endTime;" not in text
    assert request_stop(tmp_path / "nowhere") is False


def test_continuing_skips_the_start_up_steps():
    p = sphere("s")
    p.physics.potential_init = True
    p.run.processors = 1
    assert [s.command for s in run_steps(p, resume=True)] == ["simpleFoam"]
    p.run.processors = 4
    assert [s.command for s in run_steps(p, resume=True, decomposed=True)] == [
        "mpirun -np 4 simpleFoam -parallel", "reconstructPar -newTimes",
    ]  # fmt: skip
    assert [s.name for s in run_steps(p, resume=True, decomposed=False)] == [
        "decomposePar", "simpleFoam", "reconstructPar",
    ]  # fmt: skip


def make_solved_case(case):
    for rel, text in (("constant/polyMesh/boundary", "1\n(\n ball\n {\n type wall;\n nFaces 1;\n startFace 0;\n }\n)\n"),
                      ("0/U", "start"), ("50/U", "result"), ("processor0/50/U", "part")):  # fmt: skip
        f = case / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)


def test_continuing_keeps_results_and_start_fields_but_refreshes_the_settings(tmp_path):
    make_solved_case(tmp_path)
    p = sphere("s")
    p.run.end_time, p.run.processors = 400, 2
    steps = prepare_run(tmp_path, p, resume=True)
    assert (tmp_path / "50" / "U").read_text() == "result"
    assert (tmp_path / "0" / "U").read_text() == "start"
    assert "endTime         400;" in (tmp_path / "system" / "controlDict").read_text()
    assert [s.name for s in steps] == ["simpleFoam", "reconstructPar"]  # already decomposed


def test_there_must_be_a_result_to_continue_from(tmp_path):
    make_solved_case(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "50")
    with pytest.raises(RuntimeError, match="nothing to continue"):
        prepare_run(tmp_path, sphere("s"), resume=True)


# --- probes ------------------------------------------------------------------


def test_probes_add_a_sampling_function_for_pressure_and_velocity():
    p = sphere("s")
    p.probes = [[1.0, 0.0, 0.0], [2.0, 0.5, 0.0]]
    probes = control_dict(p, PATCHES)["functions"]["probes"]
    assert probes["type"] == "probes"
    assert probes["fields"] == ["p", "U"]
    assert probes["probeLocations"] == [[1.0, 0.0, 0.0], [2.0, 0.5, 0.0]]
    assert "probes" not in control_dict(sphere("s"), PATCHES).get("functions", {})


SCALARS = """\
# Probe 0 (1 0 0)
# Probe 1 (2 0.5 0)
#       Probe             0             1
#        Time
            1       -0.125          0.5
            2        -0.25         0.75
"""
VECTORS = """\
# Probe 0 (1 0 0)
#        Time
            1             (3 4 0)             (0 0 2)
            2             (6 8 0)             (0 0 1)
"""


def test_probe_files_give_one_series_per_probe_with_vector_magnitudes():
    assert parse_probe_file(SCALARS) == ([1.0, 2.0], [[-0.125, -0.25], [0.5, 0.75]])
    assert parse_probe_file(VECTORS) == ([1.0, 2.0], [[5.0, 10.0], [2.0, 1.0]])


def test_probe_history_is_read_per_field(tmp_path):
    folder = tmp_path / "postProcessing" / "probes" / "0"
    folder.mkdir(parents=True)
    (folder / "p").write_text(SCALARS)
    (folder / "U").write_text(VECTORS)
    data = read_probes(tmp_path)
    assert data["p"] == ([1.0, 2.0], [[-0.125, -0.25], [0.5, 0.75]])
    assert data["U"][1][0] == [5.0, 10.0]
    assert read_probes(tmp_path / "nowhere") == {}


# --- frontal area and renaming -----------------------------------------------


def test_frontal_area_of_primitives(tmp_path):
    p = Project(name="a")
    p.shapes.append(Shape("ball", kind="sphere", radius=0.5))
    assert frontal_area(p, tmp_path, [1, 0, 0]) == pytest.approx(math.pi * 0.25)
    p.shapes[0] = Shape("brick", kind="box", min=[0, 0, 0], max=[1, 2, 3])
    assert frontal_area(p, tmp_path, [1, 0, 0]) == pytest.approx(6.0)
    assert frontal_area(p, tmp_path, [0, 0, 2]) == pytest.approx(2.0)  # direction need not be a unit vector
    p.shapes[0] = Shape("rod", kind="cylinder", point1=[0, 0, 0], point2=[4, 0, 0], radius=1.0)
    assert frontal_area(p, tmp_path, [1, 0, 0]) == pytest.approx(math.pi)
    assert frontal_area(p, tmp_path, [0, 1, 0]) == pytest.approx(8.0)


def test_frontal_area_of_an_stl_and_of_several_shapes(tmp_path):
    folder = tmp_path / "constant" / "triSurface"
    folder.mkdir(parents=True)
    (folder / "blk.stl").write_text(ascii_stl({"part": cube(scale=(1.0, 2.0, 0.5))}))
    p = Project(name="a")
    p.shapes.append(Shape("blk", file="blk.stl"))
    assert frontal_area(p, tmp_path, [1, 0, 0]) == pytest.approx(1.0)
    p.shapes.append(Shape("ball", kind="sphere", radius=0.5))
    p.shapes.append(Shape("wake", kind="box", role="refinement"))  # regions do not count
    assert frontal_area(p, tmp_path, [1, 0, 0]) == pytest.approx(1.0 + math.pi * 0.25)


def test_renaming_a_shape_carries_its_settings_along():
    p = sphere("s")
    p.mesh.fluid_inside = "ball"
    p.boundaries["ball"] = Boundary(kind="movingWall")
    p.boundaries["ball_top"] = Boundary(kind="slip")
    p.forces.patches = ["ball", "inlet"]
    assert rename_shape(p, "ball", "golf ball") == "golf_ball"
    assert p.shapes[0].name == "golf_ball"
    assert p.mesh.fluid_inside == "golf_ball"
    assert set(p.boundaries) >= {"golf_ball", "golf_ball_top"} and "ball" not in p.boundaries
    assert p.forces.patches == ["golf_ball", "inlet"]


def test_a_shape_cannot_take_a_name_that_is_in_use():
    p = sphere("s")
    with pytest.raises(ValueError, match="already"):
        rename_shape(p, "ball", "wake")


def test_graceful_stop_is_noticed_even_right_after_the_run_started(tmp_path):
    # OpenFOAM ignores a changed file unless it is more than 5 s newer than before
    write_run_files(tmp_path, sphere("s"))
    control = tmp_path / "system" / "controlDict"
    before = control.stat().st_mtime
    request_stop(tmp_path)
    assert control.stat().st_mtime - before > 5


def test_the_final_state_is_saved_even_when_the_end_is_not_a_regular_save_point():
    p = sphere("s")
    p.run.end_time, p.run.write_interval = 250, 100
    function = control_dict(p, PATCHES)["functions"]["saveAtEnd"]
    assert function["type"] == "writeObjects" and function["writeControl"] == "onEnd"
    assert function["objects"] == ["U", "p", "k", "omega", "nut", "phi"]
    p.run.end_time = 300  # lands on a save point: nothing extra needed
    assert "saveAtEnd" not in control_dict(p, PATCHES)["functions"]
