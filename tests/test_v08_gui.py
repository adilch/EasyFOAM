import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from easyfoam.model import Project, Shape  # noqa: E402
from tests.test_gui import select, type_into  # noqa: E402

pytestmark = pytest.mark.gui

SQUARE = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]]


def geometry_panel(tmp_path, *shapes):
    from easyfoam.gui.panels import GeometryPanel

    project = Project(name="x")
    project.mesh.base.min, project.mesh.base.max = [0, 0, 0], [6, 0.5, 1.5]
    project.shapes.extend(shapes)
    panel = GeometryPanel()
    panel.load(project, tmp_path)
    return project, panel


# --- the geometry step --------------------------------------------------------------


def test_six_shapes_can_be_drawn_and_a_file_imported_side_by_side(qapp, tmp_path):
    from easyfoam.gui import icons

    _project, panel = geometry_panel(tmp_path)
    assert [a.data() for a in panel.draw_menu.actions()] == ["box", "sphere", "cylinder", "cone", "wedge", "profile"]
    assert "Import" in panel.import_button.text() and "Draw" in panel.draw_button.text()
    assert not panel.empty_hint.isHidden()  # with no shapes yet, the panel says what to do
    for action in panel.draw_menu.actions():
        assert not action.icon().isNull()
    assert {"shape-cone", "shape-wedge", "shape-outline"} <= set(icons.names()) & set(icons.USED)


def test_a_drawn_shape_appears_inside_the_base_mesh_and_shows_only_its_own_inputs(qapp, tmp_path):
    project, panel = geometry_panel(tmp_path)
    panel.add_primitive("cone")
    cone = project.shapes[0]
    assert cone.kind == "cone" and 0 < cone.point1[0] < 6 and panel.empty_hint.isHidden()
    form = panel.form
    assert all(form.isRowVisible(w) for w in (panel.point1, panel.point2, panel.radius, panel.radius2))
    assert not form.isRowVisible(panel.box_min) and not form.isRowVisible(panel.plane)
    type_into(panel.radius2, "0")
    assert cone.radius2 == 0.0

    panel.add_primitive("wedge")
    assert form.isRowVisible(panel.box_min) and form.isRowVisible(panel.rise) and not form.isRowVisible(panel.radius2)
    select(panel.rise, "-y")
    assert project.shapes[1].rise == "-y"


def test_a_sketched_outline_has_a_plane_two_ends_and_an_outline_to_edit(qapp, tmp_path):
    project, panel = geometry_panel(tmp_path)
    panel.add_primitive("profile")
    shape = project.shapes[0]
    form = panel.form
    assert all(form.isRowVisible(w) for w in (panel.plane, panel.extent_row, panel.outline_button))
    assert "4 corners" in panel.outline_summary.text()
    select(panel.plane, "xy")
    type_into(panel.extent_from, "-1")
    type_into(panel.extent_to, "2.5")
    assert (shape.plane, shape.extent) == ("xy", [-1.0, 2.5])
    panel.set_outline([[0, 0], [1, 0], [1, 1]])
    assert shape.points == [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]] and "3 corners" in panel.outline_summary.text()


def test_dragging_a_handle_in_the_3d_view_updates_the_shape_and_its_inputs(qapp, tmp_path):
    project, panel = geometry_panel(tmp_path, Shape("b", kind="box"), Shape("s", kind="sphere"), Shape("c", kind="cone"))
    assert panel.handles.isChecked()  # on unless the user switches it off
    panel.apply_box([1, 0, 0], [2, 0.5, 0.25])
    assert (project.shapes[0].min, project.shapes[0].max) == ([1.0, 0.0, 0.0], [2.0, 0.5, 0.25])
    assert panel.box_max.value() == [2.0, 0.5, 0.25]
    panel.shape_list.setCurrentRow(1)
    panel.apply_centre([3, 0.25, 0.5])
    assert project.shapes[1].centre == [3.0, 0.25, 0.5] and panel.centre.value() == [3.0, 0.25, 0.5]
    panel.shape_list.setCurrentRow(2)
    panel.apply_axis([1, 0, 0], [1, 0, 1])
    assert (project.shapes[2].point1, project.shapes[2].point2) == ([1.0, 0.0, 0.0], [1.0, 0.0, 1.0])


SURFACE_CHECK = """
from PySide6.QtWidgets import QApplication
app = QApplication([])
from easyfoam.gui.viewer import shape_surface
from easyfoam.model import Shape
square = [[0, 0], [2, 0], [2, 2], [0, 2]]
for shape in (Shape("c", kind="cone"), Shape("w", kind="wedge"), Shape("p", kind="profile", points=square)):
    surface = shape_surface(shape, None)
    print(shape.kind, surface.n_cells > 4, surface.n_open_edges)
print("unfinished", shape_surface(Shape("p", kind="profile", points=[[0, 0], [1, 1]]), None))
"""


def test_drawn_shapes_have_a_surface_for_the_3d_view():
    """Run on its own: the 3D library, once loaded, can upset the shutdown of the big test process."""
    import importlib.util
    import os
    import subprocess
    import sys

    if importlib.util.find_spec("pyvista") is None:  # looked up, not imported: see above
        pytest.skip("the 3D library is not installed")

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run([sys.executable, "-c", SURFACE_CHECK], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split() == [
        "cone", "True", "0", "wedge", "True", "0", "profile", "True", "0", "unfinished", "None",
    ]  # fmt: skip


# --- the sketch pad -----------------------------------------------------------------


def canvas(points=SQUARE, **options):
    from easyfoam.gui.sketch import SketchCanvas

    pad = SketchCanvas(points, **options)
    pad.resize(600, 400)
    pad.grid = 0.0  # no snapping unless a test asks for it
    pad.fit()
    return pad


def click(pad, u, v, button=Qt.MouseButton.LeftButton):
    QTest.mouseClick(pad, button, pos=pad.to_screen(u, v).toPoint())


def test_screen_and_drawing_coordinates_convert_both_ways_with_up_meaning_up(qapp):
    pad = canvas()
    u, v = pad.to_model(pad.to_screen(1.25, 0.5))
    assert (u, v) == pytest.approx((1.25, 0.5))
    assert pad.to_screen(0, 2).y() < pad.to_screen(0, 0).y()  # larger values are drawn higher up
    for corner in SQUARE:  # after "fit" the whole outline is on the pad
        p = pad.to_screen(*corner)
        assert 0 < p.x() < 600 and 0 < p.y() < 400


def test_clicking_adds_corners_in_order_and_a_click_on_a_side_adds_one_there(qapp):
    pad = canvas([], reference=(-1, -1, 3, 3))
    for u, v in ((0, 0), (2, 0), (2, 2)):
        click(pad, u, v)
    assert np.allclose(pad.points(), [[0, 0], [2, 0], [2, 2]], atol=0.02)
    click(pad, 1, 0)  # on the side between the first two corners
    assert np.allclose(pad.points(), [[0, 0], [1, 0], [2, 0], [2, 2]], atol=0.02)


def test_a_corner_can_be_dragged_and_removed_with_the_right_button(qapp):
    pad = canvas()
    changes = []
    pad.changed.connect(lambda: changes.append(1))
    start, end = pad.to_screen(2, 2).toPoint(), pad.to_screen(1.5, 1.0).toPoint()
    QTest.mousePress(pad, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(pad, end)
    QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, pos=end)
    assert pad.points()[2] == pytest.approx([1.5, 1.0], abs=0.02) and len(pad.points()) == 4 and changes
    click(pad, 0, 0, Qt.MouseButton.RightButton)
    assert len(pad.points()) == 3 and pad.points()[0] == pytest.approx([2, 0], abs=0.02)


def test_corners_snap_to_the_grid_when_asked(qapp):
    pad = canvas([], reference=(-1, -1, 3, 3))
    pad.grid = 0.5
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, pos=pad.to_screen(0.93, 1.21).toPoint() + QPoint(1, 1))
    assert pad.points() == [[1.0, 1.0]]


def test_the_dialog_reports_a_crossing_outline_and_only_accepts_a_sound_one(qapp):
    from easyfoam.gui.sketch import SketchDialog

    dialog = SketchDialog(SQUARE, plane="xz", reference=(0, 0, 6, 1.5))
    assert dialog.ok.isEnabled() and "4 m²" in dialog.status.text()
    assert dialog.table.rowCount() == 4 and dialog.table.horizontalHeaderItem(1).text() == "z [m]"
    dialog.canvas.set_points([[0, 0], [2, 2], [2, 0], [0, 2]])
    assert not dialog.ok.isEnabled() and "cross" in dialog.status.text()
    dialog.use_preset("trapezoid")
    assert dialog.ok.isEnabled() and len(dialog.values()) == 4
    dialog.table.item(0, 0).setText("-3")  # typing in the table moves the corner
    assert dialog.values()[0][0] == -3.0


def test_the_sketch_dialog_is_released_when_it_is_no_longer_used(qapp):
    """A dialog that stays alive until the program exits can bring the exit down with it."""
    import gc
    import weakref

    from easyfoam.gui.sketch import SketchDialog

    dialog = SketchDialog(SQUARE, plane="xz", reference=(0, 0, 6, 1.5))
    dialog.use_preset("triangle")
    alive = weakref.ref(dialog)
    del dialog
    gc.collect()
    assert alive() is None
