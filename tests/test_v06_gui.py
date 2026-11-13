import pytest

pytest.importorskip("PySide6")

from easyfoam.foam.boundaryfile import Patch  # noqa: E402
from easyfoam.model import Project, Tracer  # noqa: E402
from tests.test_gui import select, type_into, wait_for_job  # noqa: E402

pytestmark = pytest.mark.gui


def test_physics_panel_offers_the_new_turbulence_models_and_wall_treatment(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    panel = PhysicsPanel()
    panel.load(project)
    for model in ("RNGkEpsilon", "kOmega", "kkLOmega"):
        assert panel.turbulence.findData(model) >= 0
    select(panel.wall_treatment, "lowRe")
    type_into(panel.max_velocity, "25")
    assert project.physics.wall_treatment == "lowRe" and project.physics.max_velocity == 25.0


def test_choosing_a_non_newtonian_fluid_lists_its_coefficients_for_editing(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    panel = PhysicsPanel()
    panel.load(project)
    assert panel.coeff_table.rowCount() == 0 and panel.nu.isEnabled()
    select(panel.viscosity_model, "HerschelBulkley")
    assert project.physics.viscosity_model == "HerschelBulkley"
    assert set(project.physics.viscosity_coeffs) == {"k", "n", "tau0", "nu0"}
    assert panel.coeff_table.rowCount() == 4 and not panel.nu.isEnabled()
    panel.set_coefficient("tau0", 2.5)
    assert project.physics.viscosity_coeffs["tau0"] == 2.5
    select(panel.viscosity_model, "Newtonian")
    assert project.physics.viscosity_coeffs == {} and panel.nu.isEnabled()


def test_tracer_and_adaptive_refinement_settings(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = Project(name="x")
    project.physics.solver = "interFoam"
    panel = PhysicsPanel()
    panel.load(project)
    panel.add_tracer("dye")
    panel.set_tracer(0, diffusivity=1e-6)
    assert project.tracers == [Tracer("dye", 1e-06)]
    panel.remove_tracer(0)
    assert project.tracers == []
    panel.adaptive.setValue(2)
    assert project.physics.adaptive_levels == 2


def test_wall_contact_angle_and_inlet_tracer_value_appear_when_they_apply(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = Project(name="x")
    patches = [Patch("inlet", "patch", 1, 0), Patch("bed", "wall", 1, 1)]
    panel = BoundaryPanel()
    panel.load(project, patches)
    panel.patch_list.setCurrentRow(1)
    assert not panel.form.isRowVisible(panel.contact_angle)  # single fluid: no water surface
    panel.patch_list.setCurrentRow(0)
    assert not panel.form.isRowVisible(panel.tracer_value)  # no tracer defined

    project.physics.solver = "interFoam"
    project.tracers = [Tracer("dye")]
    panel.load(project, patches)
    panel.patch_list.setCurrentRow(0)
    assert panel.form.isRowVisible(panel.tracer_value)
    type_into(panel.tracer_value, "1")
    assert project.boundaries["inlet"].tracer_value == 1.0
    panel.patch_list.setCurrentRow(1)
    assert panel.form.isRowVisible(panel.contact_angle)
    type_into(panel.contact_angle, "60")
    assert project.boundaries["bed"].contact_angle == 60.0


def test_wave_maker_offers_five_theories_and_a_solitary_wave_has_no_period(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = Project(name="x")
    project.physics.solver = "interFoam"
    panel = BoundaryPanel()
    panel.load(project, [Patch("inlet", "patch", 1, 0)])
    select(panel.kind, "waveInlet")
    assert panel.wave_model.count() == 5 and panel.form.isRowVisible(panel.wave_period)
    select(panel.wave_model, "solitary")
    assert project.boundaries["inlet"].wave_model == "solitary"
    assert not panel.form.isRowVisible(panel.wave_period)


@pytest.mark.openfoam
def test_cavitation_index_is_offered_for_free_surface_results(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow
    from easyfoam.runtime import detect_runtimes

    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    window = MainWindow(enable_3d=False, detect=False)
    window.runtime = found[0]
    window.create_project("dam", tmp_path, "dambreak")
    window.project.run.end_time, window.project.run.write_interval = 0.05, 0.05
    window.generate_mesh()
    wait_for_job(qapp, window)
    window.run_solver()
    wait_for_job(qapp, window)
    fields = [window.results_panel.field.itemData(i) for i in range(window.results_panel.field.count())]
    assert "cavitationIndex" in fields and "p" in fields
    window.close()
