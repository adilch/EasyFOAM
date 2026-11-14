"""v0.13 in the window: designing hydraulic structures."""

import pytest

pytest.importorskip("PySide6")

from easyfoam import structures as sm  # noqa: E402
from easyfoam.examples import weir  # noqa: E402

pytestmark = pytest.mark.gui

BOX = ([0.0, 0.0, 0.0], [6.0, 0.5, 1.5])


def test_the_dialog_redraws_and_checks_the_design_as_it_is_edited(qapp):
    from easyfoam.gui.structure_dialog import StructureDialog

    dialog = StructureDialog(sm.place("ogee", *BOX), BOX)
    assert dialog.ok.isEnabled() and dialog.preview.built is not None
    assert "m³/s" in dialog.info.text() and "spillway crest" in dialog.purpose.text()
    dialog.inputs["design_head"].set_value(0.0)
    dialog.inputs["design_head"].changed.emit(0.0)
    assert not dialog.ok.isEnabled() and dialog.preview.built is None
    assert "design head Hd must be above zero" in dialog.status.text()
    dialog.inputs["design_head"].set_value(0.12)
    dialog.inputs["design_head"].changed.emit(0.12)
    assert dialog.ok.isEnabled() and dialog.structure().values["design_head"] == 0.12

    dialog.kind.setCurrentIndex(dialog.kind.findData("culvert"))
    st = dialog.structure()
    assert st.kind == "culvert" and st.station == 2.0 and st.values == sm.place("culvert", *BOX).values
    barrels = dialog.inputs["circular"]
    barrels.setCurrentIndex(barrels.findData(1.0))
    assert dialog.structure().values["circular"] == 1.0 and "pipe barrel" in dialog.info.text()
    dialog.inputs["count"].setValue(2)
    assert dialog.structure().values["count"] == 2.0 and "2 pipe barrels" in dialog.info.text()

    dialog.width.set_value(0.45)
    dialog.width.changed.emit(0.45)
    assert dialog.ok.isEnabled() and "water can pass beside it" in dialog.status.text()  # a warning, not a refusal
    dialog.width.set_value(0.4)
    dialog.width.changed.emit(0.4)
    assert not dialog.ok.isEnabled() and "do not fit side by side" in dialog.status.text()  # two 0.2 m pipes
    dialog.kind.setCurrentIndex(dialog.kind.findData("fishway"))
    assert dialog.structure().values["slot"] == 0.05  # pools 8 slots wide fill the channel
    assert dialog.values_box.title() == "Design of the vertical-slot fishway"


def test_the_preview_clips_shapes_at_the_bed_and_the_walls():
    from easyfoam.gui.structure_dialog import clip

    square = [(0, -1), (2, -1), (2, 1), (0, 1)]
    assert sorted(clip(square, 1, 0.0, keep_above=True)) == sorted([(0, 0), (2, 0), (2, 1), (0, 1)])
    assert sorted(clip(square, 0, 1.0, keep_above=False)) == sorted([(0, -1), (1, -1), (1, 1), (0, 1)])
    assert clip(square, 1, 5.0, keep_above=True) == []


def test_flat_structures_are_drawn_with_their_heights_stretched(qapp):
    from easyfoam.gui.structure_dialog import StructureDialog

    dialog = StructureDialog(sm.place("fishway", *BOX), BOX)
    dialog.resize(1080, 640)
    dialog.show()
    qapp.processEvents()
    image = dialog.preview.grab().toImage()
    assert image.width() > 400
    from easyfoam.gui.structure_dialog import _fit

    flat = _fit([(0, 0), (2, 0.1)], 0, 0, 400, 300, stretch=5.0)
    tall = _fit([(0, 0), (0.5, 0.5)], 0, 0, 400, 300, stretch=5.0)
    assert flat.rise == 5.0 and tall.rise == 1.0
    dialog.close()


def test_the_3d_view_shows_each_structure_inside_its_channel():
    pytest.importorskip("pyvista")
    from easyfoam.gui.viewer import shape_surface
    from easyfoam.model import Shape

    for kind in sm.KINDS:
        st = sm.place(kind, *BOX)
        surface = shape_surface(Shape("s", kind="structure", structure=st), None)
        _x0, _x1, y0, y1, z0, _z1 = surface.bounds
        assert surface.n_cells > 0, kind
        assert y0 >= st.y0 - 1e-9 and y1 <= st.y0 + st.width + 1e-9 and z0 >= st.bed - 1e-9, kind


def test_the_spillway_crest_and_the_stilling_basin_are_examples(qapp):
    from easyfoam.gui import icons
    from easyfoam.gui.main_window import EXAMPLE_LABELS, MainWindow
    from easyfoam.gui.welcome import EXAMPLES, SHOWN, WelcomePage

    assert SHOWN[-2:] == ("ogee", "basin")
    assert all(EXAMPLES[k][0] in icons.names() and EXAMPLES[k][0] in icons.USED for k in ("ogee", "basin"))
    page = WelcomePage()
    assert "Ogee spillway crest" in page.example_buttons["ogee"].text()
    assert "Stilling basin" in page.example_buttons["basin"].text()
    window = MainWindow(enable_3d=False, detect=False)
    labels = [a.text() for menu in window.menuBar().findChildren(type(window.menuBar().actions()[0].menu()))
              for a in menu.actions()]  # fmt: skip
    assert EXAMPLE_LABELS["ogee"] in labels and EXAMPLE_LABELS["basin"] in labels
    window.close()


def test_a_structure_is_added_and_changed_in_the_geometry_step(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    project = weir("weir")
    project.shapes = []
    project.mesh.snappy = False
    project.save(tmp_path / "case")
    window = MainWindow(enable_3d=False, detect=False)
    window.notify = lambda *args, **kw: None
    window.open_project(tmp_path / "case")
    geometry = window.geometry_panel
    assert [a.data() for a in geometry.structure_menu.actions()] == list(sm.KINDS)

    geometry.add_structure(sm.place("basin", *BOX))
    p = window.project
    shape = p.shapes[-1]
    assert shape.name == "basin1" and shape.kind == "structure" and p.mesh.snappy
    assert geometry.shape_list.item(0).text() == "basin1   (USBR stilling basin)"
    assert geometry.form.isRowVisible(geometry.design_button) and not geometry.form.isRowVisible(geometry.role)
    assert geometry.design_summary.text().startswith("USBR stilling basin starting at x = 2 m")
    names = [window.boundary_panel.patch_list.item(i).text() for i in range(window.boundary_panel.patch_list.count())]
    assert any("basin1" in name for name in names)

    changed = sm.place("basin", *BOX)
    changed.values.update(basin_type=4.0, froude=3.5)
    changed.station = 2.5
    geometry.set_structure(changed)
    assert shape.structure.values["basin_type"] == 4.0 and "x = 2.5 m" in geometry.design_summary.text()
    geometry.add_structure(sm.place("ogee", *BOX))
    assert [s.name for s in p.shapes] == ["basin1", "ogee1"]
    window.close()
