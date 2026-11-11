"""v0.2 end-to-end checks against a real OpenFOAM installation."""

import numpy as np
import pytest

from easyfoam.casegen.setup import parse_yplus
from easyfoam.examples import pipe, sphere
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.foam.coeffs import read_coefficients
from easyfoam.geometry import fit_base_mesh, import_stl
from easyfoam.model import Boundary, Project
from easyfoam.pipeline import Job, post_steps_for, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes
from tests.test_v02_core import CUBE_FACES, ascii_stl, cube

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
    assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-40:])
    return result, lines


def coarse_sphere(name="sphere"):
    p = sphere(name)
    p.shapes[0].level_min = p.shapes[0].level_max = 1
    p.shapes[1].region_level = 0
    p.mesh.base.cells = [20, 10, 10]
    p.run.processors = 2
    return p


@pytest.fixture(scope="module")
def solved_sphere(tmp_path_factory, runtime):
    """A coarse sphere case, meshed and run for 30 iterations with force monitoring."""
    case = tmp_path_factory.mktemp("forces") / "sphere"
    project = coarse_sphere()
    project.forces.enabled = True
    project.forces.ref_area, project.forces.ref_length = np.pi * 0.25, 1.0
    project.run.end_time = project.run.write_interval = 30
    project.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, project))
    run(case, runtime, "run", prepare_run(case, project), parse_step="simpleFoam")
    return case, project


def test_drag_coefficient_history_is_written_every_iteration(solved_sphere):
    case, _project = solved_sphere
    history = read_coefficients(case)
    assert history["Time"] == [float(i) for i in range(1, 31)]
    assert 0.05 < history["Cd"][-1] < 2.0
    assert abs(history["Cl"][-1]) < 0.5  # a sphere has no lift to speak of


def test_y_plus_is_computed_and_reported_for_the_wall(solved_sphere, runtime):
    from easyfoam.results import CaseResults

    case, project = solved_sphere
    run(case, runtime, "post", post_steps_for(case, project, "yPlus"))
    report = parse_yplus((case / "log.yPlus").read_text(errors="replace"))
    low, high, mean = report["ball"]
    assert 0 < low <= mean <= high
    assert "yPlus" in CaseResults(case, project.name).fields


@pytest.mark.parametrize("model", ["kEpsilon", "realizableKE", "SpalartAllmaras"])
def test_each_turbulence_model_runs_from_a_potential_flow_start(tmp_path, runtime, model):
    case = tmp_path / "sphere"
    project = coarse_sphere()
    project.physics.turbulence = model
    project.physics.potential_init = True
    project.run.end_time = project.run.write_interval = 5
    project.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, project))
    result, _ = run(case, runtime, "run", prepare_run(case, project), parse_step="simpleFoam")
    assert result.parser.times[-1] == 5.0
    assert (case / "log.potentialFoam").is_file()


def test_laminar_pipe_flow_develops_the_textbook_parabolic_profile(tmp_path, runtime):
    from easyfoam.results import CaseResults

    case = tmp_path / "pipe"
    project = pipe("pipe")
    project.run.processors = 4
    project.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, project))
    patches = {p.name: p for p in read_boundary(case) if p.n_faces}
    assert set(patches) == {"inlet", "outlet", "tube"}
    assert patches["tube"].type == "wall"

    result, _ = run(case, runtime, "run", prepare_run(case, project), parse_step="simpleFoam")
    assert result.parser.finished
    data = CaseResults(case, project.name).read()
    centres = data.internal.cell_centers().points
    speed = data.internal.cell_data["U"][:, 0]
    downstream = centres[:, 0] > 1.6  # past the entrance length (about 0.6 m at Re = 50)
    # Hagen-Poiseuille: the centre-line speed is twice the mean speed of 1 m/s
    assert speed[downstream].max() == pytest.approx(2.0, rel=0.07)
    near_wall = downstream & (np.hypot(centres[:, 1], centres[:, 2]) > 0.085)
    assert speed[near_wall].mean() < 0.6


def duct_stl(path):
    triangles = cube(scale=(2.0, 0.2, 0.2))
    inlet = [i for i, f in enumerate(CUBE_FACES) if all(v in (0, 3, 4, 7) for v in f)]
    outlet = [i for i, f in enumerate(CUBE_FACES) if all(v in (1, 2, 5, 6) for v in f)]
    wall = [i for i in range(len(CUBE_FACES)) if i not in inlet + outlet]
    path.write_text(ascii_stl({"inlet": triangles[inlet], "outlet": triangles[outlet], "wall": triangles[wall]}))


def test_a_closed_stl_with_named_regions_becomes_an_internal_flow_case(tmp_path, runtime):
    source = tmp_path / "duct.stl"
    duct_stl(source)
    case = tmp_path / "duct"
    project = Project(name="duct")
    shape = import_stl(case, source)
    assert list(shape.regions) == ["inlet", "outlet", "wall"]
    shape.regions["inlet"] = shape.regions["outlet"] = "patch"
    shape.level_min = shape.level_max = 0
    project.shapes.append(shape)
    project.mesh.fluid_inside = "duct"
    fit_base_mesh(project, case, cell_size=0.025)
    project.physics.turbulence = "laminar"
    project.physics.nu = 0.01
    project.boundaries["duct_inlet"] = Boundary(kind="velocityInlet", velocity=[1.0, 0.0, 0.0])
    project.boundaries["duct_outlet"] = Boundary(kind="pressureOutlet")
    project.run.end_time = project.run.write_interval = 20
    project.save(case)

    run(case, runtime, "mesh", prepare_mesh(case, project))
    patches = {p.name: p.type for p in read_boundary(case) if p.n_faces}
    assert patches == {"duct_inlet": "patch", "duct_outlet": "patch", "duct_wall": "wall"}
    result, _ = run(case, runtime, "run", prepare_run(case, project), parse_step="simpleFoam")
    assert result.parser.times[-1] == 20.0


def test_a_single_solid_ascii_stl_gives_one_patch_named_after_the_shape(tmp_path, runtime):
    source = tmp_path / "blk.stl"
    source.write_text(ascii_stl({"part": cube(scale=(1.0, 0.5, 0.5))}))
    case = tmp_path / "blk"
    project = Project(name="blk")
    shape = import_stl(case, source)
    shape.level_min = shape.level_max = 1
    project.shapes.append(shape)
    fit_base_mesh(project, case, cell_size=0.25, upstream=1, downstream=2, lateral=1)
    project.save(case)
    run(case, runtime, "mesh", prepare_mesh(case, project))
    walls = [p.name for p in read_boundary(case) if p.type == "wall"]
    assert walls == ["blk"]
