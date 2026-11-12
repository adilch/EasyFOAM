"""v0.7: moving gates (prescribed motion) and floating bodies (6DoF)."""

import math

import pytest

from easyfoam import casegen
from easyfoam.casegen.motion import point_displacement
from easyfoam.casegen.setup import dynamic_mesh_dict, field_dicts, fv_solution
from easyfoam.checks import project_issues
from easyfoam.foam.boundaryfile import Patch
from easyfoam.geometry import mass_properties
from easyfoam.model import BaseFace, Motion, Project, Shape
from tests.test_v02_core import ascii_stl, cube

PATCHES = [
    Patch("inlet", "patch", 10, 0),
    Patch("outlet", "patch", 10, 10),
    Patch("atmosphere", "patch", 40, 20),
    Patch("bed", "wall", 40, 60),
    Patch("sides", "empty", 80, 100),
    Patch("gate", "wall", 30, 180),
    Patch("pier", "wall", 30, 210),
]


def flume(motion):
    p = Project(name="flume")
    p.physics.solver, p.physics.turbulence = "interFoam", "laminar"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1e-06, 998.0
    p.physics.water_regions = [[0, 0, 0, 1, 1, 0.4]]
    base = p.mesh.base
    base.faces["xMin"], base.faces["xMax"] = BaseFace("inlet", "patch"), BaseFace("outlet", "patch")
    base.faces["zMin"], base.faces["zMax"] = BaseFace("bed", "wall"), BaseFace("atmosphere", "patch")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("sides", "empty")
    p.shapes.append(Shape("gate", kind="box", min=[1.0, -1, 0.1], max=[1.2, 2, 0.5], motion=motion))
    p.shapes.append(Shape("pier", kind="box", min=[3, -1, -1], max=[3.2, 2, 0.3]))
    return p


def lifting():
    return flume(Motion(kind="move", displacement=[0.0, 0.0, 0.1], start=0.2, duration=1.0))


def floating(freedom="heave"):
    return flume(Motion(kind="floating", density=500.0, freedom=freedom))


# --- model and mass properties -----------------------------------------------


def test_shapes_are_fixed_unless_given_a_motion_and_the_motion_is_saved(tmp_path):
    p = lifting()
    assert p.shapes[1].motion.kind == "none"
    p.save(tmp_path)
    assert Project.load(tmp_path).shapes[0].motion == Motion(kind="move", displacement=[0.0, 0.0, 0.1], start=0.2)


def test_mass_centre_and_inertia_of_primitives(tmp_path):
    mass, centre, inertia = mass_properties(Shape("b", kind="box", min=[0, 0, 0], max=[1, 2, 3]), tmp_path, 500.0)
    assert mass == pytest.approx(3000.0) and centre == pytest.approx([0.5, 1.0, 1.5])
    assert inertia == pytest.approx([3000 / 12 * 13, 3000 / 12 * 10, 3000 / 12 * 5])
    mass, _centre, inertia = mass_properties(Shape("s", kind="sphere", radius=0.5), tmp_path, 1000.0)
    assert mass == pytest.approx(1000 * 4 / 3 * math.pi * 0.125)
    assert inertia == pytest.approx([0.4 * mass * 0.25] * 3)
    rod = Shape("c", kind="cylinder", point1=[0, 0, 0], point2=[2, 0, 0], radius=0.5)
    mass, centre, inertia = mass_properties(rod, tmp_path, 100.0)
    assert mass == pytest.approx(100 * math.pi * 0.25 * 2) and centre == pytest.approx([1, 0, 0])
    assert inertia == pytest.approx([0.5 * mass * 0.25, mass / 12 * (0.75 + 4), mass / 12 * (0.75 + 4)])


def test_mass_properties_of_a_closed_stl_match_the_same_box(tmp_path):
    folder = tmp_path / "constant" / "triSurface"
    folder.mkdir(parents=True)
    (folder / "blk.stl").write_text(ascii_stl({"part": cube(scale=(1.0, 2.0, 3.0))}))
    mass, centre, inertia = mass_properties(Shape("blk", file="blk.stl"), tmp_path, 500.0)
    assert mass == pytest.approx(3000.0) and centre == pytest.approx([0.5, 1.0, 1.5])
    assert inertia == pytest.approx([3250.0, 2500.0, 1250.0])


# --- a gate that is moved -----------------------------------------------------


def test_a_moved_gate_deforms_the_mesh_around_it():
    d = dynamic_mesh_dict(lifting(), PATCHES)
    assert d["dynamicFvMesh"] == "dynamicMotionSolverFvMesh"
    assert d["motionSolver"] == "displacementLaplacian"
    assert d["displacementLaplacianCoeffs"]["diffusivity"] == "quadratic inverseDistance (gate)"


def test_the_gate_follows_a_displacement_table_and_the_rest_of_the_boundary_stays_put():
    cls, data = point_displacement(lifting(), PATCHES)
    assert cls == "pointVectorField" and data["dimensions"] == "[0 1 0 0 0 0 0]"
    f = data["boundaryField"]
    assert f["gate"] == {
        "type": "uniformFixedValue",
        "uniformValue": "table ((0 (0 0 0)) (0.2 (0 0 0)) (1.2 (0 0 0.1)))",
    }
    assert f["pier"] == {"type": "fixedValue", "value": "uniform (0 0 0)"}  # another, fixed shape
    assert f["bed"] == {"type": "slip"}  # flat faces of the base mesh let the points slide along them
    assert f["sides"] == {"type": "empty"}


def test_an_oscillating_body():
    p = flume(Motion(kind="oscillate", amplitude=[0.05, 0.0, 0.0], period=2.0))
    gate = point_displacement(p, PATCHES)[1]["boundaryField"]["gate"]
    assert gate["type"] == "oscillatingDisplacement" and gate["amplitude"] == [0.05, 0.0, 0.0]
    assert gate["omega"] == pytest.approx(math.pi)


def test_the_water_feels_the_moving_wall_and_the_solver_is_told_the_mesh_moves():
    p = lifting()
    assert field_dicts(p, PATCHES)["U"][1]["boundaryField"]["gate"] == {
        "type": "movingWallVelocity", "value": "uniform (0 0 0)",
    }  # fmt: skip
    assert field_dicts(p, PATCHES)["U"][1]["boundaryField"]["pier"] == {"type": "noSlip"}
    solution = fv_solution(p)
    assert '"cellDisplacement.*"' in solution["solvers"]
    assert solution["PIMPLE"]["correctPhi"] is True
    files = casegen.setup_files(p, PATCHES)
    assert {"0/pointDisplacement", "constant/dynamicMeshDict"} <= set(files)
    still = flume(Motion())
    assert "0/pointDisplacement" not in casegen.setup_files(still, PATCHES)
    assert "correctPhi" not in fv_solution(still)["PIMPLE"]


# --- a floating body ----------------------------------------------------------


def test_a_floating_body_gets_its_mass_inertia_and_freedom_of_motion():
    d = dynamic_mesh_dict(floating(), PATCHES)
    assert (d["motionSolverLibs"], d["motionSolver"]) == (["rigidBodyMeshMotion"], "rigidBodyMotion")
    body = d["rigidBodyMotionCoeffs"]["bodies"]["gate"]
    volume = 0.2 * 3.0 * 0.4
    assert body["type"] == "rigidBody" and body["mass"] == pytest.approx(500.0 * volume)
    assert body["centreOfMass"] == [0, 0, 0]
    assert body["transform"] == "(1 0 0 0 1 0 0 0 1) (1.1 0.5 0.3)"  # placed at its centre
    assert body["patches"] == ["gate"]
    assert body["joint"] == {"type": "composite", "joints": [{"type": "Pz"}]}  # heave only
    assert 0 < body["innerDistance"] < body["outerDistance"]


def test_freedom_of_a_floating_body():
    def joint(freedom):
        return dynamic_mesh_dict(floating(freedom), PATCHES)["rigidBodyMotionCoeffs"]["bodies"]["gate"]["joint"]

    assert joint("free") == {"type": "floating"}
    assert joint("plane") == {"type": "composite", "joints": [{"type": "Px"}, {"type": "Pz"}, {"type": "Ry"}]}


def test_a_floating_body_reports_its_own_displacement_and_needs_tighter_coupling():
    p = floating()
    body = point_displacement(p, PATCHES)[1]["boundaryField"]
    assert body["gate"] == {"type": "calculated", "value": "uniform (0 0 0)"}
    assert body["bed"] == {"type": "fixedValue", "value": "uniform (0 0 0)"}
    pimple = fv_solution(p)["PIMPLE"]
    assert (pimple["nOuterCorrectors"], pimple["moveMeshOuterCorrectors"], pimple["correctPhi"]) == (3, True, True)


# --- checks -------------------------------------------------------------------


def errors(project):
    return [i.text for i in project_issues(project, PATCHES, True) if i.level == "error"]


def test_motion_needs_a_transient_run_and_floating_needs_water():
    assert errors(lifting()) == []
    steady = lifting()
    steady.physics.solver = "simpleFoam"
    assert any("transient" in text for text in errors(steady))
    dry = floating()
    dry.physics.solver = "pimpleFoam"
    assert any("free-surface" in text for text in errors(dry))


def test_motion_and_surface_refinement_cannot_be_combined():
    p = lifting()
    p.physics.adaptive_levels = 1
    assert any("refin" in text for text in errors(p))


# --- mesh zone, log and examples ----------------------------------------------


def test_the_deforming_zone_of_a_floating_body_stays_clear_of_the_tank_walls():
    p = Project(name="tank")
    p.physics.solver = "interFoam"
    p.mesh.base.min, p.mesh.base.max = [0, 0, 0], [1.0, 0.5, 0.9]
    p.shapes.append(
        Shape("box", kind="box", min=[0.35, 0.15, 0.35], max=[0.65, 0.35, 0.55], motion=Motion(kind="floating"))
    )
    body = dynamic_mesh_dict(p, [Patch("box", "wall", 1, 0)])["rigidBodyMotionCoeffs"]["bodies"]["box"]
    assert body["outerDistance"] <= 0.9 * 0.15 + 1e-12  # the nearest wall is 0.15 m away (in y)
    assert 0 < body["innerDistance"] < body["outerDistance"]


def test_the_position_of_a_floating_body_is_read_from_the_log():
    from easyfoam.foam.logparser import LogParser

    parser = LogParser()
    for line in (
        "Time = 0.1",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.45)",
        "    Linear velocity: (0 0 -0.1)",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.44)",  # a later pass of the same time step replaces the first
        "Time = 0.2",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.41)",
    ):
        parser.feed(line)
    assert parser.body_positions == {"box": [(0.1, [0.5, 0.4, 0.44]), (0.2, [0.5, 0.4, 0.41])]}


def test_the_tilt_of_a_floating_body_is_read_from_the_log():
    from easyfoam.foam.logparser import LogParser

    angle = math.radians(10.0)
    c, s = math.cos(angle), math.sin(angle)
    parser = LogParser()
    for line in (
        "Time = 0.1",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.45)",
        f"    Orientation: ({c} 0 {s} 0 1 0 {-s} 0 {c})",  # turned 10 degrees about the y axis
        "Time = 0.2",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.45)",
        f"    Orientation: (1 0 0 0 {c} {-s} 0 {s} {c})",  # 10 degrees about the x axis
        "Time = 0.3",
        "Rigid-body motion of the box",
        "    Centre of rotation: (0.5 0.4 0.45)",
        f"    Orientation: ({c} {-s} 0 {s} {c} 0 0 0 1)",  # 10 degrees about the z axis
    ):
        parser.feed(line)
    times, angles = zip(*parser.body_rotations["box"])
    assert times == (0.1, 0.2, 0.3)
    assert angles[0] == pytest.approx([0, 10, 0], abs=1e-9)
    assert angles[1] == pytest.approx([10, 0, 0], abs=1e-9)
    assert angles[2] == pytest.approx([0, 0, 10], abs=1e-9)


def test_where_a_moved_shape_is_at_a_given_time():
    from easyfoam.casegen.motion import displacement_at

    lift = Motion(kind="move", displacement=[0.0, 0.0, 0.1], start=0.2, duration=1.0)
    assert displacement_at(lift, 0.1) == [0.0, 0.0, 0.0]
    assert displacement_at(lift, 0.7) == pytest.approx([0.0, 0.0, 0.05])
    assert displacement_at(lift, 5.0) == pytest.approx([0.0, 0.0, 0.1])
    swing = Motion(kind="oscillate", amplitude=[0.05, 0.0, 0.0], period=2.0)
    assert displacement_at(swing, 0.5) == pytest.approx([0.05, 0.0, 0.0])  # a quarter of a period
    assert displacement_at(swing, 1.0) == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)


def test_motion_settings_that_cannot_work_are_reported():
    p = lifting()
    p.shapes[0].motion.duration = 0.0
    assert any("take" in text for text in errors(p))
    p = flume(Motion(kind="oscillate", period=0.0))
    assert any("period" in text for text in errors(p))
    p = floating()
    p.shapes[0].motion.density = 0.0
    assert any("density" in text for text in errors(p))
    p = floating()
    p.shapes[1].motion = Motion(kind="move")  # the pier is moved while the gate floats
    assert any("float" in text and "set motion" in text for text in errors(p))


def test_motion_examples_are_ready_to_run():
    from easyfoam.casegen.mesh import predicted_patches
    from easyfoam.examples import EXAMPLES

    for key, kind in (("gate", "move"), ("floating", "floating")):
        p = EXAMPLES[key](key)
        assert [s.motion.kind for s in p.shapes if s.motion.kind != "none"] == [kind]
        assert [i.text for i in project_issues(p, predicted_patches(p), True) if i.level == "error"] == []
