"""Ready-made starting projects."""

from __future__ import annotations

from collections.abc import Callable

from easyfoam.model import BaseFace, Boundary, Motion, Project, Shape, Tracer


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
    p.probes = [[1.2, 0.25, 0.3]]  # water-level gauge in the reservoir
    p.flow_monitors = ["outlet"]
    run = p.run
    run.end_time, run.delta_t, run.write_interval, run.max_courant, run.processors = 20.0, 0.001, 0.5, 0.7, 4
    return p


def waves(name: str) -> Project:
    """Regular waves travelling down a flume: wave maker at one end, absorbing boundary at the other.

    A thin slice (one cell wide). Still-water depth 0.4 m, wave height 0.04 m, period 1.5 s.
    Two gauges record the water level.
    """
    p = Project(name=name)
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [8, 0.05, 0.8], [320, 1, 32]
    base.faces["xMin"] = BaseFace("inlet", "patch")
    base.faces["xMax"] = BaseFace("outlet", "patch")
    base.faces["zMin"] = BaseFace("bed", "wall")
    base.faces["zMax"] = BaseFace("atmosphere", "patch")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("frontAndBack", "empty")
    p.mesh.snappy = False
    _water(p)
    p.physics.turbulence = "laminar"
    p.physics.water_regions = [[0, 0, 0, 8, 0.05, 0.4]]
    p.boundaries["inlet"] = Boundary(kind="waveInlet", wave_height=0.04, wave_period=1.5)
    p.boundaries["outlet"] = Boundary(kind="waveOutlet")
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    p.probes = [[2.0, 0.025, 0.2], [6.0, 0.025, 0.2]]
    run = p.run
    run.end_time, run.delta_t, run.write_interval, run.max_courant, run.processors = 12.0, 0.001, 0.25, 0.5, 1
    return p


def gate(name: str) -> Project:
    """A sluice gate lifts by 0.1 m and lets the water held behind it run out underneath (a thin slice)."""
    p = Project(name=name)
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [3, 0.1, 1], [60, 2, 20]
    base.faces["xMin"] = base.faces["xMax"] = BaseFace("ends", "wall")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("sides", "patch")
    base.faces["zMin"] = BaseFace("bed", "wall")
    base.faces["zMax"] = BaseFace("atmosphere", "patch")
    _water(p)
    p.physics.turbulence = "laminar"
    p.physics.water_regions = [[0, 0, 0, 1.5, 0.1, 0.5]]
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    lift = Motion(kind="move", displacement=[0.0, 0.0, 0.1], start=0.1, duration=0.5)
    p.shapes.append(
        Shape("gate", kind="box", min=[1.5, -1, 0.1], max=[1.6, 2, 0.8], level_min=0, level_max=0, motion=lift)
    )
    run = p.run
    run.end_time, run.delta_t, run.write_interval, run.max_courant, run.processors = 2.0, 0.001, 0.1, 0.5, 2
    return p


def jump(name: str) -> Project:
    """Water shoots under a sluice gate and forms a hydraulic jump against the tailwater (a thin slice).

    0.206 m³/s per metre width passes a 0.1 m gate opening; the tailwater outlet holds 0.32 m.
    """
    p = Project(name=name)
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [6, 0.05, 0.8], [300, 1, 40]
    base.faces["xMin"] = BaseFace("inlet", "patch")
    base.faces["xMax"] = BaseFace("outlet", "patch")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("sides", "patch")  # frictionless: a slice of a wide channel
    base.faces["zMin"] = BaseFace("bed", "wall")
    base.faces["zMax"] = BaseFace("atmosphere", "patch")
    _water(p)
    p.physics.turbulence = "kOmegaSST"
    p.physics.water_regions = [[0, 0, 0, 1.0, 0.05, 0.6], [1.1, 0, 0, 6, 0.05, 0.3]]
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.0103)
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=0.32)
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    p.shapes.append(Shape("gate", kind="box", min=[1.0, -1, 0.1], max=[1.1, 2, 1.0], level_min=0, level_max=0))
    p.probes = [[0.5, 0.025, 0.3], [5.0, 0.025, 0.2]]
    p.flow_monitors = ["outlet"]
    run = p.run
    run.end_time, run.delta_t, run.write_interval, run.max_courant, run.processors = 15.0, 0.001, 1.0, 0.5, 4
    return p


def tank(name: str) -> Project:
    """A chlorine contact tank seen from above: nine cross baffles make the water wind from inlet to outlet.

    30 x 10 m in plan and 3 m deep (768 m³ of water), 0.1 m³/s entering through a 2 m wide opening in one
    corner, so V/Q is 2.1 hours. The baffles stand 3 m apart and leave a 2 m gap at alternate ends. A plan
    view (one cell over the depth), steady. It carries the age of the water and a chlorine residual dosed at
    2 mg/L that decays at 0.3 per hour. A tracer test gives a baffling factor of about 0.5 (average);
    without the baffles it is about 0.25.
    """
    p = Project(name=name)
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [30, 10, 3], [120, 40, 1]
    base.faces["xMin"] = BaseFace("inlet", "patch")
    base.faces["xMax"] = BaseFace("outlet", "patch")
    base.faces["yMin"] = base.faces["yMax"] = BaseFace("walls", "wall")
    base.faces["zMin"] = base.faces["zMax"] = BaseFace("floorAndSurface", "empty")  # a plan view
    blocks = [
        ("inletWall", [-1, 2, -1], [0.5, 11, 4]),  # leaves the inlet open over y 0-2
        ("outletWall", [29.5, 2, -1], [31, 11, 4]),  # leaves the outlet open over y 0-2
    ]
    for i in range(1, 10):  # the water passes the odd baffles at the far side (y 8-10), the even ones at y 0-2
        x = 3.0 * i
        blocks.append((f"baffle{i}", [x, -1, -1], [x + 0.5, 8, 4]) if i % 2 else (f"baffle{i}", [x, 2, -1], [x + 0.5, 11, 4]))
    for shape_name, lo, hi in blocks:
        p.shapes.append(Shape(shape_name, kind="box", min=lo, max=hi, level_min=0, level_max=0))
    p.physics.solver, p.physics.turbulence = "simpleFoam", "kOmegaSST"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1.0e-06, 998.0
    p.physics.initial_velocity = [0.0, 0.0, 0.0]
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[0.1 / 6.0, 0.0, 0.0], tracer_value=2.0)
    p.boundaries["outlet"] = Boundary(kind="pressureOutlet")
    p.tracers = [Tracer("age", 1e-09, kind="age"), Tracer("chlorine", 1e-09, decay=0.3 / 3600)]
    p.flow_monitors = ["outlet"]
    run = p.run
    run.end_time, run.write_interval, run.processors, run.residual_target = 2000, 500, 1, 1e-6
    return p


def floating(name: str) -> Project:
    """A flat box half as dense as water is released 3 cm too high and bobs until it floats at rest.

    The box is 0.3 x 0.3 x 0.12 m, so it floats 6 cm deep with its centre at the water surface.
    """
    p = Project(name=name)
    base = p.mesh.base
    # 4 cm cells, so that the still-water level (0.4 m) lies exactly between two layers of cells
    base.min, base.max, base.cells = [0, 0, 0], [1.0, 0.8, 0.8], [25, 20, 20]
    for face in ("xMin", "xMax", "yMin", "yMax"):
        base.faces[face] = BaseFace("walls", "wall")
    base.faces["zMin"] = BaseFace("bed", "wall")
    base.faces["zMax"] = BaseFace("atmosphere", "patch")
    _water(p)
    p.physics.turbulence = "laminar"
    p.physics.water_regions = [[0, 0, 0, 1.0, 0.8, 0.4]]
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    bob = Motion(kind="floating", density=500.0, freedom="heave")
    p.shapes.append(
        Shape("box", kind="box", min=[0.35, 0.25, 0.37], max=[0.65, 0.55, 0.49], level_min=1, level_max=1, motion=bob)
    )
    run = p.run
    run.end_time, run.delta_t, run.write_interval, run.max_courant, run.processors = 4.0, 0.001, 0.1, 0.5, 4
    return p


EXAMPLES: dict[str, Callable[[str], Project]] = {
    "empty": empty,
    "sphere": sphere,
    "cavity": cavity,
    "pipe": pipe,
    "dambreak": dambreak,
    "weir": weir,
    "waves": waves,
    "gate": gate,
    "floating": floating,
    "jump": jump,
    "tank": tank,
}
