"""v0.11 in the window: tracers and water age, per-inlet doses, the tracer test and its results."""

import pytest

pytest.importorskip("PySide6")

import numpy as np  # noqa: E402

from easyfoam.foam.boundaryfile import Patch  # noqa: E402
from easyfoam.model import Boundary, Project, Tracer  # noqa: E402

pytestmark = pytest.mark.gui

PATCHES = [Patch("inlet", "patch", 1, 0), Patch("outlet", "patch", 1, 1), Patch("walls", "wall", 1, 2)]


def steady_project():
    p = Project(name="tank")
    p.physics.solver, p.physics.turbulence = "simpleFoam", "kOmegaSST"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1.0e-06, 998.0
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[0.1, 0, 0], tracer_value=2.0)
    p.boundaries["outlet"] = Boundary(kind="pressureOutlet")
    return p


# --- tracers in the Physics step ------------------------------------------------------------


def test_tracers_and_the_water_age_are_added_edited_and_removed(qapp):
    from easyfoam.gui.panels import PhysicsPanel

    project = steady_project()
    panel = PhysicsPanel()
    panel.load(project)
    assert panel.tracer_table.rowCount() == 0
    panel.add_age_button.click()
    panel.add_tracer_button.click()
    assert [(t.name, t.kind) for t in project.tracers] == [("age", "age"), ("tracer", "concentration")]
    assert panel.tracer_table.item(0, 1).text() == "age of the water"
    # typing in the table: a name and a decay per hour (chlorine loses 30 % an hour)
    panel.tracer_table.item(1, 0).setText("chlorine")
    panel.tracer_table.item(1, 3).setText("0,3")  # a decimal comma is accepted
    chlorine = project.tracers[1]
    assert chlorine.name == "chlorine" and chlorine.decay == pytest.approx(0.3 / 3600)
    assert "Half-life 2.31 h" in panel.tracer_table.item(1, 3).toolTip()
    panel.tracer_table.item(1, 3).setText("fast")  # not a number: the table shows the value kept
    assert panel.tracer_table.item(1, 3).text() == "0.3" and chlorine.decay == pytest.approx(0.3 / 3600)
    panel.add_tracer("chlorine")  # names stay unique
    assert project.tracers[2].name == "chlorine2"
    panel.tracer_table.setCurrentCell(0, 0)
    panel.remove_tracer_button.click()
    assert [t.name for t in project.tracers] == ["chlorine", "chlorine2"]


# --- doses at the inlets, Boundaries step -----------------------------------------------------


def test_each_inlet_doses_each_tracer_with_its_own_concentration(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = steady_project()
    project.tracers = [Tracer("age", 1e-9, kind="age"), Tracer("chlorine", 1e-9)]
    panel = BoundaryPanel()
    panel.load(project, PATCHES)
    panel.patch_list.setCurrentRow(0)  # the inlet
    # one concentration (the age needs no dose): a single field
    assert panel.form.isRowVisible(panel.tracer_value) and not panel.form.isRowVisible(panel.tracer_inlet)
    project.tracers.append(Tracer("dye", 1e-9))
    panel.load(project, PATCHES)
    panel.patch_list.setCurrentRow(0)
    assert panel.form.isRowVisible(panel.tracer_inlet) and not panel.form.isRowVisible(panel.tracer_value)
    assert [panel.tracer_inlet.item(r, 0).text() for r in range(panel.tracer_inlet.rowCount())] == ["chlorine", "dye"]
    assert panel.tracer_inlet.item(0, 1).text() == "2"  # the common value until set
    panel.tracer_inlet.item(1, 1).setText("5")
    assert project.boundaries["inlet"].tracer_values == {"dye": 5.0}
    assert project.boundaries["inlet"].velocity == [0.1, 0, 0]  # the rest of the inlet is kept
    panel.patch_list.setCurrentRow(1)  # an outlet doses nothing
    assert not panel.form.isRowVisible(panel.tracer_inlet) and not panel.form.isRowVisible(panel.tracer_value)


# --- the tracer test, Run step ------------------------------------------------------------------


def test_the_tracer_test_is_set_up_in_the_run_step(qapp):
    from easyfoam.examples import tank
    from easyfoam.gui.panels import RunPanel

    project = tank("tank")
    panel = RunPanel()
    panel.load(project)
    assert panel.test_box.isEnabled()
    assert panel.test_inlet.currentText() == "inlet" and panel.test_outlet.currentText() == "outlet"
    panel.test_kind.setCurrentIndex(panel.test_kind.findData("pulse"))
    panel.test_duration.set_value(20000.0)
    settings = panel.test_settings()
    assert (settings.inlet, settings.outlet, settings.kind, settings.duration) == ("inlet", "outlet", "pulse", 20000.0)


def test_the_tracer_test_is_not_offered_for_free_surface_runs(qapp):
    from easyfoam.examples import weir
    from easyfoam.gui.panels import RunPanel

    panel = RunPanel()
    panel.load(weir("weir"))
    assert not panel.test_box.isEnabled() and "frictionless lid" in panel.test_box.toolTip()


# --- the residence times, Results step --------------------------------------------------------


def recorded_test(case_dir, tau=3600.0):
    """A finished step test of a perfectly mixed tank, as OpenFOAM would have written it."""
    from easyfoam import tracertest as tt

    target = tt.subcase(case_dir)
    folder = target / "postProcessing" / "tracerOut_outlet" / "0"
    folder.mkdir(parents=True)
    t = np.linspace(0, 6 * tau, 601)[1:]
    rows = "\n".join(f"{a:.6g}\t{1 - np.exp(-a / tau):.8g}" for a in t)
    (folder / "surfaceFieldValue.dat").write_text(f"# Time\tweightedAverage(rtd)\n{rows}\n")
    record = {"inlet": "inlet", "outlet": "outlet", "kind": "step", "duration": 6 * tau, "pulse": tau / 50,
              "theoretical": tau}  # fmt: skip
    import json

    (target / tt.SETTINGS_FILE).write_text(json.dumps(record))


def test_residence_times_are_shown_after_reopening_the_project(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    project = steady_project()
    project.tracers = [Tracer("age", 1e-9, kind="age"), Tracer("chlorine", 1e-9, decay=0.3 / 3600)]
    project.save(tmp_path / "case")
    recorded_test(tmp_path / "case")
    window = MainWindow(enable_3d=False, detect=False)
    window.notify = lambda *args, **kw: None
    window.open_project(tmp_path / "case")
    window.hydraulics("residence")
    text = window.results_panel.hydraulics_info.text()
    assert text.startswith("Tracer test (step) from inlet to outlet")
    assert "Baffling factor T10/(V/Q) = 0.11 (unbaffled, mixed flow)" in text
    assert "chlorine, decaying at 0.3 per hour: 76.9 % is left at the outlet (1.54 of the 2 dosed)" in text
    if window.hydraulics_view is not None:
        assert [item.name() for item in window.upper_plot.listDataItems()] == ["F(t): has left"]
    saved = window.export_table(tmp_path / "rtd.csv")
    assert saved.read_text().splitlines()[0].startswith("time [s],outlet concentration")
    window.close()


# --- the example -----------------------------------------------------------------------------


def test_the_contact_tank_is_one_of_the_examples(qapp):
    from easyfoam.gui import icons
    from easyfoam.gui.main_window import EXAMPLE_LABELS, MainWindow
    from easyfoam.gui.welcome import EXAMPLES, SHOWN, WelcomePage

    assert SHOWN[-1] == "tank" and EXAMPLES["tank"][0] in icons.names() and "flow-tank" in icons.USED
    page = WelcomePage()
    assert "Contact tank" in page.example_buttons["tank"].text()
    window = MainWindow(enable_3d=False, detect=False)
    labels = [a.text() for menu in window.menuBar().findChildren(type(window.menuBar().actions()[0].menu()))
              for a in menu.actions()]  # fmt: skip
    assert EXAMPLE_LABELS["tank"] in labels
    window.close()
