import pytest

pytest.importorskip("PySide6")

from easyfoam.examples import dambreak  # noqa: E402
from easyfoam.foam.boundaryfile import Patch  # noqa: E402
from easyfoam.model import Project  # noqa: E402
from tests.test_gui import select, type_into, wait_for_job  # noqa: E402

pytestmark = pytest.mark.gui


def test_open_boundaries_offer_the_hydraulic_conditions(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = Project(name="x")
    panel = BoundaryPanel()
    panel.load(project, [Patch("inlet", "patch", 1, 0)])
    kinds = [panel.kind.itemData(i) for i in range(panel.kind.count())]
    assert kinds == ["velocityInlet", "flowRateInlet", "pressureOutlet", "freeOutflow", "atmosphere", "slip"]
    select(panel.kind, "flowRateInlet")
    type_into(panel.flow_rate, "0.05")
    assert project.boundaries["inlet"].kind == "flowRateInlet"
    assert project.boundaries["inlet"].flow_rate == 0.05
    assert not panel.form.isRowVisible(panel.velocity) and panel.form.isRowVisible(panel.flow_rate)


def test_a_velocity_inlet_asks_for_its_water_share_only_in_free_surface_flow(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = Project(name="x")
    panel = BoundaryPanel()
    panel.load(project, [Patch("inlet", "patch", 1, 0)])
    assert not panel.form.isRowVisible(panel.water_fraction)
    project.physics.solver = "interFoam"
    panel.load(project, [Patch("inlet", "patch", 1, 0)])
    assert panel.form.isRowVisible(panel.water_fraction)
    type_into(panel.water_fraction, "0")
    assert project.boundaries["inlet"].water_fraction == 0.0


def test_choosing_free_surface_flow_shows_the_water_settings_and_makes_water_the_fluid(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    panel = PhysicsPanel()
    panel.load(project)
    assert panel.water_box.isHidden()
    select(panel.solver, "interFoam")
    assert not panel.water_box.isHidden()
    assert (project.physics.material, project.physics.rho) == ("water", 998.0)
    type_into(panel.gravity.edits[2], "-1.62")
    type_into(panel.surface_tension, "0.05")
    assert project.physics.gravity == [0.0, 0.0, -1.62]
    assert project.physics.surface_tension == 0.05


def test_initial_water_is_managed_as_a_list_of_boxes_or_filled_to_a_level(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    project.physics.solver = "interFoam"
    project.mesh.base.min, project.mesh.base.max = [0, 0, 0], [6, 0.5, 1.5]
    panel = PhysicsPanel()
    panel.load(project)
    panel.fill_to_level(0.4)
    assert project.physics.water_regions == [[0.0, 0.0, 0.0, 6.0, 0.5, 0.4]]
    panel.add_water_region([0, 0, 0, 2.5, 0.5, 0.6])
    assert panel.water_table.rowCount() == 2
    panel.water_table.selectRow(0)
    panel.remove_water_region()
    assert project.physics.water_regions == [[0.0, 0.0, 0.0, 2.5, 0.5, 0.6]]


def test_force_coefficients_are_switched_off_for_free_surface_runs(qapp):
    from easyfoam.gui.panels import RunPanel

    project = Project(name="x")
    panel = RunPanel()
    panel.load(project)
    assert panel.force_box.isEnabled()
    project.physics.solver = "interFoam"
    panel.load(project)
    assert not panel.force_box.isEnabled()


def test_results_can_show_the_water_surface(qapp):
    from easyfoam.gui.panels import ResultsPanel

    panel = ResultsPanel()
    assert panel.mode.findData("water") >= 0


def test_hydraulic_examples_are_on_the_start_page_and_in_the_menu(qapp):
    from easyfoam.gui.main_window import EXAMPLE_LABELS
    from easyfoam.gui.welcome import WelcomePage

    page = WelcomePage()
    assert {"weir", "dambreak"} <= set(page.example_buttons)
    assert {"weir", "dambreak"} <= set(EXAMPLE_LABELS)


@pytest.mark.openfoam
def test_dam_break_runs_from_the_window_and_ends_on_the_water_surface_view(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow
    from easyfoam.runtime import detect_runtimes

    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    window = MainWindow(enable_3d=False, detect=False)
    window.notices = []
    window.notify = lambda title, text, level="info": window.notices.append((level, text))
    window.runtime = found[0]
    window.create_project("dam", tmp_path, "dambreak")
    assert window.steps.item(2).data(0x0102) == "Free surface, laminar"  # DETAIL_ROLE of the Physics step
    window.project.run.end_time, window.project.run.write_interval = 0.1, 0.05
    window.generate_mesh()
    wait_for_job(qapp, window)
    window.run_solver()
    wait_for_job(qapp, window)
    assert window.notices == []
    assert window.run_panel.status.text() == "Run finished."
    fields = [window.results_panel.field.itemData(i) for i in range(window.results_panel.field.count())]
    assert "alpha.water" in fields
    assert window.results_panel.mode.currentData() == "water"
    assert window.results_panel.field.currentData() == "U"  # the surface is coloured by speed
    assert {"p_rgh"} <= set(window._curves)
    window.close()


def test_dam_break_example_is_complete_enough_to_pass_the_checks():
    from easyfoam.casegen.mesh import predicted_patches
    from easyfoam.checks import project_issues

    project = dambreak("d")
    assert [i.text for i in project_issues(project, predicted_patches(project), True)] == []
