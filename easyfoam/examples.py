"""Ready-made starting projects."""

from __future__ import annotations

from collections.abc import Callable

from easyfoam.model import BaseFace, Boundary, Project, Shape


def empty(name: str) -> Project:
    return Project(name=name)


def sphere(name: str) -> Project:
    """Air flowing past a sphere in a wind tunnel (steady, k-omega SST)."""
    p = Project(name=name)
    p.shapes.append(Shape("ball", kind="sphere", centre=[0, 0, 0], radius=0.5, level_min=2, level_max=3))
    p.shapes.append(
        Shape("wake", kind="box", role="refinement", min=[-1, -1, -1], max=[4, 1, 1], region_level=1)
    )
    base = p.mesh.base
    base.min, base.max, base.cells = [-3, -2.5, -2.5], [7, 2.5, 2.5], [40, 20, 20]
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[10.0, 0.0, 0.0])
    p.boundaries["outlet"] = Boundary(kind="pressureOutlet")
    p.physics.initial_velocity = [10.0, 0.0, 0.0]
    p.run.end_time, p.run.write_interval, p.run.processors = 200, 50, 4
    p.forces.enabled = True
    p.forces.ref_area, p.forces.ref_length = 0.7854, 1.0  # frontal area pi r^2, diameter
    return p


def cavity(name: str) -> Project:
    """Lid-driven cavity: a closed box whose top wall slides (laminar, no geometry)."""
    p = Project(name=name)
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [1, 1, 0.1], [40, 40, 1]
    for face in ("xMin", "xMax", "yMin"):
        base.faces[face] = BaseFace("walls", "wall")
    base.faces["yMax"] = BaseFace("lid", "wall")
    base.faces["zMin"] = base.faces["zMax"] = BaseFace("frontAndBack", "empty")
    p.mesh.snappy = False
    p.physics.turbulence = "laminar"
    p.physics.nu = 0.01
    p.boundaries["lid"] = Boundary(kind="movingWall", velocity=[1.0, 0.0, 0.0])
    p.run.end_time, p.run.write_interval = 300, 100
    return p


def pipe(name: str) -> Project:
    """Slow (laminar) flow through a straight pipe; develops the parabolic profile.

    The pipe is a cylinder that sticks out of the base mesh at both ends, so the
    two end faces of the base mesh become the inlet and the outlet.
    Re = U D / nu = 1 x 0.2 / 0.004 = 50.
    """
    p = Project(name=name)
    p.shapes.append(
        Shape("tube", kind="cylinder", point1=[-0.5, 0, 0], point2=[2.5, 0, 0], radius=0.1,
              level_min=1, level_max=1)  # fmt: skip
    )
    base = p.mesh.base
    base.min, base.max, base.cells = [0, -0.125, -0.125], [2, 0.125, 0.125], [80, 10, 10]
    p.mesh.fluid_inside = "tube"
    p.physics.turbulence = "laminar"
    p.physics.material, p.physics.nu, p.physics.rho = "custom", 0.004, 1000.0
    p.physics.initial_velocity = [1.0, 0.0, 0.0]
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[1.0, 0.0, 0.0])
    p.boundaries["outlet"] = Boundary(kind="pressureOutlet")
    p.run.end_time, p.run.write_interval, p.run.processors = 500, 500, 4
    p.run.residual_target = 1e-5
    return p


def _water(p: Project) -> None:
    p.physics.solver = "interFoam"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1.0e-06, 998.0


def dambreak(name: str) -> Project:
    """A column of water collapses in a closed tank (the classic dam-break test, in a thin slice)."""
    p = Project(name=name)
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [0.584, 0.0146, 0.584], [46, 1, 46]
    for face in ("xMin", "xMax", "zMin"):
        base.faces[face] = BaseFace("walls", "wall")
    base.faces["zMax"] = BaseFace("atmosphere", "patch")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("frontAndBack", "empty")
    p.mesh.snappy = False
    _water(p)
    p.physics.turbulence = "laminar"
    p.physics.water_regions = [[0, 0, 0, 0.1461, 0.0146, 0.292]]
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    run = p.run
    run.end_time, run.delta_t, run.write_interval, run.max_courant, run.processors = 1.0, 0.001, 0.05, 0.8, 1
    return p


def weir(name: str) -> Project:
    """Water flowing over a weir in a channel: 0.05 m3/s over a 0.5 m wide, 0.51 m high weir."""
    p = Project(name=name)
    p.shapes.append(
        Shape("weir", kind="box", min=[2.52, -1, -1], max=[2.77, 2, 0.51], level_min=1, level_max=1)
    )
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [6, 0.5, 1.5], [96, 8, 24]
    base.faces["xMin"] = BaseFace("inlet", "patch")
    base.faces["xMax"] = BaseFace("outlet", "patch")
    base.faces["zMin"] = BaseFace("bed", "wall")
    base.faces["zMax"] = BaseFace("atmosphere", "patch")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("sides", "patch")
    _water(p)
    p.physics.turbulence = "kOmegaSST"
    p.physics.water_regions = [[0, 0, 0, 2.52, 0.5, 0.5]]  # the reservoir, filled to just below the crest
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.05)
    p.boundaries["outlet"] = Boundary(kind="freeOutflow")
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    run = p.run
    run.end_time, run.delta_t, run.write_interval, run.max_courant, run.processors = 20.0, 0.001, 0.5, 0.7, 4
    return p


EXAMPLES: dict[str, Callable[[str], Project]] = {
    "empty": empty,
    "sphere": sphere,
    "cavity": cavity,
    "pipe": pipe,
    "dambreak": dambreak,
    "weir": weir,
}
