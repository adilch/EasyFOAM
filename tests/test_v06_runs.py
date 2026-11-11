"""v0.6 end-to-end checks with a real OpenFOAM."""

import numpy as np
import pytest

from easyfoam.examples import cavity, dambreak, pipe, waves
from easyfoam.foam.monitors import read_water_levels
from easyfoam.model import BaseFace, Boundary, Project, Tracer
from easyfoam.pipeline import Job, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes
from tests.test_v02_runs import coarse_sphere

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def solve(case, runtime, project):
    """Mesh and run a project; returns the run result."""
    project.save(case)
    for name, steps, parse in (("mesh", prepare_mesh, None), ("run", prepare_run, project.physics.solver)):
        lines = []
        result = Job(case, runtime, name, steps(case, project), on_line=lines.append, parse_step=parse).run()
        assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-45:])
    return result


def latest(case, project):
    from easyfoam.results import CaseResults

    return CaseResults(case, project.name).read()


@pytest.mark.parametrize("model", ["RNGkEpsilon", "kOmega", "kkLOmega"])
def test_added_turbulence_models_run(tmp_path, runtime, model):
    p = coarse_sphere()
    p.physics.turbulence = model
    p.run.end_time = p.run.write_interval = 5
    assert solve(tmp_path / "sphere", runtime, p).parser.times[-1] == 5.0


def test_resolving_the_boundary_layer_runs(tmp_path, runtime):
    p = coarse_sphere()
    p.physics.wall_treatment = "lowRe"
    p.run.end_time = p.run.write_interval = 5
    assert solve(tmp_path / "sphere", runtime, p).parser.times[-1] == 5.0


def test_shear_thinning_fluid_in_the_cavity(tmp_path, runtime):
    p = cavity("cavity")
    p.physics.viscosity_model = "CrossPowerLaw"
    p.physics.viscosity_coeffs = {"nu0": 0.01, "nuInf": 1e-04, "m": 0.4, "n": 3.0}
    p.run.end_time = p.run.write_interval = 20
    assert solve(tmp_path / "cavity", runtime, p).parser.times[-1] == 20.0
    assert "CrossPowerLaw" in (tmp_path / "cavity" / "log.simpleFoam").read_text(errors="replace")


def test_velocity_limit_caps_the_flow(tmp_path, runtime):
    p = cavity("cavity")  # the lid moves at 1 m/s
    p.physics.max_velocity = 0.2
    p.run.end_time = p.run.write_interval = 30
    solve(tmp_path / "cavity", runtime, p)
    speed = np.linalg.norm(latest(tmp_path / "cavity", p).internal.cell_data["U"], axis=1)
    assert speed.max() <= 0.2 * 1.02


def test_a_tracer_enters_with_the_inflow_and_stays_between_zero_and_one(tmp_path, runtime):
    p = pipe("pipe")
    p.mesh.base.cells = [40, 6, 6]
    p.shapes[0].level_min = p.shapes[0].level_max = 0
    p.tracers = [Tracer("dye", 1e-06)]
    p.boundaries["inlet"].tracer_value = 1.0
    p.run.end_time = p.run.write_interval = 150
    p.run.residual_target = 0
    p.run.processors = 2
    solve(tmp_path / "pipe", runtime, p)
    grid = latest(tmp_path / "pipe", p).internal
    dye, x = grid.cell_data["dye"], grid.cell_centers().points[:, 0]
    assert dye.min() > -0.02 and dye.max() < 1.02
    assert dye[x < 0.3].mean() > 0.8  # the pipe fills with dyed fluid from the inlet end


def test_contact_angle_on_the_walls_of_the_dam_break(tmp_path, runtime):
    p = dambreak("dam")
    p.boundaries["walls"] = Boundary(kind="wall", contact_angle=45.0)
    p.run.end_time = p.run.write_interval = 0.05
    assert solve(tmp_path / "dam", runtime, p).parser.times[-1] == pytest.approx(0.05)


def test_a_solitary_wave_passes_the_first_gauge(tmp_path, runtime):
    p = waves("solitary")
    p.boundaries["inlet"] = Boundary(kind="waveInlet", wave_height=0.05, wave_model="solitary")
    p.run.end_time = p.run.write_interval = 3.0
    solve(tmp_path / "solitary", runtime, p)
    _times, depths = read_water_levels(tmp_path / "solitary")
    assert max(depths[0]) > 0.4 + 0.6 * 0.05  # the crest rose well above the 0.4 m still water


def test_cnoidal_waves_run(tmp_path, runtime):
    p = waves("cnoidal")
    p.boundaries["inlet"] = Boundary(kind="waveInlet", wave_height=0.04, wave_period=2.5, wave_model="cnoidal")
    p.run.end_time = p.run.write_interval = 2.0
    assert solve(tmp_path / "cnoidal", runtime, p).parser.times[-1] == pytest.approx(2.0)


def tank():
    """A small fully three-dimensional dam break."""
    p = Project(name="tank")
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [0.6, 0.2, 0.6], [24, 8, 24]
    for face in ("xMin", "xMax", "yMin", "yMax", "zMin"):
        base.faces[face] = BaseFace("walls", "wall")
    base.faces["zMax"] = BaseFace("atmosphere", "patch")
    p.mesh.snappy = False
    p.physics.solver, p.physics.turbulence = "interFoam", "laminar"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1e-6, 998.0
    p.physics.water_regions = [[0, 0, 0, 0.15, 0.2, 0.3]]
    p.physics.adaptive_levels = 1
    p.run.end_time, p.run.delta_t, p.run.write_interval, p.run.max_courant = 0.1, 0.001, 0.1, 0.5
    return p


@pytest.mark.parametrize("processors", [1, 2])
def test_mesh_is_refined_at_the_water_surface_while_running(tmp_path, runtime, processors):
    p = tank()
    p.run.processors = processors
    result = solve(tmp_path / "tank", runtime, p)
    assert result.parser.times[-1] == pytest.approx(0.1)
    grid = latest(tmp_path / "tank", p).internal
    assert grid.n_cells > 24 * 8 * 24 * 1.2  # cells were added along the water surface
    water = grid.cell_data["alpha.water"]
    assert 0.11 < float((water * grid.compute_cell_sizes().cell_data["Volume"]).sum()) / 0.072 < 0.14
