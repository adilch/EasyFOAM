"""v0.14: forms in sections that fold, a search for every setting and command, plots in a window of their own,
files dropped on the window, help per step, project templates, a dark theme and the text size."""

import json
import warnings

import pytest

pytest.importorskip("PySide6")

from easyfoam.examples import weir  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture()
def state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setenv("EASYFOAM_STATE_FILE", str(path))
    return path


@pytest.fixture()
def window(qapp, tmp_path, state):
    from easyfoam.gui.main_window import MainWindow

    weir("weir").save(tmp_path / "case")
    w = MainWindow(enable_3d=False, detect=False)
    w.notify = lambda *args, **kw: None
    w.resize(1520, 900)
    w.show()
    qapp.processEvents()
    w.open_project(tmp_path / "case")
    qapp.processEvents()
    yield w
    w.close()


# --- sections that fold ---------------------------------------------------------------------------------------


def test_a_section_folds_to_its_title_opens_with_a_click_and_is_remembered(qapp, state):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFormLayout, QLineEdit, QVBoxLayout, QWidget

    from easyfoam.gui.layout import FoldingGroup, folding_groups, shown_if_unfolded, unfold_to

    host = QWidget()
    column = QVBoxLayout(host)
    box = FoldingGroup("Forces", "test.forces", folded=True)
    form = QFormLayout()
    edit = QLineEdit()
    form.addRow("Reference area [m²]", edit)
    box.setLayout(form)  # the form goes into the part that folds away
    column.addWidget(box)
    column.addStretch(1)
    host.resize(400, 300)
    host.show()
    qapp.processEvents()
    assert box.is_folded() and not edit.isVisible() and shown_if_unfolded(edit)
    assert box.height() <= 24  # one line: its title
    assert folding_groups(edit) == [box] and form.isRowVisible(edit)  # folding does not hide rows of the form
    box.set_note("off")
    assert box.note() == "off" and box.plain_title() == "Forces"
    QTest.mouseClick(box, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 8))
    qapp.processEvents()
    assert not box.is_folded() and edit.isVisible() and box.height() > 40
    QTest.mouseClick(box, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, box.height() - 4))
    assert not box.is_folded()  # a click below the title does nothing
    assert json.loads(state.read_text(encoding="utf-8"))["sections"]["test.forces"] is False
    assert not FoldingGroup("Forces", "test.forces", folded=True).is_folded()  # left open: opens open next time
    box.set_folded(True)
    assert unfold_to(edit) == [box] and not box.is_folded() and unfold_to(edit) == []
    host.close()


def test_sections_most_projects_do_not_need_start_folded_and_say_what_they_hold(qapp, window):
    run, physics = window.run_panel, window.physics_panel
    assert run.force_box.is_folded() and run.probe_box.is_folded() and run.rating_box.is_folded()
    assert physics.start_box.is_folded() and physics.tracer_box.is_folded()
    assert not physics.water_box.is_folded() and not window.results_panel.hydraulics_box.is_folded()
    assert run.probe_box.note() == "1 point" and run.flow_box.note() == "outlet"
    assert run.rating_box.note() == "not set up" and run.force_box.note() == "not in free-surface runs"
    assert physics.tracer_box.note() == "none"
    run.add_probe((2.0, 0.25, 0.3))
    assert run.probe_box.note() == "2 points"  # notes follow the changes
    physics.add_tracer("age", kind="age")
    assert physics.tracer_box.note() == "age"


# --- a search for every setting and command -------------------------------------------------------------------


def test_the_search_finds_settings_and_commands_by_name_or_by_another_word(qapp, window):
    from easyfoam.gui.search import collect, find

    entries = collect(window)

    def first(query: str):
        return find(entries, query, 1)[0]

    assert first("Manning").text.startswith("Manning's n")
    assert first("CFL").text == "Keep the Courant number below"  # another word for it
    assert first("gauge").text == "Gauge (probe number)"
    assert first("strickler").where.startswith("Boundaries")
    assert "water level" in first("tailwater").text.lower()
    assert first("undo").kind == "command" and first("undo").where == "Edit menu"
    assert first("k-epsilon").kind == "choice" and first("k-epsilon").where == "Physics › Model › Turbulence"
    assert first("Mesh step").kind == "step"
    assert all("RNG" not in e.text for e in find(entries, "rating", 10))  # not inside "sepa-rating"
    assert find(entries, "qqqzzz") == [] and find(entries, "   ") == []


def test_choosing_a_result_opens_its_step_and_section_and_gives_it_the_focus(qapp, window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window.search_action.trigger()
    QTest.keyClicks(window.search_box, "gauge")
    results = window.search_box.results
    assert results.isVisible() and results.count() >= 3
    QTest.keyClick(window.search_box, Qt.Key.Key_Return)
    for _ in range(3):
        qapp.processEvents()
    assert window.steps.currentRow() == 4  # Run
    assert not window.run_panel.rating_box.is_folded() and window.run_panel.rating_gauge.isVisible()
    assert window.focusWidget() is window.run_panel.rating_gauge
    assert not results.isVisible() and window.search_box.text() == ""
    # a command runs
    window.search_box.start()
    QTest.keyClicks(window.search_box, "plots and log")
    QTest.keyClick(window.search_box, Qt.Key.Key_Return)
    assert window.right.is_folded()
    # a setting the current choices hide says so instead
    window.boundary_panel.patch_list.setCurrentRow(0)  # the inlet: no roughness there
    window.search_box.start()
    QTest.keyClicks(window.search_box, "manning's n [")
    QTest.keyClick(window.search_box, Qt.Key.Key_Return)
    assert "not shown with the current choices" in window.statusBar().currentMessage()
    QTest.keyClicks(window.search_box, "xyz")
    QTest.keyClick(window.search_box, Qt.Key.Key_Escape)
    assert window.search_box.text() == "" and not results.isVisible()


# --- plots on a second screen ---------------------------------------------------------------------------------


def test_the_plots_and_log_move_to_a_window_of_their_own_and_back(qapp, window, state):
    assert not window.plots_detached() and window.right.count() == 2
    window.detach_action.trigger()
    qapp.processEvents()
    assert window.plots_detached() and window.plot_window.isVisible() and window.right.count() == 1
    assert window.detach_action.isChecked() and window.fold_plots_button.isHidden()
    window._show_tab("Log")
    assert window.bottom.currentWidget() is window.log
    window.plots_action.trigger()  # Ctrl+J while they are away brings their window forward and changes nothing
    assert window.plots_detached() and window.plots_action.isChecked()
    window._remember_layout()
    saved = json.loads(state.read_text(encoding="utf-8"))["layout"]["plot_window"]
    assert saved["detached"] is True and saved["geometry"]
    window.plot_window.close()  # closing their window puts them back
    qapp.processEvents()
    assert not window.plots_detached() and window.right.count() == 2 and window.right.sizes()[1] > 100
    assert not window.detach_action.isChecked() and not window.fold_plots_button.isHidden()
    window.set_plots_detached(True)
    window.reset_layout()
    assert not window.plots_detached()


# --- files dropped on the window ------------------------------------------------------------------------------

PIER_STL = """solid pier
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 100 0 0
  vertex 0 100 0
 endloop
endfacet
facet normal 0 0 1
 outer loop
  vertex 0 0 100
  vertex 100 0 100
  vertex 0 100 100
 endloop
endfacet
endsolid pier
"""


def test_what_is_dropped_on_the_window_is_opened(qapp, window, tmp_path, monkeypatch):
    from pathlib import Path

    from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent
    from PySide6.QtWidgets import QInputDialog

    from easyfoam.gui.main_window import MainWindow

    kind = MainWindow.drop_kind
    assert kind(tmp_path / "case") == "project" and kind(tmp_path / "case" / "easyfoam.json") == "project"
    assert kind(Path("pier.STL")) == "geometry" and kind(Path("weir.step")) == "geometry"
    assert kind(Path("river.xyz")) == "survey" and kind(Path("dem.tif")) == "survey" and kind(Path("notes.docx")) == ""

    pier = tmp_path / "pier.stl"
    pier.write_text(PIER_STL)

    def drag(path) -> bool:
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(path))])
        with warnings.catch_warnings():  # the one constructor there is, marked as going to change
            warnings.simplefilter("ignore", DeprecationWarning)
            event = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                                    Qt.KeyboardModifier.NoModifier)  # fmt: skip
        event.setAccepted(False)
        window.dragEnterEvent(event)
        return event.isAccepted()

    assert drag(pier) and not drag(tmp_path / "notes.docx")
    asked = []
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kw: asked.append(args[2]) or ("millimetres", True))
    window.steps.setCurrentRow(4)
    window.open_files([pier, tmp_path / "notes.docx"])
    assert asked == ["The file is drawn in"] and window.current_step() == "Geometry"
    assert window.project.shapes[-1].name == "pier"  # imported, in millimetres
    assert "notes.docx" in window.statusBar().currentMessage()
    surveys = []
    monkeypatch.setattr(window, "bring_in_terrain", lambda path=None: surveys.append(path))
    window.open_files([tmp_path / "river.xyz"])
    assert surveys == [tmp_path / "river.xyz"]  # the ground dialog opens with it
    weir("other").save(tmp_path / "other")
    window.open_files([tmp_path / "other" / "easyfoam.json"])
    assert window.case_dir == tmp_path / "other"  # another project: it is opened instead


# --- help for each step ---------------------------------------------------------------------------------------


def test_the_help_of_each_step_opens_the_closest_tutorial_at_that_step(qapp, window, monkeypatch):
    from easyfoam.examples import EXAMPLES
    from easyfoam.gui.help import project_kinds, tutorial_for

    page, number, title = tutorial_for(window.project, "Boundaries")  # a free-surface weir
    assert page.name == "weir.html" and number == 8 and title
    assert project_kinds(EXAMPLES["basin"]("b"))[:2] == ["basin", "structure"]
    assert tutorial_for(EXAMPLES["basin"]("b"), "Results")[0].name == "basin.html"
    assert tutorial_for(EXAMPLES["tank"]("t"), "Physics")[0].name == "tank.html"
    assert tutorial_for(EXAMPLES["sphere"]("s"), "Mesh")[0].name == "sphere.html"
    assert tutorial_for(EXAMPLES["basin"]("b"), "Mesh")[0].name in ("weir.html", "spillway.html")  # basin has none
    opened = []
    monkeypatch.setattr("easyfoam.gui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url) or True)
    window.steps.setCurrentRow(3)
    assert window.help_button.isEnabled() and "step 8" in window.help_button.toolTip()
    window.step_help_action.trigger()
    forward = opened[-1].toLocalFile()
    text = open(forward, encoding="utf-8").read()
    assert "weir.html#step-8" in text  # through a page that keeps the #step-8 on the way


# --- project templates ----------------------------------------------------------------------------------------


def test_a_project_saved_as_a_template_starts_new_projects(qapp, window, tmp_path, monkeypatch):
    from easyfoam.model import Project
    from easyfoam.templates import list_templates

    window.project.run.end_time = 33.0
    window.save_as_template("Flume 1:20", "my usual flume")
    templates = list_templates()
    assert [(t.name, t.description) for t in templates] == [("Flume 1:20", "my usual flume")]
    from easyfoam.gui.welcome import NewProjectDialog

    dialog = NewProjectDialog(tmp_path, f"template:{templates[0].folder}", window)
    assert dialog.example.currentText().startswith("Template: Flume 1:20")
    window.create_project("from-template", tmp_path, dialog.values()[2])
    assert window.case_dir == tmp_path / "from-template" and window.project.run.end_time == 33.0
    assert Project.load(tmp_path / "from-template").name == "from_template"
    window._fill_template_menu()
    assert "Flume 1:20" in [a.text() for a in window.template_menu.actions()]


# --- a dark theme and the text size ---------------------------------------------------------------------------


def test_the_dark_theme_and_the_text_size_change_the_running_window_and_are_remembered(qapp, window, state):
    from PySide6.QtCore import QSize

    from easyfoam.gui import style
    from easyfoam.gui.icons import icon
    from easyfoam.gui.state import load_appearance

    def icon_colours() -> set[str]:
        image = icon("play").pixmap(QSize(20, 20)).toImage()
        return {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
                if image.pixelColor(x, y).alpha() == 255}  # fmt: skip

    font = qapp.font()
    try:
        assert style.LIGHT["icon"] in icon_colours()
        window.theme_actions["dark"].trigger()
        assert style.theme == "dark" and style.PANEL == style.DARK["panel"] and window.theme_actions["dark"].isChecked()
        assert f"background: {style.DARK['panel']}" in qapp.styleSheet()
        assert style.DARK["icon"] in icon_colours()  # an icon made before follows the theme
        assert window.plot.backgroundBrush().color().name() == style.DARK["plot_bg"]
        window.larger_text_action.trigger()
        assert style.text_size == 10.0 and qapp.font().pointSizeF() == 10.0
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert (saved["theme"], saved["text_size"]) == ("dark", 10.0) and load_appearance() == ("dark", 10.0)
        window.set_text_size(30)
        assert style.text_size == style.TEXT_SIZES[1] and not window.larger_text_action.isEnabled()
        window.set_theme("system")
        assert style.theme == "system" and style.resolved() in ("light", "dark")
    finally:  # as the other tests expect it: no style sheet, the usual font
        style.choose("light", style.TEXT_SIZE)
        qapp.setStyleSheet("")
        qapp.setPalette(qapp.style().standardPalette())
        qapp.setFont(font)
