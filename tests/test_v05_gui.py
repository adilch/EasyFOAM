import pytest

pytest.importorskip("PySide6")

from easyfoam.examples import weir  # noqa: E402
from easyfoam.foam.boundaryfile import Patch  # noqa: E402
from easyfoam.geometry import stl_bounds  # noqa: E402
from easyfoam.model import Project  # noqa: E402
from tests.test_gui import select, type_into  # noqa: E402
from tests.test_v02_core import ascii_stl, cube  # noqa: E402
from tests.test_v05_core import DISCHARGE, HEIGHT  # noqa: E402

pytestmark = pytest.mark.gui


def free_surface_project():
    project = Project(name="x")
    project.physics.solver = "interFoam"
    return project


def test_water_level_outlet_asks_for_the_tailwater_level(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = free_surface_project()
    panel = BoundaryPanel()
    panel.load(project, [Patch("outlet", "patch", 1, 0)])
    select(panel.kind, "waterLevelOutlet")
    type_into(panel.level, "0.45")
    assert project.boundaries["outlet"].kind == "waterLevelOutlet"
    assert project.boundaries["outlet"].level == 0.45
    assert panel.form.isRowVisible(panel.level) and not panel.form.isRowVisible(panel.wave_height)


def test_wave_maker_asks_for_height_period_and_theory(qapp):
    from easyfoam.gui.panels import BoundaryPanel

    project = free_surface_project()
    panel = BoundaryPanel()
    panel.load(project, [Patch("inlet", "patch", 1, 0)])
    select(panel.kind, "waveInlet")
    type_into(panel.wave_height, "0.1")
    type_into(panel.wave_period, "2.5")
    select(panel.wave_model, "StokesI")
    wave = project.boundaries["inlet"]
    assert (wave.kind, wave.wave_height, wave.wave_period, wave.wave_model) == ("waveInlet", 0.1, 2.5, "StokesI")
    assert not panel.form.isRowVisible(panel.level)
    select(panel.kind, "waveOutlet")
    assert not panel.form.isRowVisible(panel.wave_height)


def test_run_panel_chooses_the_boundaries_whose_discharge_is_recorded(qapp):
    from easyfoam.gui.panels import RunPanel

    project = Project(name="x")
    panel = RunPanel()
    panel.load(project)
    type_into(panel.flow_monitors, "inlet,  outlet")
    assert project.flow_monitors == ["inlet", "outlet"]
    project.flow_monitors = ["spillway"]
    panel.load(project)
    assert panel.flow_monitors.text() == "spillway"


def test_geometry_is_imported_in_the_unit_the_file_was_drawn_in(qapp, tmp_path):
    from easyfoam.gui.panels import GeometryPanel

    source = tmp_path / "gate.stl"
    source.write_text(ascii_stl({"gate": cube(scale=(1500, 100, 800))}))
    project = Project(name="x")
    panel = GeometryPanel()
    panel.load(project, tmp_path / "case")
    panel.import_file(source, unit="mm")
    assert [s.name for s in project.shapes] == ["gate"]
    lo, hi = stl_bounds(tmp_path / "case" / "constant" / "triSurface" / "gate.stl")
    assert hi == pytest.approx([1.5, 0.1, 0.8])
    assert "gate" in panel.shape_list.item(0).text()


def test_a_step_file_can_be_imported_with_each_face_as_its_own_boundary(qapp, tmp_path):
    from easyfoam.gui.panels import GeometryPanel
    from tests.test_v05_core import step_box

    step_box(tmp_path / "chute.step")
    project = Project(name="x")
    panel = GeometryPanel()
    panel.load(project, tmp_path / "case")
    panel.import_file(tmp_path / "chute.step", unit="m", faces_as_regions=True)
    assert len(project.shapes[0].regions) == 6
    assert panel.regions.rowCount() == 6


def test_window_plots_water_depth_at_the_gauges_and_discharge_per_boundary(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    project = weir("weir")
    project.save(tmp_path)
    for folder, name, text in (("waterLevel", "height.dat", HEIGHT), ("flow_outlet", "surfaceFieldValue.dat", DISCHARGE)):
        target = tmp_path / "postProcessing" / folder / "0"
        target.mkdir(parents=True)
        (target / name).write_text(text)
    window = MainWindow(enable_3d=False, detect=False)
    window.open_project(tmp_path)
    tabs = [window.bottom.tabText(i) for i in range(window.bottom.count())]
    assert "Discharge" in tabs
    assert len(window._probe_curves) == 2
    _xs, depth = window._probe_curves[1].getData()
    assert list(depth) == [0.4, 0.392632556]
    assert set(window._flow_curves) == {"outlet"}
    assert "outlet" in window.flow_label.text() and "0.01168" in window.flow_label.text()
    window.close()


def test_wave_flume_example_is_offered(qapp):
    from easyfoam.gui.main_window import EXAMPLE_LABELS
    from easyfoam.gui.welcome import WelcomePage

    assert "waves" in EXAMPLE_LABELS and "waves" in WelcomePage().example_buttons
