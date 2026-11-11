"""v0.4 end-to-end: free-surface runs with a real interFoam."""

import numpy as np
import pytest

from easyfoam.examples import dambreak, weir
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.pipeline import Job, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def run(case, runtime, name, steps, parse_step=None):
    lines = []
    result = Job(case, runtime, name, steps, on_line=lines.append, parse_step=parse_step).run()
    assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-45:])
    return result


def test_dam_break_keeps_its_water_and_sends_it_across_the_tank(tmp_path, runtime):
    from easyfoam.results import CaseResults

    case = tmp_path / "dambreak"
    project = dambreak("dambreak")
    project.run.end_time, project.run.write_interval = 0.4, 0.1
    project.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, project))
    result = run(case, runtime, "run", prepare_run(case, project), parse_step="interFoam")

    history = result.parser.water_fraction
    assert len(history) > 20
    start, end = history[0][1], history[-1][1]
    assert start == pytest.approx(12 * 23 / 46**2, rel=0.01)  # the column covers 12 x 23 of the 46 x 46 cells
    assert end == pytest.approx(start, rel=0.01)  # no water created or lost

    results = CaseResults(case, project.name)
    assert results.times == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4])
    assert "alpha.water" in results.fields and "p_rgh" in results.fields
    data = results.read(0.4)
    centres = data.internal.cell_centers().points
    water = data.internal.cell_data["alpha.water"]
    far_corner = (centres[:, 0] > 0.5) & (centres[:, 2] < 0.05)
    assert water[far_corner].max() > 0.9  # the surge has reached the opposite wall
    assert np.all(water > -0.01) and np.all(water < 1.01)


def test_weir_case_meshes_and_water_flows_in(tmp_path, runtime):
    case = tmp_path / "weir"
    project = weir("weir")
    project.run.end_time, project.run.write_interval = 0.3, 0.3
    project.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, project))
    patches = {p.name: p.type for p in read_boundary(case) if p.n_faces}
    assert patches == {"inlet": "patch", "outlet": "patch", "bed": "wall", "atmosphere": "patch",
                       "sides": "patch", "weir": "wall"}  # fmt: skip

    result = run(case, runtime, "run", prepare_run(case, project), parse_step="interFoam")
    history = result.parser.water_fraction
    assert history[-1][0] == pytest.approx(0.3)
    # 0.05 m3/s for 0.3 s into a 4.5 m3 domain adds about 0.33 % of its volume
    gained = history[-1][1] - history[0][1]
    assert gained == pytest.approx(0.05 * 0.3 / 4.5, rel=0.25)
    assert (case / "0.3" / "alpha.water").is_file()
