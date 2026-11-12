"""Reading results back: quantities computed after the run must be offered too."""

import pytest

from easyfoam.examples import cavity
from easyfoam.pipeline import Job, post_steps_for, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


def test_a_quantity_computed_for_the_latest_result_is_listed_although_earlier_times_lack_it(tmp_path):
    pytest.importorskip("pyvista")
    from easyfoam.results import CaseResults

    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    p = cavity("cavity")
    p.run.end_time, p.run.write_interval, p.run.residual_target = 20, 10, 0.0  # two saved results: 10 and 20
    case = tmp_path / "cavity"
    p.save(case)
    for name, steps in (
        ("mesh", lambda: prepare_mesh(case, p)),
        ("run", lambda: prepare_run(case, p)),
        ("compute", lambda: post_steps_for(case, p, "vorticity")),
    ):
        lines = []
        result = Job(case, found[0], name, steps(), on_line=lines.append).run()
        assert result.ok, f"{name} failed:\n" + "\n".join(lines[-30:])
    results = CaseResults(case, p.name)
    assert results.times[-2:] == [10.0, 20.0]
    assert "vorticity" in results.fields
    assert "vorticity" in results.read(20.0).internal.cell_data
    assert "U" in results.read(10.0).internal.cell_data  # earlier times still read, without the extra quantity
