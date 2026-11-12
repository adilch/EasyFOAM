"""The EasyFOAM project: everything the user chose, stored as ``easyfoam.json``.

The project file lives in the case folder and is the source of truth; the
OpenFOAM dictionaries are regenerated from it (see :mod:`easyfoam.casegen`).
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_FILE = "easyfoam.json"
FORMAT_VERSION = 1

FACES = ("xMin", "xMax", "yMin", "yMax", "zMin", "zMax")
#: patch types whose boundary condition is dictated by the mesh
CONSTRAINT_TYPES = ("symmetry", "symmetryPlane", "empty", "wedge", "cyclic", "cyclicAMI", "processor")
#: boundary kinds the user may pick, per patch type
KINDS_FOR_TYPE = {
    "patch": (
        "velocityInlet", "flowRateInlet", "pressureOutlet", "freeOutflow", "atmosphere", "slip",
        "waterLevelOutlet", "waveInlet", "waveOutlet",
    ),  # fmt: skip
    "wall": ("wall", "movingWall", "slip"),
}


def _vec(x: float, y: float, z: float):
    return field(default_factory=lambda: [x, y, z])


@dataclass
class Motion:
    """How a shape moves during the run."""

    kind: str = "none"  # none | move (to a new position) | oscillate | floating (moved by the flow)
    displacement: list[float] = _vec(0, 0, 0.1)  # move: where it ends up, relative to the start [m]
    start: float = 0.0  # move: when it starts [s]
    duration: float = 1.0  # move: how long it takes [s]
    amplitude: list[float] = _vec(0, 0, 0.05)  # oscillate [m]
    period: float = 2.0  # oscillate [s]
    density: float = 500.0  # floating: density of the body [kg/m3]
    freedom: str = "heave"  # floating: heave (up and down) | plane (x, z and pitch) | free (all six)


@dataclass
class Shape:
    """A piece of geometry: an STL surface or a primitive."""

    name: str
    kind: str = "stl"  # stl | box | sphere | cylinder | cone | wedge | profile (a sketched outline, extruded)
    file: str = ""  # STL file name inside constant/triSurface
    role: str = "wall"  # wall = meshed surface; refinement = region to refine only
    min: list[float] = _vec(0, 0, 0)  # box
    max: list[float] = _vec(1, 1, 1)
    centre: list[float] = _vec(0, 0, 0)  # sphere
    radius: float = 0.5  # sphere, cylinder
    point1: list[float] = _vec(0, 0, 0)  # cylinder axis
    point2: list[float] = _vec(1, 0, 0)
    radius2: float = 0.25  # cone: radius at the second end (0 = a point)
    rise: str = "+x"  # wedge: the direction in which its top rises (+x, -x, +y, -y)
    #: profile: the corners of its outline, in the plane it is drawn in
    points: list[list[float]] = field(default_factory=lambda: [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
    plane: str = "xz"  # profile: the plane it is drawn in (xz, xy or yz); it is extruded across that plane
    extent: list[float] = field(default_factory=lambda: [0.0, 1.0])  # profile: where the extrusion starts and ends
    level_min: int = 1  # surface refinement (role wall)
    level_max: int = 2
    layers: int = 0  # boundary-layer cells on this surface
    region_level: int = 1  # refinement inside the shape (role refinement)
    near_distance: float = 0.0  # refine cells closer than this to the surface [m] ...
    near_level: int = 0  # ... to this level (0 = off)
    #: STL regions (solids) -> patch type; empty for single-solid surfaces
    regions: dict[str, str] = field(default_factory=dict)
    motion: Motion = field(default_factory=Motion)


@dataclass
class BaseFace:
    name: str
    type: str = "patch"  # patch | wall | symmetry | empty


def _default_faces() -> dict[str, BaseFace]:
    names = {"xMin": "inlet", "xMax": "outlet"}
    return {f: BaseFace(names.get(f, "sides")) for f in FACES}


@dataclass
class BaseMesh:
    """The background box of hexahedra that snappyHexMesh starts from."""

    min: list[float] = _vec(-5, -5, -5)
    max: list[float] = _vec(15, 5, 5)
    cells: list[int] = field(default_factory=lambda: [20, 20, 20])
    faces: dict[str, BaseFace] = field(default_factory=_default_faces)


@dataclass
class MeshSettings:
    base: BaseMesh = field(default_factory=BaseMesh)
    snappy: bool = True  # False: use the base mesh as it is
    snap: bool = True
    add_layers: bool = True  # only has an effect for shapes with layers > 0
    location_in_mesh: list[float] | None = None  # None: chosen automatically
    fluid_inside: str = ""  # name of the shape that contains the fluid ("" = flow around shapes)
    cells_between_levels: int = 3
    feature_angle: float = 30.0
    layer_expansion: float = 1.2
    final_layer_thickness: float = 0.3


@dataclass
class Physics:
    solver: str = "simpleFoam"  # see easyfoam.solvers.SOLVERS
    turbulence: str = "kOmegaSST"  # laminar | kEpsilon | kOmegaSST
    material: str = "air"
    nu: float = 1.5e-05  # kinematic viscosity, m2/s
    rho: float = 1.2  # density, kg/m3 (forces only)
    initial_velocity: list[float] = _vec(0, 0, 0)
    turbulence_intensity: float = 0.05
    turbulence_length: float = 0.1  # m
    numerics: str = "robust"  # robust | accurate
    potential_init: bool = False  # start from a potential-flow solution
    # free-surface flow: the main fluid above is the water, the second fluid is the air
    gravity: list[float] = _vec(0, 0, -9.81)  # m/s2
    air_nu: float = 1.48e-05
    air_rho: float = 1.2
    surface_tension: float = 0.07  # N/m
    #: boxes filled with water at the start, each [x0, y0, z0, x1, y1, z1]
    water_regions: list[list[float]] = field(default_factory=list)
    wall_treatment: str = "wallFunctions"  # wallFunctions | lowRe (resolve the boundary layer)
    viscosity_model: str = "Newtonian"  # see easyfoam.solvers.VISCOSITY_MODELS
    viscosity_coeffs: dict[str, float] = field(default_factory=dict)
    max_velocity: float = 0.0  # m/s, cap on the velocity anywhere (0 = no cap)
    adaptive_levels: int = 0  # free surface: refine the mesh at the water surface by this many levels
    ambient_pressure: float = 101325.0  # Pa, absolute pressure of the surrounding air
    vapour_pressure: float = 2339.0  # Pa, of the water (20 degC)


@dataclass
class Boundary:
    kind: str = "wall"  # velocityInlet | pressureOutlet | wall | movingWall | slip | constraint
    velocity: list[float] = _vec(0, 0, 0)
    pressure: float = 0.0  # kinematic gauge pressure p/rho, m2/s2 (pascals in free-surface flow)
    flow_rate: float = 0.0  # m3/s, for a flow-rate inlet
    water_fraction: float = 1.0  # free-surface flow: share of water in a velocity inlet (0 = air)
    level: float = 0.0  # m, tailwater height for a water-level outlet (measured against gravity)
    wave_height: float = 0.05  # m, crest to trough
    wave_period: float = 2.0  # s
    wave_model: str = "StokesII"  # StokesI | StokesII
    contact_angle: float = 90.0  # degrees, of the water surface on a wall (90 = neutral)
    tracer_value: float = 0.0  # concentration of the tracer(s) entering through an inlet


@dataclass
class RunSettings:
    end_time: float = 500.0  # iterations when steady, seconds when transient
    delta_t: float = 1.0
    write_interval: float = 100.0
    processors: int = 1
    adjust_time_step: bool = True  # transient only
    max_courant: float = 1.0
    purge_write: int = 0  # keep only the last N saved times (0 = all)
    residual_target: float = 1e-4  # steady runs stop when all residuals are below (0 = never)


@dataclass
class ForceMonitor:
    """Force and moment coefficients on walls, written every iteration."""

    enabled: bool = False
    patches: list[str] = field(default_factory=list)  # empty: every wall that comes from a shape
    drag_dir: list[float] = _vec(1, 0, 0)
    lift_dir: list[float] = _vec(0, 0, 1)
    centre: list[float] = _vec(0, 0, 0)  # moment reference point
    ref_velocity: float = 0.0  # 0: use the inlet / initial speed
    ref_area: float = 1.0  # m2
    ref_length: float = 1.0  # m


@dataclass
class Tracer:
    """A passive quantity carried by the flow (dye, pollutant, age)."""

    name: str = "tracer"
    diffusivity: float = 1e-09  # m2/s


@dataclass
class Project:
    name: str = "case"
    format_version: int = FORMAT_VERSION
    runtime: dict | None = None  # see easyfoam.runtime.Runtime.to_json
    shapes: list[Shape] = field(default_factory=list)
    mesh: MeshSettings = field(default_factory=MeshSettings)
    physics: Physics = field(default_factory=Physics)
    boundaries: dict[str, Boundary] = field(default_factory=dict)
    run: RunSettings = field(default_factory=RunSettings)
    forces: ForceMonitor = field(default_factory=ForceMonitor)
    probes: list[list[float]] = field(default_factory=list)  # points where p and U are recorded
    flow_monitors: list[str] = field(default_factory=list)  # boundaries whose discharge is recorded
    tracers: list[Tracer] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def save(self, case_dir: Path) -> Path:
        case_dir = Path(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)
        path = case_dir / PROJECT_FILE
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> Project:
        return _build(cls, data)

    @classmethod
    def load(cls, case_dir: Path) -> Project:
        text = (Path(case_dir) / PROJECT_FILE).read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))

    def boundary_for(self, patch: str, patch_type: str) -> Boundary:
        """The boundary condition to apply to a mesh patch."""
        chosen = self.boundaries.get(patch)
        if chosen is not None and chosen.kind in KINDS_FOR_TYPE.get(patch_type, ()):
            return chosen
        return default_boundary(patch, patch_type)


def default_boundary(patch: str, patch_type: str) -> Boundary:
    if patch_type in CONSTRAINT_TYPES:
        return Boundary(kind="constraint")
    if patch_type == "wall":
        return Boundary(kind="wall")
    lowered = patch.lower()
    if "atmos" in lowered:
        return Boundary(kind="atmosphere")
    if "inlet" in lowered or "inflow" in lowered:
        return Boundary(kind="velocityInlet")
    if "outlet" in lowered or "outflow" in lowered:
        return Boundary(kind="pressureOutlet")
    return Boundary(kind="slip")


def _build(tp, value):
    """Rebuild typed dataclasses from JSON data, ignoring unknown keys."""
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        if value is None:
            return None
        inner = [a for a in typing.get_args(tp) if a is not type(None)]
        return _build(inner[0], value)
    if dataclasses.is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        known = {f.name for f in dataclasses.fields(tp)}
        return tp(**{k: _build(hints[k], v) for k, v in value.items() if k in known})
    if origin is list:
        (item,) = typing.get_args(tp)
        return [_build(item, v) for v in value]
    if origin is dict:
        _, item = typing.get_args(tp)
        return {k: _build(item, v) for k, v in value.items()}
    return value
