"""v0.9 end-to-end: hydraulic results of real OpenFOAM runs, checked against hand calculations."""

import numpy as np
import pytest

from easyfoam import hydraulics as hy
from easyfoam.examples import jump, weir
from easyfoam.pipeline import Job, post_steps_for, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def solve(case, runtime, project):
    project.save(case)
    for name, steps, parse in (("mesh", prepare_mesh, None), ("run", prepare_run, project.physics.solver)):
        lines = []
        result = Job(case, runtime, name, steps(case, project), on_line=lines.append, parse_step=parse).run()
        assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-45:])


def averaged(case, project, count):
    from easyfoam.results import CaseResults

    results = CaseResults(case, project.name)
    times = [t for t in results.times if t > 0][-count:]
    return results, hy.average_sections([hy.long_section(results.read(t), project, case, time=t) for t in times])


def test_jump_below_a_sluice_gate_matches_belanger_and_the_gate_force_the_momentum_balance(tmp_path, runtime):
    case = tmp_path / "jump"
    p = jump("jump")
    p.run.end_time, p.run.write_interval = 20.0, 1.0
    solve(case, runtime, p)
    results, section = averaged(case, p, 5)

    # the discharge set at the inlet passes the reservoir and the jet (not counted under the gate's lip itself,
    # where the sampling lines graze the gate)
    inflow = p.boundaries["inlet"].flow_rate
    pool = (section.chainage > 0.2) & (section.chainage < 0.9) & section.wet
    jet_reach = (section.chainage > 1.2) & (section.chainage < 2.5) & section.wet
    assert np.allclose(section.discharge[pool], inflow, rtol=0.03)
    assert np.allclose(section.discharge[jet_reach], inflow, rtol=0.05)  # a thin fast jet, a few cells deep

    jumps = hy.find_jumps(section)
    assert len(jumps) == 1
    found = jumps[0]
    assert 2.5 < found.froude1 < 4.5 and found.kind == "oscillating jump"
    assert found.y2 == pytest.approx(found.y2_theory, rel=0.12)  # Bélanger, time-averaged
    assert found.loss == pytest.approx(found.loss_theory, rel=0.35) and found.loss > 0

    # momentum between the reservoir and the vena contracta gives the force on the gate (per metre width)
    rho, g, width = p.physics.rho, 9.81, p.mesh.base.max[1] - p.mesh.base.min[1]
    pool = (section.chainage > 0.3) & (section.chainage < 0.6)
    y0 = float(np.nanmean(section.hydraulic_depth[pool]))
    jet = (section.chainage > 1.1) & (section.chainage < 2.6)
    y1 = float(np.nanmin(np.where(jet, section.hydraulic_depth, np.inf)))
    q = inflow / width
    momentum = 0.5 * rho * g * (y0**2 - y1**2) - rho * q * q * (1 / y1 - 1 / y0)
    data = results.read(results.times[-1])
    loads = hy.structure_loads([data.patches["gate"]], p)
    assert loads.width == pytest.approx(width)
    assert loads.force[0] / width == pytest.approx(momentum, rel=0.10)

    # the pressure on the upstream face of the gate is positive under water and about zero in the air
    profile = hy.pressure_profile(data.patches["gate"], p)
    assert profile.x[0] == pytest.approx(1.0) and profile.head.max() > 0.3
    assert abs(profile.head[0]) < 0.01  # the top of the gate is in the air

    # the bed under the fast jet carries far more shear than the pool upstream
    lines = []
    shear = Job(case, runtime, "compute", post_steps_for(case, p, "wallShearStress"), on_line=lines.append).run()
    assert shear.ok, "\n".join(lines[-20:])
    from easyfoam.results import CaseResults

    bed = CaseResults(case, p.name).read(results.times[-1]).patches["bed"]
    hy.add_bed_shear(bed, p, hy.critical_shear_stress(0.002))
    x = np.asarray(bed.cell_centers().points)[:, 0]
    stress = np.asarray(bed.cell_data["bedShearStress"])
    assert stress[(x > 1.5) & (x < 2.5)].mean() > 10 * stress[(x > 0.2) & (x < 0.8)].mean()
    assert bed.cell_data["sedimentMobility"].max() > 1  # sand would be scoured below the gate


def test_flow_over_the_weir_passes_critical_depth_on_the_crest(tmp_path, runtime):
    case = tmp_path / "weir"
    p = weir("weir")
    p.run.end_time, p.run.write_interval = 10.0, 1.0
    solve(case, runtime, p)
    _results, section = averaged(case, p, 3)
    controls = hy.find_controls(section)
    assert controls, "no control section found"
    crest = controls[0]
    assert 2.52 < crest.chainage < 2.80  # on the crest, towards its downstream edge
    assert crest.depth == pytest.approx(crest.critical_depth, rel=0.15)
    assert hy.find_jumps(section) == []  # the overfall at the downstream face is not a jump
    assert np.nanmax(section.froude[section.chainage > 3.2]) > 2  # supercritical below the weir


def test_the_long_section_command_saves_a_table(tmp_path, runtime):
    from easyfoam.cli import main

    case = tmp_path / "jump"
    p = jump("jump")
    p.run.end_time, p.run.write_interval = 2.0, 1.0
    solve(case, runtime, p)
    assert main(["long-section", str(case), "--average", "2", "--csv", str(tmp_path / "long.csv")]) == 0
    rows = (tmp_path / "long.csv").read_text().splitlines()
    assert len(rows) == 301 and rows[0].startswith("chainage [m]")
    assert main(["loads", str(case), "gate"]) == 0
