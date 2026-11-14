"""v0.14: a report of a project for a design note, its results checked against hydraulic theory."""

import math

import numpy as np
import pytest

from easyfoam import report as rp
from easyfoam.examples import EXAMPLES, weir
from easyfoam.hydraulics import LongSection
from easyfoam.model import Channel, Project

LOG = """Courant Number mean: 0 max: 0
Time = 0.1

Courant Number mean: 0.1 max: 0.62
smoothSolver:  Solving for alpha.water, Initial residual = 0.001, Final residual = 1e-08, No Iterations 1
Time = 10

Courant Number mean: 0.1 max: 0.69
DICPCG:  Solving for p_rgh, Initial residual = 0.0004, Final residual = 1e-08, No Iterations 9
time step continuity errors : sum local = 1e-09, global = 1e-12, cumulative = 1e-10
ExecutionTime = 95.5 s  ClockTime = 96 s

Time = 20

Courant Number mean: 0.1 max: 0.7
ExecutionTime = 190.25 s  ClockTime = 191 s

End
"""


def _finished_case(tmp_path, outflow: float):
    """A weir case with the files a finished run leaves: the solver log, checkMesh and the outlet discharge."""
    case = tmp_path / "weir"
    project = weir("weir")
    project.save(case)
    (case / f"log.{project.physics.solver}").write_text(LOG)
    (case / "log.checkMesh").write_text("Mesh stats\n    cells:            20192\n\nMesh OK.\n\nEnd\n")
    flow = case / "postProcessing" / "flow_outlet" / "0"
    flow.mkdir(parents=True)
    rows = "\n".join(f"{t:g}\t{outflow * min(1.0, t / 5):.6g}" for t in np.arange(0.5, 20.01, 0.5))
    (flow / "surfaceFieldValue.dat").write_text("# Time    sum(phi)\n" + rows + "\n")
    return project, case


def test_a_report_of_a_project_not_run_yet_says_what_was_modelled(tmp_path):
    project = weir("weir")
    project.save(tmp_path / "weir")
    report = rp.build(project, tmp_path / "weir", "v2506")
    titles = [s.title for s in report.sections]
    assert titles == ["What was modelled", "Geometry", "Mesh", "Boundaries", "The run", "Results"]
    assert report.checks == []  # nothing has run: nothing to check
    page = rp.render_html(report)
    assert "weir: simulation report" in page and "Inlet by flow rate" in page and "Q = 0.05 m³/s" in page
    assert "The simulation has not been run yet." in page and "OpenFOAM v2506" in page
    assert "Checked against theory" not in page


def test_the_checks_read_the_log_the_mesh_and_the_monitors(tmp_path):
    project, case = _finished_case(tmp_path, outflow=0.0499)
    report = rp.build(project, case)
    verdicts = {c.what: c.verdict for c in report.checks}
    assert verdicts["Mesh quality (checkMesh)"] == rp.OK
    assert verdicts["The run went to its end"] == rp.OK
    assert verdicts["Courant number"] == rp.OK  # 0.7 against a limit of 0.7
    assert verdicts["Continuity: inflow set against outflow measured"] == rp.OK  # 0.0499 against 0.05
    run = next(s for s in report.sections if s.title == "The run")
    rows = dict(row for row in run.tables[0].rows)
    assert rows["Finished"] == "yes" and rows["Computer time"] == "3 min 10 s" and rows["Reached"] == "20 s of 20 s"
    assert "20,192" in rp.render_html(report)
    project, case = _finished_case(tmp_path / "draining", outflow=0.065)
    lost = next(c for c in rp.build(project, case).checks if c.what.startswith("Continuity"))
    assert lost.verdict == rp.LOOK and "+30.0 %" in lost.found and "filling or draining" in lost.note


def _section(chainage, level, discharge, bed=0.0):
    n = len(chainage)
    ones, zeros = np.ones(n), np.zeros(n)
    depth = np.asarray(level) - bed
    return LongSection(np.asarray(chainage, float), np.asarray(chainage, float), zeros, zeros + bed, np.asarray(level, float),
                       depth, depth, ones, ones, np.asarray(discharge, float) * ones, zeros, zeros, zeros + 0.1, depth,
                       np.asarray(level, float), np.asarray(level, float), ones)  # fmt: skip


def test_an_ogee_crest_is_checked_against_the_wes_coefficient():
    from easyfoam import structures as sm

    project = EXAMPLES["ogee"]("ogee")
    st = project.shapes[0].structure
    hd, crest = sm.value(st, "design_head"), st.bed + sm.value(st, "height")
    x = np.linspace(st.station - 1.0, st.station - 0.05, 40)
    q = sm.WES_C * st.width * hd**1.5
    check = next(c for c in rp.hydraulic_checks(project, _section(x, np.full(x.size, crest + hd), q))
                 if "WES" in c.what)  # fmt: skip
    assert check.verdict == rp.OK and "C = 2.18" in check.found and "H/Hd = 1.00" in check.found
    low = rp.hydraulic_checks(project, _section(x, np.full(x.size, crest + 0.5 * hd), q))
    assert next(c for c in low if "WES" in c.what).verdict == rp.INFO  # far from the design head: C differs anyway


def test_the_normal_depth_of_a_channel_follows_manning():
    project = Project()
    project.channel = Channel(section="rectangular", bottom_width=2.0, slope=0.001)
    area, perimeter = 2.0 * 0.5, 2.0 + 2 * 0.5
    q = area * (area / perimeter) ** (2 / 3) * math.sqrt(0.001) / 0.03
    assert rp.normal_depth(project, q, 0.03) == pytest.approx(0.5, rel=1e-6)
    assert rp.normal_depth(project, 0.0, 0.03) is None


@pytest.mark.gui
def test_the_report_is_written_as_a_web_page_and_as_a_pdf(qapp, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from easyfoam.gui.main_window import MainWindow

    monkeypatch.setenv("EASYFOAM_STATE_FILE", str(tmp_path / "state.json"))
    _project, case = _finished_case(tmp_path, outflow=0.0499)
    w = MainWindow(enable_3d=False, detect=False)
    w.notify = lambda *args, **kw: None
    w.open_project(case)
    try:
        page = w.write_report(tmp_path / "report.html", open_after=False)
        text = page.read_text(encoding="utf-8")
        assert "Checked against theory" in text and "Agrees" in text and "What was modelled" in text
        assert "4 checks, 0 to look at" in w.statusBar().currentMessage()
        pdf = w.write_report(tmp_path / "report.pdf", open_after=False)
        assert pdf.read_bytes()[:5] == b"%PDF-" and pdf.stat().st_size > 2000
        assert w.report_action.isEnabled() and w.results_panel.report_button.isVisibleTo(w.results_panel)
    finally:
        w.close()
