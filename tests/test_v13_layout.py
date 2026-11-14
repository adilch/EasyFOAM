"""v0.13 in the window: panels that can be resized, folded away and brought back, and remembered."""

import json

import pytest

pytest.importorskip("PySide6")

from easyfoam.examples import weir  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    """A window on screen with a project open, remembering its layout in a file of its own."""
    from easyfoam.gui.main_window import MainWindow

    monkeypatch.setenv("EASYFOAM_STATE_FILE", str(tmp_path / "state.json"))
    weir("weir").save(tmp_path / "case")
    made = []

    def make():
        w = MainWindow(enable_3d=False, detect=False)
        w.notify = lambda *args, **kw: None
        w.resize(1520, 900)
        w.show()
        qapp.processEvents()
        w.open_project(tmp_path / "case")
        qapp.processEvents()
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()


def test_the_settings_fold_away_and_a_click_on_a_step_brings_them_back(qapp, window):
    w = window()
    open_width = w.workspace.sizes()[0]
    assert w.settings_action.isChecked() and open_width > 400
    w.settings_action.trigger()  # View > Settings of the step, or Ctrl+B
    qapp.processEvents()
    assert w.workspace.is_folded() and w.workspace.sizes()[0] == 0 and not w.settings_action.isChecked()
    w.steps.itemClicked.emit(w.steps.item(3))
    qapp.processEvents()
    assert not w.workspace.is_folded() and w.workspace.sizes()[0] == open_width and w.settings_action.isChecked()
    w.fold_settings_button.click()  # the button beside Back
    assert w.workspace.is_folded()


def test_a_double_click_on_a_handle_folds_and_unfolds(qapp, window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    w = window()
    handle = w.right.handle(1)
    QTest.mouseDClick(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 3))
    qapp.processEvents()
    assert w.right.is_folded() and not w.plots_action.isChecked()
    QTest.mouseDClick(w.right.handle(1), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 3))
    qapp.processEvents()
    assert not w.right.is_folded()


def test_the_plots_fold_down_to_their_tabs_and_a_tab_opens_them(qapp, window):
    w = window()
    w.fold_plots_button.click()
    qapp.processEvents()
    headers = w.bottom.tabBar().sizeHint().height()
    assert w.right.is_folded() and headers <= w.right.sizes()[1] <= headers + 8
    assert "Bring back" in w.fold_plots_button.toolTip() and not w.plots_action.isChecked()
    w.bottom.tabBarClicked.emit(2)
    qapp.processEvents()
    assert not w.right.is_folded() and w.right.sizes()[1] > 150
    w.plots_action.trigger()  # Ctrl+J
    assert w.right.is_folded()
    w.tab_actions["Log"].trigger()  # asking for a tab opens the plots again
    assert not w.right.is_folded() and w.bottom.currentWidget() is w.log


def test_the_steps_narrow_to_their_icons(qapp, window):
    from easyfoam.gui.sidebar import COMPACT_WIDTH, FULL_WIDTH

    w = window()
    assert w.steps.width() == FULL_WIDTH and not w.compact_action.isChecked()
    w.compact_button.click()
    qapp.processEvents()
    assert w.steps.width() == COMPACT_WIDTH and w.compact_action.isChecked() and w.step_delegate.compact
    assert w.steps.item(0).toolTip().startswith("Geometry")  # the names live on in the tooltips
    assert w.workspace.sizes()[1] > 802  # the room goes to the 3D view
    w.compact_action.trigger()
    assert w.steps.width() == FULL_WIDTH


def test_the_layout_is_remembered_and_can_be_reset(qapp, window, tmp_path):
    w = window()
    w.set_compact_steps(True)
    w.right.set_folded(True)
    w.workspace.setSizes([600, 900])
    qapp.processEvents()
    width = w.workspace.sizes()[0]
    w.close()
    saved = json.loads((tmp_path / "state.json").read_text())["layout"]
    assert saved["compact_steps"] and saved["right"]["folded"] and saved["centre"]["sizes"][0] == width

    again = window()
    assert again.step_delegate.compact and again.right.is_folded() and not again.workspace.is_folded()
    assert abs(again.workspace.sizes()[0] - width) <= 2
    again.reset_layout()
    qapp.processEvents()
    assert not again.step_delegate.compact and not again.right.is_folded()
    assert abs(again.workspace.sizes()[0] - 486) <= 10


def test_the_window_can_be_narrower_than_a_laptop_screen(qapp, window):
    w = window()
    assert w.minimumSizeHint().width() < 1300  # one-line hints under the plots no longer hold it wide
    assert w.right.minimumSizeHint().width() < 400


def test_the_view_menu_entries_reach_what_they_name(qapp, window):
    w = window()
    asked = []
    w._view = asked.append
    w.view_actions["iso"].trigger()
    w.view_actions["-z"].trigger()
    assert asked == ["iso", "-z"]  # not the action's "checked" flag, as before
    w.tab_actions["Residuals"].trigger()
    assert w.bottom.currentWidget() is w.plot
