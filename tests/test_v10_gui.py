import pytest

pytest.importorskip("PySide6")

from easyfoam.foam.boundaryfile import Patch  # noqa: E402
from easyfoam.model import Boundary, Project  # noqa: E402
from tests.test_gui import select, type_into  # noqa: E402

pytestmark = pytest.mark.gui

PATCHES = [Patch("inlet", "patch", 1, 0), Patch("outlet", "patch", 1, 1), Patch("bed", "wall", 1, 2)]


def free_surface_project():
    p = Project(name="x")
    p.physics.solver, p.physics.turbulence = "interFoam", "kOmegaSST"
    p.physics.material, p.physics.rho = "water", 998.0
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.01)
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=0.3)
    return p


def boundary_panel(project):
    from easyfoam.gui.panels import BoundaryPanel

    panel = BoundaryPanel()
    panel.load(project, PATCHES)
    return panel


# --- roughness --------------------------------------------------------------------------


def test_a_wall_can_be_given_a_manning_n_or_a_sand_grain_height(qapp):
    project = free_surface_project()
    panel = boundary_panel(project)
    panel.patch_list.setCurrentRow(2)  # bed
    form = panel.form
    assert form.isRowVisible(panel.roughness) and not form.isRowVisible(panel.manning)
    select(panel.roughness, "manning")
    type_into(panel.manning, "0.017")
    assert (project.boundaries["bed"].roughness, project.boundaries["bed"].manning) == ("manning", 0.017)
    assert form.isRowVisible(panel.manning) and "7.18 mm" in panel.roughness_hint.text()
    select(panel.roughness, "ks")
    type_into(panel.ks_mm, "2")
    assert project.boundaries["bed"].ks == pytest.approx(0.002) and "Manning's n = 0.0137" in panel.roughness_hint.text()
    panel.patch_list.setCurrentRow(0)  # an inlet has no roughness
    assert not form.isRowVisible(panel.roughness)


# --- time series ------------------------------------------------------------------------


def test_an_inflow_hydrograph_is_set_kept_and_cleared(qapp):
    project = free_surface_project()
    panel = boundary_panel(project)
    panel.patch_list.setCurrentRow(0)
    assert panel.form.isRowVisible(panel.flow_series_button) and not panel.form.isRowVisible(panel.flow_series_hint)
    panel.set_flow_series([[0, 0.01], [30, 0.05], [90, 0.01]])
    inlet = project.boundaries["inlet"]
    assert inlet.flow_series == [[0.0, 0.01], [30.0, 0.05], [90.0, 0.01]]
    assert "3 points from 0 s to 90 s" in panel.flow_series_hint.text() and not panel.flow_rate.isEnabled()
    type_into(panel.flow_rate, "0.02")  # editing another value keeps the hydrograph
    assert project.boundaries["inlet"].flow_series and project.boundaries["inlet"].flow_rate == 0.02
    panel.set_flow_series([])
    assert project.boundaries["inlet"].flow_series == [] and panel.flow_rate.isEnabled()


def test_the_series_dialog_reads_pasted_columns_and_refuses_times_that_go_back(qapp):
    from easyfoam.gui.series import SeriesDialog, parse_pairs, preset_series, series_problem

    assert parse_pairs("time\tQ\n0\t0.01\n10;0.02\n20, 0.03\n") == [[0, 0.01], [10, 0.02], [20, 0.03]]
    assert series_problem([[0, 1], [0, 2]], True) == "the times must increase from row to row"
    assert series_problem([[0, -1], [5, 2]], True) == "the values cannot be negative"
    assert series_problem([[0, -1], [5, 2]], False) is None  # a level may be negative
    assert preset_series("flood", 0.01, 0.05, 90) == [[0.0, 0.01], [30.0, 0.05], [90, 0.01]]
    dialog = SeriesDialog([], "Inflow hydrograph", "m³/s", 0.02, duration=60)
    assert dialog.values() == [[0.0, 0.02], [60.0, 0.02]] and dialog.ok.isEnabled()
    dialog.set_series([[0, 0.01], [10, 0.02], [5, 0.03]])
    assert not dialog.ok.isEnabled() and "increase" in dialog.status.text()


# --- rating curves ----------------------------------------------------------------------


def test_a_rating_run_is_set_up_from_the_run_step(qapp):
    from easyfoam.gui.panels import RunPanel

    project = free_surface_project()
    project.probes = [[1.0, 0.25, 0.3]]
    panel = RunPanel()
    panel.load(project)
    assert panel.rating_box.isEnabled()
    text = panel.setup_rating([0.02, 0.04, 0.06], hold=12)
    assert project.rating.discharges == [0.02, 0.04, 0.06] and project.rating.inlet == "inlet"
    assert project.boundaries["inlet"].flow_series[:3] == [[0.0, 0.02], [12, 0.02], [13, 0.04]]
    assert project.run.end_time == 36 and "ends at 36 s" in text
    assert panel.rating_discharges.text() == "0.02, 0.04, 0.06"
    with pytest.raises(ValueError, match="two discharges"):
        panel.setup_rating([0.02], hold=12)
    project.probes = []
    with pytest.raises(ValueError, match="probe"):
        panel.setup_rating([0.02, 0.04], hold=12)


def test_rating_curves_are_only_offered_for_free_surface_runs(qapp):
    from easyfoam.gui.panels import RunPanel

    project = Project(name="x")
    panel = RunPanel()
    panel.load(project)
    assert not panel.rating_box.isEnabled()


def test_the_rating_curve_is_plotted_from_the_gauge_record(qapp, tmp_path, monkeypatch):
    pytest.importorskip("pyvista")
    from easyfoam import hydraulics as hy
    from tests.test_v09_gui import window_with_results

    window = window_with_results(qapp, tmp_path, monkeypatch)
    window.project.rating.discharges = [0.02, 0.04]
    fake = [hy.RatingPoint(0.02, 0.6, 0.09, 0.02, 1.48, 0.5, 0.0, True),
            hy.RatingPoint(0.04, 0.65, 0.14, 0.04, 1.53, 0.52, 0.003, False)]  # fmt: skip
    monkeypatch.setattr(hy, "rating_curve", lambda project, case_dir: fake)
    window.results_panel.rating_button.click()
    text = window.results_panel.hydraulics_info.text()
    assert "Q 0.02 m³/s: head 0.09 m, C = 1.48" in text and "not settled" in text
    assert window._table.rows[1][:3] == [0.04, 0.65, 0.14]
    window.close()
