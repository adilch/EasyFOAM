"""v0.12 in the window: the channel builder."""

import pytest

pytest.importorskip("PySide6")

from easyfoam.model import Channel, ChannelSegment, Project  # noqa: E402

pytestmark = pytest.mark.gui


def test_the_dialog_checks_the_channel_as_it_is_edited(qapp):
    from easyfoam.gui.channel_dialog import ChannelDialog

    dialog = ChannelDialog()
    assert dialog.ok.isEnabled() and "about" in dialog.status.text() and "m³/s" in dialog.status.text()
    dialog.add_bend.click()
    assert [s.kind for s in dialog.channel().segments] == ["straight", "bend"]
    dialog.pieces.item(1, 2).setText("1")  # a bend tighter than the channel is wide
    assert not dialog.ok.isEnabled() and "half the channel's width" in dialog.status.text()
    dialog.pieces.item(1, 2).setText("25")
    dialog.pieces.item(1, 3).setText("-45")  # to the right
    assert dialog.ok.isEnabled()
    bend = dialog.channel().segments[1]
    assert (bend.radius, bend.angle) == (25.0, -45.0)
    assert dialog.pieces.item(1, 1).text() == f"{bend.run():.4g}"  # a bend's length follows from its radius and angle
    dialog.pieces.setCurrentCell(1, 0)
    dialog.remove_piece.click()
    dialog.add_straight.click()
    assert [s.kind for s in dialog.channel().segments] == ["straight", "straight"]


def test_each_section_shows_only_what_it_needs(qapp):
    from easyfoam.gui.channel_dialog import ChannelDialog

    dialog = ChannelDialog(Channel(segments=[ChannelSegment("straight", length=10),
                                             ChannelSegment("bend", radius=20, angle=30)]))  # fmt: skip
    form = dialog.form
    dialog.section.setCurrentIndex(dialog.section.findData("compound"))
    assert form.isRowVisible(dialog.berm_width) and form.isRowVisible(dialog.side_slope)
    assert not form.isRowVisible(dialog.diameter)
    dialog.section.setCurrentIndex(dialog.section.findData("rectangular"))
    assert not form.isRowVisible(dialog.side_slope) and not form.isRowVisible(dialog.berm_width)
    dialog.section.setCurrentIndex(dialog.section.findData("circular"))
    assert form.isRowVisible(dialog.diameter) and not form.isRowVisible(dialog.bottom_width)
    assert not dialog.add_bend.isEnabled() and not dialog.ok.isEnabled()  # a culvert is straight
    assert "built straight" in dialog.status.text()


def test_the_cross_section_drawing_clips_the_water_at_its_depth():
    from easyfoam.gui.channel_dialog import clip_below

    square = [(-1, 0), (1, 0), (1, 2), (-1, 2)]
    assert sorted(clip_below(square, 0.5)) == sorted([(-1, 0), (1, 0), (1, 0.5), (-1, 0.5)])
    assert clip_below(square, -1) == []


def test_a_channel_is_built_into_the_project_and_can_be_removed(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    project = Project(name="river")
    project.save(tmp_path / "case")
    window = MainWindow(enable_3d=False, detect=False)
    window.notify = lambda *args, **kw: None
    window.open_project(tmp_path / "case")
    window.apply_channel(Channel(segments=[ChannelSegment("straight", length=12)], cell_size=0.25))
    p = window.project
    assert p.channel is not None and p.physics.solver == "interFoam"
    assert p.boundaries["inlet"].kind == "flowRateInlet" and p.boundaries["inlet"].flow_rate > 0
    assert p.boundaries["outlet"].kind == "waterLevelOutlet" and p.boundaries["outlet"].level == 0.5
    names = [window.boundary_panel.patch_list.item(i).data(0x0100) or window.boundary_panel.patch_list.item(i).text()
             for i in range(window.boundary_panel.patch_list.count())]  # fmt: skip
    assert any("bed" in str(n) for n in names) and any("atmosphere" in str(n) for n in names)
    geometry = window.geometry_panel
    assert geometry.channel_summary.isVisibleTo(geometry) and "12 m long" in geometry.channel_summary.text()
    assert window.mesh_panel.channel_note.isVisibleTo(window.mesh_panel)
    assert not window.mesh_panel.base_box.isEnabled()
    geometry.remove_channel_button.click()
    assert p.channel is None and not geometry.channel_summary.isVisibleTo(geometry)
    window.close()


def test_a_channel_that_cannot_be_built_is_refused_with_the_reason(qapp, tmp_path):
    from easyfoam.gui.main_window import MainWindow

    Project(name="river").save(tmp_path / "case")
    window = MainWindow(enable_3d=False, detect=False)
    said = []
    window.notify = lambda title, text, *rest: said.append(text)
    window.open_project(tmp_path / "case")
    window.apply_channel(Channel(segments=[ChannelSegment("bend", radius=0.5, angle=90)]))
    assert window.project.channel is None and "half the channel's width" in said[-1]
    window.close()


# --- the ground of a river reach ---------------------------------------------------------------------------------------


def test_the_terrain_dialog_reads_a_survey_and_checks_the_choices(qapp, tmp_path):
    from easyfoam.gui.terrain_dialog import TerrainDialog
    from tests.test_v12_terrain import X0, Y0, write_asc

    dialog = TerrainDialog(write_asc(tmp_path / "dem.asc"))
    assert "ESRI ASCII grid: 231 points about 2 m apart" in dialog.about.text()
    assert dialog.origin() == (512_300.0, 4_181_200.0) and dialog.origin_y.text() == "4181200"  # all digits shown
    assert dialog.spacing.value() == 2.0 and dialog.ok.isEnabled()
    assert dialog.region() == pytest.approx((X0 - 512_300, Y0 - 4_181_200, X0 - 512_300 + 40, Y0 - 4_181_200 + 20))
    settings = dialog.settings()
    assert settings["top"] > 100 and settings["water_level"] < settings["top"]
    ground = dialog.ground()
    assert ground.z.shape == (11, 21) and ground.origin == dialog.origin()
    dialog.spacing.set_value(0.001)
    dialog._update()
    assert not dialog.ok.isEnabled() and "coarser spacing" in dialog.status.text()
    dialog.spacing.set_value(2.0)
    dialog.top.set_value(50.0)
    dialog._update()
    assert not dialog.ok.isEnabled() and "above the highest ground" in dialog.status.text()


def test_a_survey_that_cannot_be_read_says_why(qapp, tmp_path):
    from easyfoam.gui.terrain_dialog import TerrainDialog

    bad = tmp_path / "dem.asc"
    bad.write_text("this is not a grid\n")
    dialog = TerrainDialog(bad)
    assert dialog.survey is None and "Cannot read it" in dialog.about.text() and not dialog.ok.isEnabled()


def test_the_ground_is_brought_into_the_project(qapp, tmp_path):
    from easyfoam import terrain as tr
    from easyfoam.gui.main_window import MainWindow
    from tests.test_v12_terrain import X0, Y0, write_asc

    Project(name="reach").save(tmp_path / "case")
    window = MainWindow(enable_3d=False, detect=False)
    window.notify = lambda *args, **kw: None
    window.open_project(tmp_path / "case")
    ground = tr.ground(tr.read_survey(write_asc(tmp_path / "dem.asc")), 1.0, (X0, Y0))
    window.apply_terrain(ground, cell_size=0.5, water_level=99.8, top=101.0, discharge=3.0)
    p = window.project
    assert [s.name for s in p.shapes] == ["terrain"] and p.boundaries["inlet"].flow_rate == 3.0
    assert (tmp_path / "case" / "constant" / "triSurface" / "terrain.stl").is_file()
    assert window.geometry_panel.shape_list.count() == 1
    assert p.mesh.base.max[2] == 101.0
    window.close()
