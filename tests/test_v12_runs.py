"""v0.12 end-to-end: a channel built in the program and the ground of a surveyed valley, meshed and run."""

import math

import numpy as np
import pytest

from easyfoam import channel as chm
from easyfoam import hydraulics as hy
from easyfoam import terrain as tr
from easyfoam.foam.monitors import read_discharge
from easyfoam.model import Channel, ChannelSegment, Project
from easyfoam.pipeline import Job, prepare_mesh, prepare_run
from easyfoam.results import CaseResults
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def run(case, runtime, project, name, steps, parse=None):
    lines = []
    result = Job(case, runtime, name, steps(case, project), on_line=lines.append, parse_step=parse).run()
    assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-45:])


def water_volume(data):
    cells = data.internal.compute_cell_sizes(length=False, area=False, volume=True)
    return float((np.asarray(cells.cell_data["Volume"]) * np.asarray(data.internal.cell_data["alpha.water"])).sum())


def test_a_bent_trapezoidal_channel_is_meshed_filled_and_run(tmp_path, runtime):
    case = tmp_path / "bend"
    ch = Channel(section="trapezoidal", bottom_width=1.0, depth=0.5, side_slope=1.0, slope=0.002, freeboard=0.15,
                 cell_size=0.1, water_depth=0.35,
                 segments=[ChannelSegment("straight", length=6), ChannelSegment("bend", radius=8, angle=60),
                           ChannelSegment("straight", length=6)])  # fmt: skip
    p = Project(name="bend")
    chm.use_channel(p, ch)
    p.boundaries["inlet"].flow_rate = 0.2
    p.run.end_time, p.run.write_interval, p.run.max_courant, p.run.processors = 5.0, 2.5, 0.8, 4
    p.save(case)
    run(case, runtime, p, "mesh", prepare_mesh)
    assert "Mesh OK." in (case / "log.checkMesh").read_text()
    run(case, runtime, p, "run", prepare_run, "interFoam")
    results = CaseResults(case, p.name)
    area, _perimeter = chm.wetted(ch, ch.water_depth)
    # the water at the start fills the channel to its depth, round the bend too
    assert water_volume(results.read(0.0)) == pytest.approx(area * chm.total_length(ch), rel=0.01)
    section = hy.long_section(results.read(results.times[-1]), p, case)
    assert section.chainage[-1] == pytest.approx(chm.total_length(ch), abs=0.2)  # along the curved centreline
    assert section.wet.all()
    assert np.nanmedian(section.depth) == pytest.approx(ch.water_depth, rel=0.15)
    assert section.bed[0] == pytest.approx(ch.slope * chm.total_length(ch), abs=0.01)  # the bed falls to 0


def valley_survey(path, size=1.0):
    """A valley falling to the east-north-east with a meandering channel 1.2 m deep, as an ASCII grid."""
    x0, y0 = 512_000.0, 4_181_000.0
    along = np.arange(int(160 / size) + 1) * size
    across = np.arange(int(100 / size) + 1) * size - 50
    a, c = np.meshgrid(along, across)
    z = 100 - 0.004 * a + 0.0008 * c**2 - 1.2 * np.exp(-(((c - 8 * np.sin(2 * math.pi * a / 80)) / 3.0) ** 2))
    angle = math.radians(30)
    east = x0 + a * math.cos(angle) - c * math.sin(angle)
    north = y0 + a * math.sin(angle) + c * math.cos(angle)
    e = np.arange(east.min(), east.max() + size, size)
    n = np.arange(north.min(), north.max() + size, size)
    grid = np.full((len(n), len(e)), -9999.0)
    grid[np.round((north - n[0]) / size).astype(int), np.round((east - e[0]) / size).astype(int)] = z
    rows = "\n".join(" ".join(f"{v:.3f}" for v in row) for row in grid[::-1])
    path.write_text(f"ncols {len(e)}\nnrows {len(n)}\nxllcenter {e[0]:.3f}\nyllcenter {n[0]:.3f}\ncellsize {size}\n"
                    f"NODATA_value -9999\n{rows}\n")  # fmt: skip
    return path


def test_water_flows_down_a_surveyed_valley(tmp_path, runtime):
    case = tmp_path / "valley"
    survey = tr.read_survey(valley_survey(tmp_path / "valley.asc"))
    ground = tr.ground(survey, 1.0, (512_000.0, 4_181_000.0), angle=30.0, region=(5, -30, 155, 30))
    p = Project(name="valley")
    case.mkdir()
    tr.use_terrain(p, case, ground, cell_size=1.0, water_level=99.3, top=101.5, discharge=4.0)
    p.physics.turbulence = "kOmegaSST"
    p.run.end_time, p.run.write_interval, p.run.max_courant, p.run.processors = 20.0, 10.0, 0.8, 8
    p.save(case)
    run(case, runtime, p, "mesh", prepare_mesh)
    report = (case / "log.checkMesh").read_text()
    failed = [line for line in report.splitlines() if line.strip().startswith("***")]
    assert all("skew" in line for line in failed)  # a few snapped faces on the ground may be skewed; nothing else
    run(case, runtime, p, "run", prepare_run, "interFoam")
    results = CaseResults(case, p.name)
    start = water_volume(results.read(0.0))
    assert start > 0  # the low ground starts filled to 99.3 m
    end = results.read(results.times[-1])
    section = hy.long_section(end, p, case)
    assert section.wet.all()  # water all along the reach, round the meanders
    assert np.nanmax(section.water_level) < 100.0  # held within the valley
    assert water_volume(end) > start  # 4 m³/s coming in
    _times, flows = read_discharge(case)["outlet"]
    assert np.all(np.isfinite(flows))
