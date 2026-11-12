"""Moving shapes: gates that follow a prescribed motion, and bodies that float.

Both deform the mesh around the moving shape while the run goes on (the
number of cells stays the same). A prescribed motion gives the shape's
displacement over time; a floating body is moved by the forces of the flow
and its own weight (rigid-body motion with a chosen freedom).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from easyfoam import geometry
from easyfoam.foam.boundaryfile import Patch
from easyfoam.model import CONSTRAINT_TYPES, Project, Shape

ZERO = "uniform (0 0 0)"
#: freedom of a floating body -> joint of the rigid-body solver
JOINTS = {
    "heave": {"type": "composite", "joints": [{"type": "Pz"}]},
    "plane": {"type": "composite", "joints": [{"type": "Px"}, {"type": "Pz"}, {"type": "Ry"}]},
    "free": {"type": "floating"},
}


def moving_shapes(project: Project) -> list[Shape]:
    return [s for s in project.shapes if s.role == "wall" and s.motion.kind != "none"]


def floating_shapes(project: Project) -> list[Shape]:
    return [s for s in moving_shapes(project) if s.motion.kind == "floating"]


def shape_patches(shape: Shape, patches: Sequence[Patch]) -> list[str]:
    """Names of the mesh boundaries that belong to a shape."""
    found = [p.name for p in patches if p.name == shape.name or p.name.startswith(shape.name + "_")]
    return found or [shape.name]


def _vector(values: Sequence[float]) -> str:
    return "(" + " ".join(f"{c:g}" for c in values) + ")"


def _clipped_size(shape: Shape, project: Project, case_dir: Path | None) -> float:
    """A typical size of the part of the shape that lies inside the base mesh."""
    lo, hi = geometry.shape_bounds(shape, case_dir or Path("."))
    base = project.mesh.base
    extents = [max(min(h, bh) - max(low, bl), 0.0) for low, h, bl, bh in zip(lo, hi, base.min, base.max)]
    extents = [e for e in extents if e > 0] or [1.0]
    return math.prod(extents) ** (1.0 / len(extents))


def _clearance(shape: Shape, project: Project, case_dir: Path | None) -> float:
    """Distance from the shape to the nearest face of the base mesh (infinite if it reaches or crosses one)."""
    lo, hi = geometry.shape_bounds(shape, case_dir or Path("."))
    base = project.mesh.base
    gaps = [g for low, h, bl, bh in zip(lo, hi, base.min, base.max) for g in (low - bl, bh - h)]
    return min(gaps) if all(g > 0 for g in gaps) else float("inf")


def dynamic_mesh_dict(project: Project, patches: Sequence[Patch], case_dir: Path | None = None) -> dict | None:
    moving = moving_shapes(project)
    if not moving:
        return None
    floating = floating_shapes(project)
    if floating:
        bodies = {}
        for shape in floating:
            mass, centre, inertia = geometry.mass_properties(shape, case_dir or Path("."), shape.motion.density)
            size = _clipped_size(shape, project, case_dir)
            # the deforming zone must end before the nearest fixed face of the base mesh
            outer = min(1.2 * size, 0.9 * _clearance(shape, project, case_dir))
            inner = min(0.2 * size, outer / 3.0)
            bodies[shape.name] = {
                "type": "rigidBody",
                "parent": "root",
                "centreOfMass": [0, 0, 0],
                "mass": mass,
                "inertia": [inertia[0], 0, 0, inertia[1], 0, inertia[2]],
                "transform": f"(1 0 0 0 1 0 0 0 1) {_vector(centre)}",
                "joint": JOINTS.get(shape.motion.freedom, JOINTS["heave"]),
                "patches": shape_patches(shape, patches),
                # the mesh moves rigidly with the body up to the inner distance and not at all beyond the outer one
                "innerDistance": inner,
                "outerDistance": outer,
            }
        return {
            "dynamicFvMesh": "dynamicMotionSolverFvMesh",
            "motionSolverLibs": ["rigidBodyMeshMotion"],
            "motionSolver": "rigidBodyMotion",
            "rigidBodyMotionCoeffs": {
                "report": True,
                "solver": {"type": "Newmark"},
                "accelerationRelaxation": 0.7,
                "bodies": bodies,
            },
        }
    names = [name for shape in moving for name in shape_patches(shape, patches)]
    return {
        "dynamicFvMesh": "dynamicMotionSolverFvMesh",
        "motionSolverLibs": ["fvMotionSolvers"],
        "motionSolver": "displacementLaplacian",
        # the mesh is stiff near the moving shape and absorbs the motion further away
        "displacementLaplacianCoeffs": {"diffusivity": f"quadratic inverseDistance ({' '.join(names)})"},
    }


def _prescribed_entry(shape: Shape) -> dict:
    motion = shape.motion
    if motion.kind == "oscillate":
        return {
            "type": "oscillatingDisplacement",
            "amplitude": [float(c) for c in motion.amplitude],
            "omega": 2.0 * math.pi / motion.period,
            "value": ZERO,
        }
    end = motion.start + motion.duration
    points = [(0.0, [0, 0, 0])]
    if motion.start > 0:
        points.append((motion.start, [0, 0, 0]))
    points.append((end, motion.displacement))
    table = " ".join(f"({t:g} {_vector(d)})" for t, d in points)
    return {"type": "uniformFixedValue", "uniformValue": f"table ({table})"}


def displacement_at(motion, time: float) -> list[float]:
    """How far a shape with a set motion has moved from its starting position at a given time."""
    if motion.kind == "oscillate" and motion.period > 0:
        swing = math.sin(2.0 * math.pi * time / motion.period)
        return [float(a) * swing for a in motion.amplitude]
    if motion.kind == "move":
        share = (time - motion.start) / motion.duration if motion.duration > 0 else float(time >= motion.start)
        share = max(0.0, min(1.0, share))
        return [float(d) * share for d in motion.displacement]
    return [0.0, 0.0, 0.0]


def point_displacement(project: Project, patches: Sequence[Patch]) -> tuple[str, dict] | None:
    """The ``pointDisplacement`` field: how far each boundary's mesh points have moved."""
    moving = moving_shapes(project)
    if not moving:
        return None
    floating = bool(floating_shapes(project))
    owner = {name: shape for shape in moving for name in shape_patches(shape, patches)}
    base_faces = {face.name for face in project.mesh.base.faces.values()}
    entries = {}
    for patch in patches:
        if patch.name in owner:
            shape = owner[patch.name]
            entries[patch.name] = (
                {"type": "calculated", "value": ZERO} if shape.motion.kind == "floating" else _prescribed_entry(shape)
            )
        elif patch.type in CONSTRAINT_TYPES:
            entries[patch.name] = {"type": patch.type}
        elif patch.name in base_faces and not floating:
            entries[patch.name] = {"type": "slip"}  # flat outer faces: points may slide along them
        else:
            entries[patch.name] = {"type": "fixedValue", "value": ZERO}
    return "pointVectorField", {"dimensions": "[0 1 0 0 0 0 0]", "internalField": ZERO, "boundaryField": entries}


def apply_wall_velocity(project: Project, patches: Sequence[Patch], fields: dict) -> None:
    """The fluid on a moving wall moves with the wall."""
    if "U" not in fields:
        return
    velocity = fields["U"][1]["boundaryField"]
    for shape in moving_shapes(project):
        for name in shape_patches(shape, patches):
            if name in velocity:
                velocity[name] = {"type": "movingWallVelocity", "value": ZERO}


def extend_solution(project: Project, solution: dict) -> dict:
    """Solver settings a moving mesh needs (only for transient solvers)."""
    if not moving_shapes(project) or "PIMPLE" not in solution:
        return solution
    solvers = solution["solvers"]
    solvers['"cellDisplacement.*"'] = {"solver": "GAMG", "smoother": "GaussSeidel", "tolerance": 1e-08, "relTol": 0}
    solvers.setdefault('"pcorr.*"', {"solver": "PCG", "preconditioner": "DIC", "tolerance": 1e-05, "relTol": 0})
    pimple = solution["PIMPLE"]
    pimple["correctPhi"] = True
    if floating_shapes(project):
        # the body and the flow depend on each other: repeat each time step until they agree
        pimple["nOuterCorrectors"] = 3
        pimple["moveMeshOuterCorrectors"] = True
    return solution
