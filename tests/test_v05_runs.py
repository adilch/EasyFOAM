"""v0.5 end-to-end: tailwater outlet, monitors, waves and the sharp-interface solver with real OpenFOAM."""

import numpy as np
import pytest

from easyfoam.examples import dambreak, waves
from easyfoam.foam.monitors import read_discharge, read_water_levels
from easyfoam.model import BaseFace, Boundary, Project
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


def thin_channel(length=4.0, height=1.0, cells=(80, 1, 20), depth=0.4):
    p = Project(name="channel")
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [length, 0.1, height], list(cells)
    base.faces["xMin"], base.faces["xMax"] = BaseFace("inlet", "patch"), BaseFace("outlet", "patch")
    base.faces["zMin"], base.faces["zMax"] = BaseFace("bed", "wall"), BaseFace("atmosphere", "patch")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("frontAndBack", "empty")
    p.mesh.snappy = False
    p.physics.solver, p.physics.turbulence = "interFoam", "laminar"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1e-6, 998.0
    p.physics.water_regions = [[0, 0, 0, length, 0.1, depth]]
    p.run.delta_t, p.run.max_courant = 0.001, 0.7
    return p


def test_tailwater_outlet_holds_its_level_and_the_monitors_report_depth_and_discharge(tmp_path, runtime):
    case = tmp_path / "channel"
    p = thin_channel()
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.01)
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=0.4)
    p.probes = [[1.0, 0.05, 0.2], [3.5, 0.05, 0.2]]
    p.flow_monitors = ["inlet", "outlet"]
    p.run.end_time, p.run.write_interval = 6.0, 6.0
    p.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, p))
    run(case, runtime, "run", prepare_run(case, p), parse_step="interFoam")

    times, depths = read_water_levels(case)
    assert times[-1] == pytest.approx(6.0) and len(depths) == 2
    assert depths[0][0] == pytest.approx(0.4, abs=0.01)  # both gauges start at the still-water depth
    # a free outflow would drain towards the critical depth of 0.10 m; the tailwater keeps it at its level
    assert depths[1][-1] == pytest.approx(0.4, rel=0.05)

    flow = read_discharge(case)
    assert set(flow) == {"inlet", "outlet"}
    late = np.array(flow["inlet"][0]) > 1.0
    # negative = into the domain; slightly below the nominal 0.01 because the inlet face at the water surface is part air
    assert np.array(flow["inlet"][1])[late].mean() == pytest.approx(-0.01, rel=0.05)
    assert 0.005 < flow["outlet"][1][-1] < 0.02  # water leaves at about the rate it enters


def test_wave_maker_sends_waves_of_the_requested_height_down_the_flume(tmp_path, runtime):
    case = tmp_path / "waves"
    p = waves("waves")
    p.run.end_time, p.run.write_interval = 8.0, 8.0
    p.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, p))
    result = run(case, runtime, "run", prepare_run(case, p), parse_step="interFoam")

    times, depths = read_water_levels(case)
    t = np.array(times)
    late = t > 4.5
    assert len(depths) == 2
    for gauge in depths:
        level = np.array(gauge)[late]
        assert level.mean() == pytest.approx(0.4, abs=0.01)
        assert level.max() - level.min() == pytest.approx(0.04, rel=0.25)  # the wave height that was asked for
    share = [value for _time, value in result.parser.water_fraction]
    assert share[-1] == pytest.approx(share[0], rel=0.01)  # the far end absorbs the waves without piling water up


def test_sharp_interface_solver_runs_the_dam_break_and_keeps_its_water(tmp_path, runtime):
    case = tmp_path / "dam"
    p = dambreak("dam")
    p.physics.solver = "interIsoFoam"
    p.run.end_time, p.run.write_interval = 0.3, 0.3
    p.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, p))
    result = run(case, runtime, "run", prepare_run(case, p), parse_step="interIsoFoam")
    assert result.parser.times[-1] == pytest.approx(0.3)
    assert (case / "0.3" / "alpha.water").is_file()
    share = [value for _time, value in result.parser.water_fraction]
    if share:  # the solver prints the water share in the same form as interFoam
        assert share[-1] == pytest.approx(share[0], rel=0.02)


def test_a_weir_drawn_in_cad_is_imported_meshed_and_run(tmp_path, runtime):
    gmsh = pytest.importorskip("gmsh")
    from easyfoam.foam.boundaryfile import read_boundary
    from easyfoam.geometry import import_geometry

    step = tmp_path / "weir.step"  # a weir block drawn in millimetres, as CAD files usually are
    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.addBox(1520, -500, -500, 250, 1500, 760)
    gmsh.model.occ.synchronize()
    gmsh.write(str(step))
    gmsh.finalize()

    case = tmp_path / "cadweir"
    p = thin_channel(length=4.0, height=0.8, cells=(80, 2, 16), depth=0.25)
    p.mesh.snappy = True
    p.mesh.base.faces["yMin"] = p.mesh.base.faces["yMax"] = BaseFace("sides", "patch")
    p.physics.water_regions = [[0, 0, 0, 1.5, 0.1, 0.25]]
    shape = import_geometry(case, step, unit="mm")
    shape.level_min = shape.level_max = 0
    p.shapes.append(shape)
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.005)
    p.boundaries["outlet"] = Boundary(kind="freeOutflow")
    p.run.end_time, p.run.write_interval = 0.2, 0.2
    p.save(case)

    run(case, runtime, "mesh", prepare_mesh(case, p))
    patches = {patch.name: patch for patch in read_boundary(case) if patch.n_faces}
    assert patches["weir"].type == "wall" and patches["weir"].n_faces > 20
    assert "Mesh OK." in (case / "log.checkMesh").read_text(errors="replace")
    result = run(case, runtime, "run", prepare_run(case, p), parse_step="interFoam")
    assert result.parser.times[-1] == pytest.approx(0.2)
