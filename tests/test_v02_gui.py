import pytest

pytest.importorskip("PySide6")

from easyfoam.examples import sphere  # noqa: E402
from easyfoam.model import Project, Shape  # noqa: E402
from tests.test_gui import Counter, select, type_into, wait_for_job  # noqa: E402

pytestmark = pytest.mark.gui


def test_physics_panel_switches_the_potential_flow_start(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    panel = PhysicsPanel()
    panel.load(project)
    panel.potential.setChecked(True)
    assert project.physics.potential_init is True
    assert panel.turbulence.findData("SpalartAllmaras") >= 0


def test_run_panel_edits_the_convergence_target_and_the_force_monitor(qapp):
    from easyfoam.gui.panels import RunPanel

    project = Project(name="x")
    panel = RunPanel()
    panel.load(project)
    type_into(panel.residual_target, "1e-6")
    panel.forces_on.setChecked(True)
    type_into(panel.ref_area, "2.2")
    type_into(panel.ref_length, "4.5")
    type_into(panel.ref_velocity, "30")
    type_into(panel.lift_dir.edits[1], "1")
    type_into(panel.force_patches, "body, wheels")
    assert project.run.residual_target == 1e-6
    f = project.forces
    assert (f.enabled, f.ref_area, f.ref_length, f.ref_velocity) == (True, 2.2, 4.5, 30.0)
    assert f.lift_dir == [0.0, 1.0, 1.0]
    assert f.patches == ["body", "wheels"]


def test_force_settings_are_greyed_out_while_the_monitor_is_off(qapp):
    from easyfoam.gui.panels import RunPanel

    panel = RunPanel()
    panel.load(Project(name="x"))
    assert panel.ref_area.isEnabled() is False
    panel.forces_on.setChecked(True)
    assert panel.ref_area.isEnabled() is True


def test_mesh_panel_offers_each_solid_shape_as_the_place_where_the_fluid_is(qapp):
    from easyfoam.gui.panels import MeshPanel

    project = Project(name="x")
    project.shapes += [Shape("tube", kind="cylinder"), Shape("wake", kind="box", role="refinement")]
    panel = MeshPanel()
    panel.load(project)
    choices = [panel.fluid_region.itemData(i) for i in range(panel.fluid_region.count())]
    assert choices == ["", "tube"]  # refinement regions are not containers
    select(panel.fluid_region, "tube")
    assert project.mesh.fluid_inside == "tube"


def test_geometry_panel_sets_refinement_near_a_surface(qapp):
    from easyfoam.gui.panels import GeometryPanel

    project = sphere("s")
    panel = GeometryPanel()
    panel.load(project, None)
    panel.shape_list.setCurrentRow(0)
    type_into(panel.near_distance, "0.4")
    panel.near_level.setValue(2)
    assert (project.shapes[0].near_distance, project.shapes[0].near_level) == (0.4, 2)


def test_geometry_panel_lets_each_stl_region_be_an_opening_or_a_wall(qapp):
    from easyfoam.gui.panels import GeometryPanel

    project = Project(name="x")
    project.shapes.append(Shape("duct", file="duct.stl", regions={"inlet": "wall", "wall": "wall"}))
    panel = GeometryPanel()
    panel.load(project, None)
    hits = Counter(panel.changed)
    assert panel.regions.rowCount() == 2
    panel.set_region_type("inlet", "patch")
    assert project.shapes[0].regions == {"inlet": "patch", "wall": "wall"}
    assert hits.count == 1


def test_results_panel_asks_for_a_derived_quantity(qapp):
    from easyfoam.gui.panels import ResultsPanel

    panel = ResultsPanel()
    asked = []
    panel.compute_requested.connect(asked.append)
    select(panel.function, "yPlus")
    panel.compute.click()
    assert asked == ["yPlus"]


def test_window_plots_the_force_history_of_the_last_run_when_a_case_is_opened(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow
    from tests.test_v02_core import COEFFS

    project = Project(name="p")
    project.forces.enabled = True
    project.forces.ref_area = 2.0
    project.physics.initial_velocity = [10.0, 0.0, 0.0]
    project.save(tmp_path)
    folder = tmp_path / "postProcessing" / "forceCoeffs" / "0"
    folder.mkdir(parents=True)
    (folder / "coefficient.dat").write_text(COEFFS)
    window = MainWindow(enable_3d=False, detect=False)
    window.open_project(tmp_path)
    assert set(window._force_curves) == {"Cd", "Cl"}
    xs, ys = window._force_curves["Cd"].getData()
    assert list(xs) == [1.0, 2.0] and list(ys) == [0.51, 0.40]
    # drag force = Cd * 1/2 rho U^2 A = 0.40 * 0.5 * 1.2 * 100 * 2.0 = 48 N
    assert "Cd = 0.4" in window.force_label.text() and "48" in window.force_label.text()
    window.close()


def test_new_from_example_offers_the_pipe(qapp):
    from easyfoam.gui.main_window import EXAMPLE_LABELS

    assert "pipe" in EXAMPLE_LABELS


@pytest.mark.openfoam
def test_window_computes_a_derived_quantity_after_a_run(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow
    from easyfoam.runtime import detect_runtimes

    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    window = MainWindow(enable_3d=False, detect=False)
    window.runtime = found[0]
    window.new_project(tmp_path / "cavity", "cavity")
    window.project.run.end_time, window.project.run.write_interval = 10, 10
    window.generate_mesh()
    wait_for_job(qapp, window)
    window.run_solver()
    wait_for_job(qapp, window)

    window.compute_quantity("vorticity")
    wait_for_job(qapp, window)
    fields = [window.results_panel.field.itemData(i) for i in range(window.results_panel.field.count())]
    assert "vorticity" in fields
    assert window.results_panel.field.currentData() == "vorticity"
    window.close()


def test_a_wall_that_spans_the_whole_domain_is_treated_as_an_enclosure(qapp):
    from easyfoam.gui.viewer import is_enclosure

    domain = (0, 2, -0.1, 0.1, -0.1, 0.1)
    assert is_enclosure((0, 2, -0.1, 0.1, -0.1, 0.1), domain) is True  # pipe wall
    tunnel = (-3, 7, -2.5, 2.5, -2.5, 2.5)
    assert is_enclosure((-0.5, 0.5, -0.5, 0.5, -0.5, 0.5), tunnel) is False  # body in a wind tunnel
