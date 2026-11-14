"""v0.13: the time a run still needs, an alert when it ends, undo and redo, and numbers typed with units."""

import pytest

from easyfoam.history import History
from easyfoam.pace import Pace, in_words, took
from easyfoam.units import parse_quantity, unit_in_label

# --- numbers typed with their units -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "unit", "value"),
    [
        ("50 mm", "m", 0.05), ("2 ft", "m", 0.6096), ("2ft", "m", 0.6096), ("0.5 m", "mm", 500.0),
        ("3.5 l/s", "m³/s", 0.0035), ("10 cfs", "m³/s", 0.28316846592), ("1.2 ML/d", "m³/s", 1200 / 86400),
        ("5 m3/s", "m³/s", 5.0), ("5 m^3/s", "m³/s", 5.0), ("0.1 %", "m/m", 0.001), ("2 ‰", "m/m", 0.002),
        ("10 min", "s", 600.0), ("1.5 h", "s", 5400.0), ("2 days", "s", 172800.0), ("200 kPa", "Pa", 2e5),
        ("1 cSt", "m²/s", 1e-6), ("90 deg", "°", 90.0), ("36 km/h", "m/s", 10.0),
        ("1,5", "m", 1.5), ("1.2 + 0.3", "m", 1.5), ("2*0.75", "", 1.5), ("-1.5", "m", -1.5), ("1e-5", "m²/s", 1e-5),
    ],
)  # fmt: skip
def test_numbers_are_read_in_the_fields_own_unit(text, unit, value):
    assert parse_quantity(text, unit)[0] == pytest.approx(value)


def test_a_converted_number_says_what_it_became():
    assert parse_quantity("50 mm", "m")[1] == "50 mm = 0.05 m"
    assert parse_quantity("5 m3/s", "m³/s")[1] == ""  # the field's own unit, spelled differently
    assert parse_quantity("90 deg", "°")[1] == ""  # another name for it
    assert parse_quantity("5", "m")[1] == ""


@pytest.mark.parametrize(
    ("text", "unit", "reason"),
    [
        ("5 m/s", "m", "m/s is a speed, but this is a length in m"),
        ("abc", "m", "“abc” is not a number"),
        ("5 furlongs", "m", "“furlongs” is not a unit EasyFOAM knows"),
        ("3 m", "H per V", "type a plain number here: this is in H per V"),
        ("2 m", "", "type a plain number here"),
        ("1/0", "m", "“1/0” is not a number"),
        ("__import__('os')", "", "is not a number"),
    ],
)
def test_numbers_that_cannot_be_used_say_why(text, unit, reason):
    with pytest.raises(ValueError, match=reason.replace("(", r"\(").replace(")", r"\)").replace("^", r"\^")):
        parse_quantity(text, unit)


def test_the_unit_is_read_from_a_form_label():
    assert unit_in_label("End time [s]") == "s"
    assert unit_in_label("Limit velocity [m/s], 0 = off") == "m/s"
    assert unit_in_label("Turbulence intensity (0–1)") == ""


# --- the time a run still needs -----------------------------------------------------------------------------------


def test_the_time_left_follows_the_recent_pace():
    pace = Pace(window=60, warm_up=5)
    assert pace.seconds_left(10) is None
    pace.add(0.0, now=0)
    pace.add(1.0, now=2)
    assert pace.seconds_left(10) is None  # too early to tell
    for t in range(3, 31):  # 0.5 s of simulated time per second of clock
        pace.add(1.0 + 0.5 * (t - 2), now=t)
    assert pace.seconds_left(25.0) == pytest.approx((25.0 - 15.0) / 0.5, rel=0.05)
    for t in range(31, 121):  # it slows down to 0.1 s a second: the estimate follows within the window
        pace.add(15.0 + 0.1 * (t - 30), now=t)
    assert pace.seconds_left(30.0) == pytest.approx((30.0 - 24.0) / 0.1, rel=0.05)
    pace.add(0.5, now=121)  # started again
    assert pace.seconds_left(30.0) is None


def test_durations_are_said_the_way_people_say_them():
    assert in_words(20) == "less than a minute"
    assert in_words(12 * 60 + 10) == "about 12 min"
    assert in_words(80 * 60) == "about 1 h 20 min" and in_words(120 * 60) == "about 2 h"
    assert took(40) == "40 s" and took(200) == "3 min 20 s" and took(180) == "3 min" and took(3900) == "1 h 05 min"


# --- undo and redo ------------------------------------------------------------------------------------------------


def test_the_history_steps_back_and_forth_and_forgets_the_redo_after_a_new_change():
    h = History(limit=3)
    h.reset("a")
    assert not h.can_undo and not h.record("a")
    assert h.record("b") and h.record("c")
    assert h.step_back() == "b" and h.step_back() == "a" and h.step_back() is None
    assert h.step_forward() == "b" and h.can_redo
    assert h.record("d") and not h.can_redo  # a new change after an undo: the old future is gone
    for state in "efgh":
        h.record(state)
    steps = []
    while (state := h.step_back()) is not None:
        steps.append(state)
    assert steps == ["g", "f", "e"]  # only the last three are kept


# --- in the window ------------------------------------------------------------------------------------------------


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from easyfoam.examples import weir
    from easyfoam.gui.main_window import MainWindow

    monkeypatch.setenv("EASYFOAM_STATE_FILE", str(tmp_path / "state.json"))
    weir("weir").save(tmp_path / "case")
    w = MainWindow(enable_3d=False, detect=False)
    w.notify = lambda *args, **kw: None
    w.open_project(tmp_path / "case")
    yield w
    w.close()


@pytest.mark.gui
def test_a_field_takes_units_from_its_label_and_keeps_a_bad_value_in_red(qapp, window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    end = window.run_panel.end_time
    seen = []
    end.changed.connect(seen.append)
    end.setText("2 min")
    end.editingFinished.emit()
    assert window.project.run.end_time == 120.0 and seen == [120.0] and end.text() == "120"
    end.setText("-5")
    end.editingFinished.emit()
    assert window.project.run.end_time == 120.0 and seen == [120.0]  # nothing changed ...
    assert end.text() == "-5" and end.property("invalid") and "must be above 0" in end.problem  # ... and it says why
    assert "must be above 0" in window.statusBar().currentMessage()
    QTest.keyClick(end, Qt.Key.Key_Escape)
    assert end.text() == "120" and not end.problem and not end.property("invalid")
    end.setText("3 l/s")
    end.editingFinished.emit()
    assert "a discharge, but this is a time in s" in end.problem
    ks = window.boundary_panel.ks_mm  # its label says mm
    ks.setText("0.002 m")
    ks.editingFinished.emit()
    assert ks.value() == pytest.approx(2.0)
    fraction = window.boundary_panel.water_fraction
    fraction.setText("1.5")
    fraction.editingFinished.emit()
    assert "between 0 and 1" in fraction.problem and fraction.value() == 1.0


@pytest.mark.gui
def test_undo_and_redo_walk_through_the_changes_to_the_set_up(qapp, window):
    assert not window.undo_action.isEnabled() and not window.redo_action.isEnabled()
    window.run_panel.end_time.setText("30")
    window.run_panel.end_time.editingFinished.emit()
    window.save_project()  # as the autosave does, shortly after each change
    window.project.boundaries["inlet"].flow_rate = 0.07  # a change still waiting for the autosave
    window._project_changed()
    assert window.undo_action.isEnabled()
    window.undo_action.trigger()
    assert window.project.boundaries["inlet"].flow_rate == 0.05 and window.project.run.end_time == 30
    window.undo_action.trigger()
    assert window.project.run.end_time == 20 and window.run_panel.end_time.text() == "20"
    assert not window.undo_action.isEnabled() and window.redo_action.isEnabled()
    from easyfoam.model import Project

    assert Project.load(window.case_dir).run.end_time == 20  # what is on disk follows
    window.redo_action.trigger()
    window.redo_action.trigger()
    assert window.project.run.end_time == 30 and window.project.boundaries["inlet"].flow_rate == 0.07
    assert not window.redo_action.isEnabled()


@pytest.mark.gui
def test_the_progress_bar_says_how_long_is_left(qapp, window):
    window.show_progress(5.0, 20.0, 12 * 60)
    assert window.time_left.text() == "about 12 min left" and window.progress.value() == 25
    window.show_progress(5.0, 20.0)
    assert window.time_left.text() == "estimating the time left…"
    window.show_progress(None, None)
    assert window.time_left.isHidden() and window.progress.isHidden()


@pytest.mark.gui
def test_a_long_task_is_announced_when_no_one_is_looking(qapp, window, monkeypatch):
    from PySide6.QtWidgets import QApplication

    flashed = []
    monkeypatch.setattr(QApplication, "alert", lambda widget, msec=0: flashed.append(widget))
    window._announce("Run finished in 3 s.", True, 3.0)
    assert flashed == []  # a short task ends while the user is still looking
    window._announce("Run finished in 23 min.", True, 23 * 60)
    assert flashed == [window]  # the window is not the active one here: the taskbar button flashes
