import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvista")

import numpy as np  # noqa: E402

from easyfoam.results import CaseData  # noqa: E402
from tests.test_v09_core import channel_project, channel_result, hydrostatic, weir_faces  # noqa: E402

pytestmark = pytest.mark.gui


class FakeResults:
    """Saved results without OpenFOAM: a channel with a weir, the same at every saved time."""

    def __init__(self, project, fields=("U", "alpha.water", "p", "p_rgh")):
        self.project = project
        self.times = [0.0, 1.0, 2.0]
        self.fields = list(fields)

    def read(self, time=None):
        data = channel_result(self.project, lambda x: 0.5 - 0.02 * x, q=0.2)
        weir = hydrostatic(weir_faces())
        weir.cell_data["wallShearStress"] = np.tile([0.004, 0.0, 0.0], (weir.n_cells, 1))
        weir.cell_data["alpha.water"] = np.ones(weir.n_cells)
        return CaseData(data.internal, {"weir": weir})


def window_with_results(qapp, tmp_path, monkeypatch, **kwargs):
    from easyfoam.foam.boundaryfile import Patch
    from easyfoam.gui.main_window import MainWindow

    window = MainWindow(enable_3d=False, detect=False)
    window.notify = lambda *args, **kw: None
    project = channel_project()
    project.save(tmp_path / "case")
    window.open_project(tmp_path / "case")
    fake = FakeResults(window.project, **kwargs)
    monkeypatch.setattr(window, "_case_results", lambda: fake)
    monkeypatch.setattr(window, "mesh_patches", lambda: [Patch("weir", "wall", 1, 0), Patch("inlet", "patch", 1, 1)])
    window.reload_results(show=False)
    return window


def test_the_results_step_offers_hydraulic_results_for_free_surface_runs(qapp, tmp_path, monkeypatch):
    window = window_with_results(qapp, tmp_path, monkeypatch)
    panel = window.results_panel
    assert panel.long_button.isEnabled() and panel.pressure_button.isEnabled()
    assert [panel.structure.itemText(i) for i in range(panel.structure.count())] == ["weir"]  # walls only
    assert not panel.export_button.isEnabled()  # nothing to save yet
    assert panel.chosen_point() is None
    panel.at_toe.setChecked(False)
    panel.moment_point.set_value([3.0, 0.5, 0.4])
    assert panel.chosen_point() == [3.0, 0.5, 0.4]
    window.close()


def test_a_long_section_is_plotted_summarised_and_saved(qapp, tmp_path, monkeypatch):
    window = window_with_results(qapp, tmp_path, monkeypatch)
    window.results_panel.long_button.click()
    assert window.bottom.tabText(window.bottom.currentIndex()) == "Hydraulics"
    assert "Discharge 0.2 m³/s" in window.results_panel.hydraulics_info.text()
    assert window.results_panel.export_button.isEnabled()
    if window.hydraulics_view is not None:
        names = [item.name() for item in window.upper_plot.listDataItems()]
        assert names == ["bed", "water level", "energy line"] and window.lower_plot.isVisible()
    saved = window.export_table(tmp_path / "long.csv")
    assert saved.read_text().splitlines()[0].startswith("chainage [m]")
    window.close()


def test_pressure_along_a_structure_and_its_loads(qapp, tmp_path, monkeypatch):
    window = window_with_results(qapp, tmp_path, monkeypatch)
    panel = window.results_panel
    panel.pressure_button.click()
    assert "lowest pressure head" in panel.hydraulics_info.text()
    panel.loads_button.click()
    text = panel.hydraulics_info.text()
    assert "Horizontal force along the flow" in text and "kN/m" in text
    rows = window._table.rows
    assert [row[0] for row in rows] == [1.0, 2.0]  # every saved time after the start
    assert rows[0][1] == pytest.approx(998 * 9.81 * 0.10 / 1000, rel=2e-3)  # kN per metre width
    if window.hydraulics_view is not None:
        assert len(window.upper_plot.listDataItems()) == 2
    window.close()


def test_bed_shear_stress_is_shown_on_the_walls_with_the_sediment_mobility(qapp, tmp_path, monkeypatch):
    window = window_with_results(qapp, tmp_path, monkeypatch, fields=("U", "alpha.water", "p", "wallShearStress"))
    fields = [window.results_panel.field.itemData(i) for i in range(window.results_panel.field.count())]
    assert {"bedShearStress", "sedimentMobility"} <= set(fields)
    data = window._case_results().read(1.0)
    window.results_panel.d50.set_value(1.0)
    window._add_bed_shear(data)
    stress = data.patches["weir"].cell_data["bedShearStress"]
    assert stress[0] == pytest.approx(998 * 0.004)
    assert data.patches["weir"].cell_data["sedimentMobility"][0] == pytest.approx(998 * 0.004 / 0.51, rel=0.06)
    assert "starts to move above" in window.results_panel.info.text()
    window.close()


def test_the_jump_example_is_offered(qapp):
    from easyfoam.gui.main_window import EXAMPLE_LABELS
    from easyfoam.gui.welcome import WelcomePage

    assert "jump" in EXAMPLE_LABELS and "jump" in WelcomePage().example_buttons
