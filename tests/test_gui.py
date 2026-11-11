import pytest

pytest.importorskip("PySide6")

from easyfoam.examples import sphere  # noqa: E402
from easyfoam.foam.boundaryfile import Patch  # noqa: E402
from easyfoam.model import Project  # noqa: E402

pytestmark = pytest.mark.gui


def type_into(edit, text):
    edit.setText(text)
    edit.editingFinished.emit()


def select(combo, data):
    index = combo.findData(data)
    assert index >= 0, f"{data!r} is not offered"
    combo.setCurrentIndex(index)


class Counter:
    def __init__(self, signal):
        self.count = 0
        signal.connect(self._hit)

    def _hit(self, *args):
        self.count += 1


# --- widgets ---------------------------------------------------------------


def test_float_edit_accepts_scientific_notation_and_reverts_garbage(qapp):
    from easyfoam.gui.widgets import FloatEdit

    edit = FloatEdit(1.5)
    type_into(edit, "1e-5")
    assert edit.value() == 1e-5
    type_into(edit, "fast")
    assert edit.value() == 1e-5 and edit.text() == "1e-05"


def test_vector_edit_reports_three_components(qapp):
    from easyfoam.gui.widgets import VectorEdit

    edit = VectorEdit([1, 2, 3])
    hits = Counter(edit.changed)
    type_into(edit.edits[1], "-4.5")
    assert edit.value() == [1.0, -4.5, 3.0]
    assert hits.count == 1


# --- panels ----------------------------------------------------------------


def test_physics_panel_writes_choices_into_the_project(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    panel = PhysicsPanel()
    panel.load(project)
    hits = Counter(panel.changed)
    select(panel.solver, "pimpleFoam")
    select(panel.turbulence, "kEpsilon")
    type_into(panel.velocity.edits[0], "12")
    assert (project.physics.solver, project.physics.turbulence) == ("pimpleFoam", "kEpsilon")
    assert project.physics.initial_velocity == [12.0, 0.0, 0.0]
    assert hits.count == 3


def test_choosing_a_material_fills_in_its_viscosity_and_density(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    panel = PhysicsPanel()
    panel.load(project)
    select(panel.material, "water")
    assert (project.physics.material, project.physics.nu, project.physics.rho) == ("water", 1e-06, 998.0)
    assert panel.nu.value() == 1e-06


def test_loading_a_project_into_a_panel_does_not_count_as_a_change(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    panel = PhysicsPanel()
    hits = Counter(panel.changed)
    panel.load(sphere("s"))
    assert hits.count == 0


def test_geometry_panel_adds_primitives_with_unique_names_and_removes_them(qapp):
    from easyfoam.gui.panels import GeometryPanel

    project = Project(name="x")
    panel = GeometryPanel()
    panel.load(project, None)
    panel.add_primitive("sphere")
    panel.add_primitive("sphere")
    panel.add_primitive("box")
    assert [(s.name, s.kind) for s in project.shapes] == [
        ("sphere1", "sphere"), ("sphere2", "sphere"), ("box1", "box"),
    ]  # fmt: skip
    panel.shape_list.setCurrentRow(0)
    panel.remove_selected()
    assert [s.name for s in project.shapes] == ["sphere2", "box1"]


def test_geometry_panel_edits_the_selected_shape(qapp):
    from easyfoam.gui.panels import GeometryPanel

    project = sphere("s")
    panel = GeometryPanel()
    panel.load(project, None)
    panel.shape_list.setCurrentRow(0)
    type_into(panel.radius, "0.75")
    panel.level_max.setValue(5)
    panel.layers.setValue(3)
    ball = project.shapes[0]
    assert (ball.radius, ball.level_max, ball.layers) == (0.75, 5, 3)


def test_mesh_panel_renames_and_retypes_a_base_mesh_face(qapp):
    from easyfoam.gui.panels import MeshPanel

    project = Project(name="x")
    panel = MeshPanel()
    panel.load(project)
    panel.set_face("zMin", "ground", "wall")
    assert (project.mesh.base.faces["zMin"].name, project.mesh.base.faces["zMin"].type) == ("ground", "wall")
    panel.cells[0].setValue(64)
    assert project.mesh.base.cells[0] == 64


def test_boundary_panel_lists_patches_and_offers_kinds_that_fit_the_patch_type(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = Project(name="x")
    panel = BoundaryPanel()
    panel.load(project, [Patch("inlet", "patch", 1, 0), Patch("body", "wall", 1, 1), Patch("mid", "symmetry", 1, 2)])
    assert [panel.patch_list.item(i).data(0x0100) for i in range(3)] == ["inlet", "body", "mid"]

    panel.patch_list.setCurrentRow(0)
    kinds = [panel.kind.itemData(i) for i in range(panel.kind.count())]
    assert kinds == ["velocityInlet", "pressureOutlet", "slip"]
    panel.patch_list.setCurrentRow(1)
    assert [panel.kind.itemData(i) for i in range(panel.kind.count())] == ["wall", "movingWall", "slip"]
    panel.patch_list.setCurrentRow(2)
    assert panel.kind.isEnabled() is False


def test_boundary_panel_stores_the_edit_under_the_patch_name(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = Project(name="x")
    panel = BoundaryPanel()
    panel.load(project, [Patch("inlet", "patch", 1, 0), Patch("sides", "patch", 1, 1)])
    panel.patch_list.setCurrentRow(1)
    select(panel.kind, "velocityInlet")
    type_into(panel.velocity.edits[2], "3")
    assert project.boundaries["sides"].kind == "velocityInlet"
    assert project.boundaries["sides"].velocity == [0.0, 0.0, 3.0]
    assert "inlet" not in project.boundaries  # untouched patches keep their default


def test_run_panel_shows_time_step_settings_only_for_transient_solvers(qapp):
    from easyfoam.gui.panels import RunPanel

    project = Project(name="x")
    panel = RunPanel()
    panel.load(project)
    assert panel.delta_t.isEnabled() is False
    project.physics.solver = "pimpleFoam"
    panel.load(project)
    assert panel.delta_t.isEnabled() is True
    panel.processors.setValue(6)
    assert project.run.processors == 6


# --- main window -----------------------------------------------------------


def test_window_opens_a_project_and_shows_the_six_workflow_steps(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    sphere("ball_case").save(tmp_path)
    window = MainWindow(enable_3d=False, detect=False)
    window.open_project(tmp_path)
    steps = [window.steps.item(i).text() for i in range(window.steps.count())]
    assert steps == ["Geometry", "Mesh", "Physics", "Boundaries", "Run", "Results"]
    assert window.project.name == "ball_case"
    assert "ball_case" in window.windowTitle()
    window.close()


def test_window_saves_edits_back_to_the_project_file(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    Project(name="p").save(tmp_path)
    window = MainWindow(enable_3d=False, detect=False)
    window.open_project(tmp_path)
    select(window.physics_panel.turbulence, "laminar")
    window.save_project()
    assert Project.load(tmp_path).physics.turbulence == "laminar"
    window.close()


def test_boundaries_step_uses_predicted_patches_until_a_mesh_exists(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    sphere("s").save(tmp_path)
    window = MainWindow(enable_3d=False, detect=False)
    window.open_project(tmp_path)
    names = [window.boundary_panel.patch_list.item(i).data(0x0100)
             for i in range(window.boundary_panel.patch_list.count())]  # fmt: skip
    assert names == ["inlet", "outlet", "sides", "ball"]
    window.close()


def test_actions_that_need_a_project_are_disabled_until_one_is_open(qapp):
    from easyfoam.gui.main_window import MainWindow

    window = MainWindow(enable_3d=False, detect=False)
    assert window.mesh_action.isEnabled() is False and window.run_action.isEnabled() is False
    window.close()


def test_reopening_a_case_shows_the_residual_history_of_its_last_run(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    Project(name="p").save(tmp_path)
    (tmp_path / "log.simpleFoam").write_text(
        "Time = 1\n\n"
        "smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.1, No Iterations 1\n"
        "GAMG:  Solving for p, Initial residual = 0.5, Final residual = 0.01, No Iterations 4\n"
        "Time = 2\n\n"
        "smoothSolver:  Solving for Ux, Initial residual = 0.2, Final residual = 0.01, No Iterations 1\n"
        "GAMG:  Solving for p, Initial residual = 0.1, Final residual = 0.01, No Iterations 4\n"
    )
    window = MainWindow(enable_3d=False, detect=False)
    window.open_project(tmp_path)
    assert set(window._curves) == {"Ux", "p"}
    xs, ys = window._curves["p"].getData()
    assert list(xs) == [1.0, 2.0]
    window.close()


def wait_for_job(qapp, window, timeout=180.0):
    import time

    deadline = time.time() + timeout
    while window.thread is not None:
        qapp.processEvents()
        time.sleep(0.02)
        assert time.time() < deadline, "the job did not finish in time"
    qapp.processEvents()


@pytest.mark.openfoam
def test_cavity_example_meshes_and_runs_from_the_window(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow
    from easyfoam.runtime import detect_runtimes

    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    window = MainWindow(enable_3d=False, detect=False)
    window.runtime = found[0]
    window.new_project(tmp_path / "cavity", "cavity")
    window.project.run.end_time, window.project.run.write_interval = 20, 20

    window.generate_mesh()
    assert window.thread is not None and window.stop_action.isEnabled()
    wait_for_job(qapp, window)
    assert "Mesh ready (1,600 cells)" in window.run_panel.status.text()
    assert {p.name: p.type for p in window.mesh_patches()} == {
        "walls": "wall", "lid": "wall", "frontAndBack": "empty",
    }  # fmt: skip
    assert "generated mesh" in window.boundary_panel.source.text()

    window.run_solver()
    wait_for_job(qapp, window)
    assert window.run_panel.status.text() == "Run finished."
    assert {"Ux", "Uy", "p"} <= set(window._curves)
    assert window.results_panel.time.count() == 2  # 0 and 20
    assert window.current_step() == "Results"
    assert "Time = 20" in window.log.toPlainText()
    assert window.run_action.isEnabled() and not window.stop_action.isEnabled()
    window.close()
