import pytest

pytest.importorskip("PySide6")

from easyfoam.model import Motion, Project, Shape  # noqa: E402
from tests.test_gui import select, type_into, wait_for_job  # noqa: E402

pytestmark = pytest.mark.gui


def geometry_panel(tmp_path, *shapes):
    from easyfoam.gui.panels import GeometryPanel

    project = Project(name="x")
    project.shapes.extend(shapes)
    panel = GeometryPanel()
    panel.load(project, tmp_path)
    return project, panel


def test_a_shape_is_fixed_until_a_motion_is_chosen_and_only_the_matching_inputs_show(qapp, tmp_path):
    project, panel = geometry_panel(tmp_path, Shape("gate", kind="box", min=[0, 0, 0.1], max=[0.1, 1, 0.8]))
    form = panel.form
    assert panel.motion_kind.currentData() == "none"
    for widget in (panel.motion_displacement, panel.motion_period, panel.motion_density, panel.motion_freedom):
        assert not form.isRowVisible(widget)

    select(panel.motion_kind, "move")
    assert project.shapes[0].motion.kind == "move"
    assert form.isRowVisible(panel.motion_displacement) and form.isRowVisible(panel.motion_duration)
    assert not form.isRowVisible(panel.motion_period) and not form.isRowVisible(panel.motion_density)
    panel.motion_displacement.set_value([0.0, 0.0, 0.25])
    panel.motion_displacement.changed.emit()
    type_into(panel.motion_start, "0.5")
    type_into(panel.motion_duration, "2")
    assert project.shapes[0].motion == Motion(kind="move", displacement=[0.0, 0.0, 0.25], start=0.5, duration=2.0)

    select(panel.motion_kind, "oscillate")
    assert form.isRowVisible(panel.motion_amplitude) and form.isRowVisible(panel.motion_period)
    assert not form.isRowVisible(panel.motion_displacement)
    type_into(panel.motion_period, "4")
    assert project.shapes[0].motion.period == 4.0


def test_a_floating_body_asks_for_density_and_freedom_and_shows_its_mass(qapp, tmp_path):
    project, panel = geometry_panel(tmp_path, Shape("box", kind="box", min=[0, 0, 0], max=[0.3, 0.3, 0.12]))
    select(panel.motion_kind, "floating")
    assert panel.form.isRowVisible(panel.motion_density) and panel.form.isRowVisible(panel.motion_freedom)
    assert "5.4 kg" in panel.motion_mass.text()  # 0.0108 m3 at the default 500 kg/m3
    type_into(panel.motion_density, "250")
    select(panel.motion_freedom, "free")
    assert (project.shapes[0].motion.density, project.shapes[0].motion.freedom) == (250.0, "free")
    assert "2.7 kg" in panel.motion_mass.text()
    assert "floats" in panel.shape_list.item(0).text()  # the list shows which shapes move


def test_refinement_regions_cannot_move(qapp, tmp_path):
    _project, panel = geometry_panel(tmp_path, Shape("zone", kind="box", role="refinement"))
    assert not panel.form.isRowVisible(panel.motion_kind)


def test_the_gate_and_the_floating_box_are_offered_as_examples(qapp):
    from easyfoam.gui import icons
    from easyfoam.gui.main_window import EXAMPLE_LABELS
    from easyfoam.gui.welcome import EXAMPLES, WelcomePage

    buttons = WelcomePage().example_buttons
    for key in ("gate", "floating"):
        assert key in EXAMPLE_LABELS and key in buttons
        assert EXAMPLES[key][0] in icons.names() and EXAMPLES[key][0] in icons.USED


def test_the_motion_tab_follows_a_floating_body_and_a_moved_gate(qapp, tmp_path):
    from easyfoam.foam.logparser import LogParser
    from easyfoam.gui.main_window import MainWindow

    window = MainWindow(enable_3d=False, detect=False)
    if window.motion_plot is None:
        pytest.skip("pyqtgraph is not installed")
    window.create_project("float", tmp_path, "floating")
    parser = LogParser()
    for line in (
        "Time = 0.1",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.43)",
        "    Orientation: (1 0 0 0 1 0 0 0 1)",
        "Time = 0.2",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.41)",
        "    Orientation: (1 0 0 0 1 0 0 0 1)",
    ):
        parser.feed(line)
    parser.feed("DICPCG:  Solving for pcorr, Initial residual = 1, Final residual = 1e-06, No Iterations 9")
    parser.feed("GAMG:  Solving for p_rgh, Initial residual = 0.01, Final residual = 1e-06, No Iterations 3")
    window._update_plot(parser)
    assert set(window._curves) == {"p_rgh"}  # the mesh-motion bookkeeping is kept out of the residual plot
    assert set(window._motion_curves) == {"box z"}  # heave only: one curve
    times, moved = window._motion_curves["box z"].getData()
    assert list(times) == [0.1, 0.2] and list(moved) == pytest.approx([0.0, -0.02])
    assert "box" in window.motion_label.text() and "0.41" in window.motion_label.text()
    assert window.rotation_plot.isHidden()  # nothing turns
    window.close()

    window = MainWindow(enable_3d=False, detect=False)
    window.create_project("gate", tmp_path, "gate")
    parser = LogParser()
    for time in (0.05, 0.35, 0.6, 1.0):
        parser.feed(f"Time = {time}")
    window._update_plot(parser)
    _times, moved = window._motion_curves["gate z"].getData()
    assert list(moved) == pytest.approx([0.0, 0.05, 0.1, 0.1])  # the lift that was set: 0.1 m from 0.1 s to 0.6 s
    window.close()


@pytest.mark.openfoam
def test_a_floating_box_runs_from_the_window_and_its_motion_is_plotted(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow
    from easyfoam.runtime import detect_runtimes

    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    window = MainWindow(enable_3d=False, detect=False)
    window.runtime = found[0]
    window.create_project("float", tmp_path, "floating")
    window.project.run.end_time, window.project.run.write_interval = 0.2, 0.1
    window.generate_mesh()
    wait_for_job(qapp, window)
    window.run_solver()
    wait_for_job(qapp, window)
    if window.motion_plot is not None:
        _times, moved = window._motion_curves["box z"].getData()
        assert moved[-1] < -0.005  # released above its floating depth, it has started to sink in
    assert window._case_results().times[-1] == pytest.approx(0.2)
    window.close()
