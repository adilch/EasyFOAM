"""v0.14: picking in the 3D view: values under the cursor, gauges placed with a click, distances, the long-section
line (which the long section then follows)."""

import numpy as np
import pytest

from easyfoam.examples import weir
from easyfoam.hydraulics import default_centreline
from easyfoam.model import Project


def test_the_long_section_follows_the_line_drawn_for_it(tmp_path):
    project = weir("weir")
    assert default_centreline(project).points.tolist() == [[0.0, 0.25], [6.0, 0.25]]  # the x axis, as before
    project.section_line = [[0.5, 0.1], [3.0, 0.3], [5.5, 0.2]]
    project.save(tmp_path / "case")
    again = Project.load(tmp_path / "case")
    line = default_centreline(again)
    assert line.points.tolist() == [[0.5, 0.1], [3.0, 0.3], [5.5, 0.2]] and line.half_width == pytest.approx(0.25)
    assert line.length == pytest.approx(np.hypot(2.5, 0.2) + np.hypot(2.5, 0.1))
    again.section_line = [[1.0, 1.0], [1.0, 1.0]]  # no length: not a line
    assert default_centreline(again).points.tolist() == [[0.0, 0.25], [6.0, 0.25]]


@pytest.fixture()
def viewer(qapp, tmp_path):
    pytest.importorskip("pyvistaqt")
    from easyfoam.gui.viewer import Viewer

    project = weir("weir")
    project.save(tmp_path / "case")
    v = Viewer()
    v.resize(900, 600)
    v.show()
    qapp.processEvents()
    v.plotter.ren_win.SetSize(900, 560)  # off screen the view has no size of its own
    v.show_geometry(project, tmp_path / "case")
    v.toggle_parallel(True)  # no perspective: a point of the model and its place on screen line up
    v.set_view("+x")  # looking downstream, at the upstream face of the weir
    qapp.processEvents()
    yield v, project
    v.close_view()
    v.close()


def _display(v, point):
    renderer = v.plotter.renderer
    renderer.SetWorldPoint(*point, 1.0)
    renderer.WorldToDisplay()
    x, y, _ = renderer.GetDisplayPoint()
    return int(round(x)), int(round(y))


@pytest.mark.gui
def test_a_click_reads_values_places_gauges_measures_and_draws_the_long_section_line(qapp, viewer):
    v, project = viewer
    picked, lines = [], []
    v.probe_picked.connect(picked.append)
    v.section_line_drawn.connect(lines.append)
    face = (2.52, 0.25, 0.3)  # on the upstream face of the weir
    picker, point = v._pick(*_display(v, face))
    assert picker is not None and point[0] == pytest.approx(2.52, abs=0.02)
    assert "weir" in v.describe(picker, point) and "x 2.52" in v.describe(picker, point)

    v.set_pick_mode("probe")
    assert v.pick_button.text() == "Gauges" and "gauge" in v.readout.text()
    v._place_probe(*_display(v, face))
    assert len(picked) == 1
    x, y, z = picked[0]
    assert x < 2.52 and abs(x - 2.52) == pytest.approx(0.5 * v._cell, abs=0.01)  # half a cell into the water
    assert z == pytest.approx(0.3, abs=0.03)

    v.set_pick_mode("measure")
    v._measure_at(*_display(v, (2.52, 0.25, 0.1)))
    v._measure_at(*_display(v, (2.52, 0.25, 0.4)))
    assert v.readout.text().startswith("Distance 0.3")

    v.set_view("-z")  # from above, to draw along the channel
    qapp.processEvents()
    v.set_pick_mode("line")
    for x_line in (0.5, 3.0, 5.5):
        v._extend_line(*_display(v, (x_line, 0.25, 0.0)))
    assert "3 points" in v.readout.text()
    v._finish_line()
    assert len(lines) == 1 and len(lines[0]) == 3
    assert [p[0] for p in lines[0]] == pytest.approx([0.5, 3.0, 5.5], abs=0.05)
    v.set_pick_mode("line")
    v._extend_line(*_display(v, (1.0, 0.25, 0.0)))
    v._finish_line()
    assert len(lines) == 1 and "at least two points" in v.readout.text()


@pytest.mark.gui
def test_the_window_keeps_what_was_picked_and_says_where(qapp, tmp_path, monkeypatch):
    from easyfoam.gui.main_window import MainWindow

    monkeypatch.setenv("EASYFOAM_STATE_FILE", str(tmp_path / "state.json"))
    weir("weir").save(tmp_path / "case")
    w = MainWindow(enable_3d=False, detect=False)
    w.notify = lambda *args, **kw: None
    w.open_project(tmp_path / "case")
    try:
        w._probe_picked([4.0, 0.25, 0.05])
        assert w.project.probes[-1] == [4.0, 0.25, 0.05] and w.run_panel.probe_table.rowCount() == 2
        assert w.statusBar().currentMessage().startswith("Gauge 2 placed at x 4, y 0.25, z 0.05")
        w._section_line_drawn([[0.5, 0.25], [5.5, 0.25]])
        w.save_project()
        assert Project.load(tmp_path / "case").section_line == [[0.5, 0.25], [5.5, 0.25]]
        w._section_line_drawn([])
        assert w.project.section_line == [] and "cleared" in w.statusBar().currentMessage()
    finally:
        w.close()
