import pytest

pytest.importorskip("PySide6")

from easyfoam import casegen  # noqa: E402
from easyfoam.examples import sphere  # noqa: E402
from easyfoam.foam.boundaryfile import Patch  # noqa: E402
from easyfoam.model import Boundary, Project  # noqa: E402
from tests.test_gui import type_into, wait_for_job  # noqa: E402

pytestmark = pytest.mark.gui


def open_window(tmp_path, project=None):
    from easyfoam.gui.main_window import MainWindow

    (project or sphere("demo")).save(tmp_path)
    window = MainWindow(enable_3d=False, detect=False)
    window.notices = []
    window.notify = lambda title, text, level="info": window.notices.append((level, text))
    window.open_project(tmp_path)
    return window


# --- icons and state ---------------------------------------------------------


def test_icons_are_rendered_from_svg_in_the_requested_colour_and_size(qapp):
    from easyfoam.gui.icons import icon, pixmap

    assert not icon("play").isNull()
    image = pixmap("play", 24, "#ff0000").toImage()
    assert image.width() == 48  # drawn at twice the size for sharp high-DPI display
    reds = sum(
        1 for x in range(0, 48, 2) for y in range(0, 48, 2)
        if image.pixelColor(x, y).alpha() > 200 and image.pixelColor(x, y).red() > 200
    )  # fmt: skip
    assert reds > 5


def test_an_unknown_icon_name_is_an_error_not_a_blank(qapp):
    from easyfoam.gui.icons import icon

    with pytest.raises(KeyError, match="no-such-icon"):
        icon("no-such-icon")


def test_every_icon_the_interface_uses_is_shipped(qapp):
    from easyfoam.gui import icons

    missing = [name for name in icons.USED if name not in icons.names()]
    assert missing == []
    assert "LICENSE-lucide.txt" in [p.name for p in icons.ICON_DIR.iterdir()]


def test_recent_projects_are_remembered_newest_first_without_duplicates(tmp_path, monkeypatch):
    from easyfoam.gui import state

    monkeypatch.setenv("EASYFOAM_STATE_FILE", str(tmp_path / "state.json"))
    folders = []
    for name in ("a", "b", "c"):
        Project(name=name).save(tmp_path / name)
        folders.append(str(tmp_path / name))
    for folder in (folders[0], folders[1], folders[0], folders[2]):
        state.add_recent(folder)
    assert state.load_recent() == [folders[2], folders[0], folders[1]]
    (tmp_path / "a" / "easyfoam.json").unlink()  # a project that was deleted drops off the list
    assert state.load_recent() == [folders[2], folders[1]]


# --- welcome page and project creation ---------------------------------------


def test_the_window_starts_on_a_welcome_page_and_switches_to_the_workspace(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    window = MainWindow(enable_3d=False, detect=False)
    assert window.pages.currentWidget() is window.welcome
    sphere("demo").save(tmp_path)
    window.open_project(tmp_path)
    assert window.pages.currentWidget() is window.workspace
    window.close()


def test_welcome_page_offers_examples_and_recent_projects(qapp, tmp_path):
    from easyfoam.gui.welcome import WelcomePage

    page = WelcomePage()
    asked = []
    page.new_requested.connect(asked.append)
    page.recent_requested.connect(asked.append)
    page.example_buttons["pipe"].click()
    page.new_button.click()
    page.set_recent([str(tmp_path)])
    page.recent_list.itemActivated.emit(page.recent_list.item(0))
    assert asked == ["pipe", "empty", str(tmp_path)]


def test_a_new_project_is_created_in_its_own_folder_under_the_chosen_location(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    window = MainWindow(enable_3d=False, detect=False)
    window.create_project("Wing study", tmp_path, "sphere")
    assert window.case_dir == tmp_path / "Wing study"
    assert window.project.name == "Wing_study"
    assert Project.load(tmp_path / "Wing study").shapes[0].name == "ball"
    with pytest.raises(ValueError, match="already"):
        window.create_project("Wing study", tmp_path, "empty")
    window.close()


# --- guidance ----------------------------------------------------------------


def test_sidebar_shows_the_state_and_a_summary_of_every_step(qapp, tmp_path):
    from easyfoam.gui.sidebar import DETAIL_ROLE, STATE_ROLE

    window = open_window(tmp_path)
    rows = {window.steps.item(i).text(): window.steps.item(i) for i in range(window.steps.count())}
    assert rows["Geometry"].data(STATE_ROLE) == "done" and rows["Geometry"].data(DETAIL_ROLE) == "2 shapes"
    assert rows["Mesh"].data(STATE_ROLE) == "todo"
    assert rows["Physics"].data(DETAIL_ROLE) == "Steady, k-omega SST"
    window.project.boundaries["outlet"] = Boundary(kind="slip")
    window.refresh_status()
    assert rows["Boundaries"].data(STATE_ROLE) == "error"
    window.close()


def test_next_and_back_walk_through_the_steps(qapp, tmp_path):
    window = open_window(tmp_path)
    assert window.back_button.isEnabled() is False
    assert window.next_button.text() == "Next: Mesh"
    window.next_button.click()
    assert window.current_step() == "Mesh"
    window.back_button.click()
    assert window.current_step() == "Geometry"
    window.steps.setCurrentRow(5)
    assert window.next_button.isEnabled() is False
    window.close()


def test_toolbar_actions_carry_icons(qapp, tmp_path):
    window = open_window(tmp_path)
    for action in (window.new_action, window.open_action, window.mesh_action, window.run_action,
                   window.stop_action, window.paraview_action, window.continue_action):  # fmt: skip
        assert not action.icon().isNull(), action.text()
    window.close()


def test_running_is_refused_with_an_explanation_while_the_project_has_errors(qapp, tmp_path):
    window = open_window(tmp_path)
    (tmp_path / "constant" / "polyMesh").mkdir(parents=True)
    (tmp_path / "constant" / "polyMesh" / "boundary").write_text(
        "2\n(\n inlet\n {\n type patch;\n nFaces 1;\n startFace 0;\n }\n"
        " outlet\n {\n type patch;\n nFaces 1;\n startFace 1;\n }\n)\n"
    )
    from easyfoam.runtime import Runtime

    window.runtime = Runtime("posix", "fake", "/nowhere/bashrc")
    window.project.boundaries["outlet"] = Boundary(kind="slip")
    window.run_solver()
    assert window.thread is None
    assert [level for level, _ in window.notices] == ["error"]
    assert "outlet" in window.notices[0][1]
    window.close()


def test_progress_bar_follows_the_run(qapp, tmp_path):
    window = open_window(tmp_path)
    window.show_progress(50, 200)
    assert window.progress.value() == 25 and not window.progress.isHidden()
    window.show_progress(None, None)
    assert window.progress.isHidden()
    window.close()


# --- stop, continue ----------------------------------------------------------


class FakeThread:
    def __init__(self, name):
        self.name, self.killed, self.lines = name, False, []

    def stop(self):
        self.killed = True


def test_first_stop_lets_the_solver_save_and_finish_and_the_second_stop_kills_it(qapp, tmp_path):
    window = open_window(tmp_path)
    casegen.write_files(tmp_path, casegen.setup_files(window.project, [Patch("inlet", "patch", 1, 0)]))
    window.thread = fake = FakeThread("run")
    window.stop_job()
    assert "writeNow" in (tmp_path / "system" / "controlDict").read_text()
    assert fake.killed is False
    window.stop_job()
    assert fake.killed is True
    window.thread = None
    window.close()


def test_stopping_the_mesher_ends_it_at_once(qapp, tmp_path):
    window = open_window(tmp_path)
    window.thread = fake = FakeThread("mesh")
    window.stop_job()
    assert fake.killed is True
    window.thread = None
    window.close()


def test_continue_is_only_offered_when_there_is_a_result_to_continue_from(qapp, tmp_path):
    window = open_window(tmp_path)
    assert window.continue_action.isEnabled() is False
    assert window.run_panel.continue_button.isEnabled() is False
    (tmp_path / "constant" / "polyMesh").mkdir(parents=True)
    (tmp_path / "constant" / "polyMesh" / "boundary").write_text("1\n(\n w\n {\n type wall;\n nFaces 1;\n startFace 0;\n }\n)\n")
    (tmp_path / "100").mkdir()
    window.refresh_status()
    assert window.continue_action.isEnabled() is True
    assert window.run_panel.continue_button.isEnabled() is True
    window.close()


# --- panels ------------------------------------------------------------------


def test_run_panel_manages_probe_points(qapp):
    from easyfoam.gui.panels import RunPanel

    project = Project(name="x")
    panel = RunPanel()
    panel.load(project)
    panel.add_probe([1.0, 0.0, 0.5])
    panel.add_probe()
    assert project.probes == [[1.0, 0.0, 0.5], [0.0, 0.0, 0.0]]
    assert panel.probe_table.rowCount() == 2
    panel.set_probe(1, [2.0, 3.0, 4.0])
    panel.probe_table.selectRow(0)
    panel.remove_probe()
    assert project.probes == [[2.0, 3.0, 4.0]]


def test_run_panel_estimates_the_reference_area_from_the_geometry(qapp, tmp_path):
    from easyfoam.gui.panels import RunPanel

    project = sphere("s")
    project.forces.ref_area = 99.0
    panel = RunPanel()
    panel.load(project, tmp_path)
    panel.estimate_area.click()
    assert project.forces.ref_area == pytest.approx(0.7854, abs=1e-4)
    assert panel.ref_area.value() == pytest.approx(0.7854, abs=1e-4)


def test_run_panel_lists_what_still_stands_in_the_way(qapp):
    from easyfoam.checks import Issue
    from easyfoam.gui.panels import RunPanel

    panel = RunPanel()
    panel.load(Project(name="x"))
    panel.show_issues([Issue("Mesh", "todo", "Generate the mesh before running."),
                       Issue("Boundaries", "error", "There is an inlet but no outlet.")])  # fmt: skip
    assert "Generate the mesh" in panel.issues.text() and "no outlet" in panel.issues.text()
    panel.show_issues([])
    assert "Ready to run" in panel.issues.text()


def test_geometry_panel_renames_the_selected_shape(qapp):
    from easyfoam.gui.panels import GeometryPanel

    project = sphere("s")
    panel = GeometryPanel()
    panel.load(project, None)
    picked = []
    panel.selection_changed.connect(picked.append)
    panel.shape_list.setCurrentRow(1)
    panel.shape_list.setCurrentRow(0)
    panel.rename_selected("golf ball")
    assert project.shapes[0].name == "golf_ball"
    assert "golf_ball" in panel.shape_list.item(0).text()
    assert picked[:2] == ["wake", "ball"]


def test_boundary_panel_reports_the_selected_boundary_and_shows_icons(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    panel = BoundaryPanel()
    picked = []
    panel.selection_changed.connect(picked.append)
    panel.load(Project(name="x"), [Patch("inlet", "patch", 1, 0), Patch("body", "wall", 1, 1)])
    panel.patch_list.setCurrentRow(1)
    assert picked[-1] == "body"
    assert not panel.patch_list.item(0).icon().isNull()
    assert not panel.kind.itemIcon(0).isNull()


def test_inputs_explain_themselves_with_tooltips(qapp):
    from easyfoam.gui.panels import MeshPanel, PhysicsPanel, RunPanel

    for widget in (PhysicsPanel().nu, PhysicsPanel().intensity, MeshPanel().snappy,
                   MeshPanel().location, RunPanel().processors, RunPanel().residual_target):  # fmt: skip
        assert len(widget.toolTip()) > 20


# --- end to end --------------------------------------------------------------


@pytest.mark.openfoam
def test_window_continues_a_finished_run(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow
    from easyfoam.runtime import detect_runtimes

    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    window = MainWindow(enable_3d=False, detect=False)
    window.runtime = found[0]
    window.create_project("cavity", tmp_path, "cavity")
    window.project.run.end_time, window.project.run.write_interval = 10, 10
    window.generate_mesh()
    wait_for_job(qapp, window)
    window.run_solver()
    wait_for_job(qapp, window)
    assert window.continue_action.isEnabled()

    type_into(window.run_panel.end_time, "17")
    window.continue_run()
    wait_for_job(qapp, window)
    times = [window.results_panel.time.itemData(i) for i in range(window.results_panel.time.count())]
    assert times == [0.0, 10.0, 17.0]
    assert window.progress.isHidden()
    window.close()
