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
class Structure:
    """A hydraulic structure made from its design values, in a straight channel along +x (see easyfoam.structures)."""

    kind: str = "ogee"  # ogee | stepped | labyrinth | basin | culvert | fishway
    station: float = 0.0  # where it starts along the channel (x) [m]
    bed: float = 0.0  # level of the bed it stands on [m]
    y0: float = 0.0  # one side wall of the channel [m]
    width: float = 0.5  # width of the channel, across (y) [m]
    values: dict[str, float] = field(default_factory=dict)  # design values; any left out take their defaults


@dataclass
class Shape:
    """A piece of geometry: an STL surface or a primitive."""

    name: str
    #: stl | box | sphere | cylinder | cone | wedge | profile (a sketched outline, extruded) | structure
    kind: str = "stl"
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
    structure: Structure | None = None  # structure: what it is and its design values


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
    tracer_values: dict[str, float] = field(default_factory=dict)  # per tracer, overrides tracer_value
    #: a flow-rate inlet whose discharge changes in time (a hydrograph): [[time s, m3/s], ...]; empty = constant
    flow_series: list[list[float]] = field(default_factory=list)
    #: a tailwater that changes in time (a tide, a rising river): [[time s, level m], ...]; empty = constant
    level_series: list[list[float]] = field(default_factory=list)
    roughness: str = "smooth"  # walls: smooth | ks (sand-grain roughness height) | manning
    ks: float = 0.0  # m, equivalent sand-grain roughness height
    manning: float = 0.0  # Manning's n, s/m^(1/3)


#: what each condition of a boundary is called in the window and in reports
KIND_LABELS = {
    "velocityInlet": "Velocity inlet",
    "pressureOutlet": "Pressure outlet",
    "slip": "Slip (frictionless)",
    "wall": "Wall (no slip)",
    "movingWall": "Moving wall",
    "flowRateInlet": "Inlet by flow rate",
    "freeOutflow": "Free outflow",
    "atmosphere": "Open to the atmosphere",
    "waterLevelOutlet": "Outlet at a water level",
    "waveInlet": "Wave maker",
    "waveOutlet": "Wave-absorbing outlet",
}


#: Strickler: Manning's n = ks^(1/6) / (8.25 sqrt(g)); used to turn n into a roughness height
STRICKLER = 8.25 * 9.81**0.5


def ks_from_manning(n: float) -> float:
    """Equivalent sand-grain roughness height (m) of a Manning's n (Strickler)."""
    return (STRICKLER * n) ** 6 if n > 0 else 0.0


def manning_from_ks(ks: float) -> float:
    return ks ** (1.0 / 6.0) / STRICKLER if ks > 0 else 0.0


def roughness_height(bc: Boundary) -> float:
    """The sand-grain roughness height (m) a wall boundary asks for; 0 for a smooth wall."""
    if bc.kind not in ("wall", "movingWall"):
        return 0.0
    if bc.roughness == "ks":
        return max(0.0, float(bc.ks))
    if bc.roughness == "manning":
        return ks_from_manning(float(bc.manning))
    return 0.0


def series_entry(series: list[list[float]]) -> str:
    """A time series as an OpenFOAM table, linear between the points and constant beyond them."""
    return "table (" + " ".join(f"({float(t):g} {float(v):g})" for t, v in series) + ")"


def series_value(series: list[list[float]], time: float) -> float:
    times = [float(t) for t, _ in series]
    values = [float(v) for _, v in series]
    if time <= times[0]:
        return values[0]
    for (t0, v0), (t1, v1) in zip(zip(times, values), zip(times[1:], values[1:])):
        if time <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (time - t0) / (t1 - t0)
    return values[-1]


@dataclass
class RatingCurve:
    """A run that steps through several discharges to measure the head over a structure at each."""

    discharges: list[float] = field(default_factory=list)  # m3/s, in the order they are run
    hold: float = 10.0  # s each discharge is held, long enough for the level to settle
    ramp: float = 1.0  # s to change from one discharge to the next
    gauge: int = 0  # which probe point measures the upstream water level
    crest: float | None = None  # m, crest level of the structure; None = the top of the highest wall shape
    inlet: str = "inlet"  # the flow-rate inlet that the discharges are given to


def staircase(discharges: list[float], hold: float, ramp: float = 1.0) -> list[list[float]]:
    """The inflow of a rating-curve run: each discharge held for ``hold`` seconds, short ramps between."""
    series = [[0.0, float(discharges[0])]]
    for k in range(1, len(discharges)):
        start = k * hold
        series += [[start, float(discharges[k - 1])], [start + ramp, float(discharges[k])]]
    return series


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
    diffusivity: float = 1e-09  # m2/s, molecular; turbulent mixing is added when a turbulence model is on
    decay: float = 0.0  # 1/s, first-order decay (chlorine, bacteria die-off): dC/dt = -decay * C
    kind: str = "concentration"  # concentration | age (the time since the water entered, in seconds)


#: turbulent Schmidt number: how much less a tracer mixes than momentum in turbulent flow
SCHMIDT_TURBULENT = 0.7

#: cross-sections the channel builder makes
CHANNEL_SECTIONS = ("rectangular", "trapezoidal", "compound", "circular")


@dataclass
class ChannelSegment:
    """A piece of a channel's centreline seen from above: straight, or a bend."""

    kind: str = "straight"  # straight | bend
    length: float = 20.0  # m, straight pieces
    radius: float = 20.0  # m, bends: radius of the centreline
    angle: float = 90.0  # degrees, bends: positive turns left (anticlockwise seen from above), negative right

    def run(self) -> float:
        """Its length along the centreline, m."""
        if self.kind == "bend":
            return abs(self.radius * self.angle) * 3.141592653589793 / 180.0
        return self.length


@dataclass
class Channel:
    """An open channel built in the program: a cross-section swept along a centreline, falling at the bed slope."""

    section: str = "trapezoidal"  # one of CHANNEL_SECTIONS
    bottom_width: float = 2.0  # m, bed of the main channel
    depth: float = 1.0  # m, height of the main channel banks
    side_slope: float = 1.5  # banks, horizontal per vertical (0 = vertical walls)
    berm_width: float = 4.0  # m, compound: width of each floodplain
    berm_depth: float = 0.6  # m, compound: height of the outer banks above the floodplains
    berm_slope: float = 2.0  # compound: outer banks, horizontal per vertical
    diameter: float = 1.2  # m, circular culvert
    slope: float = 0.001  # bed slope, falling downstream, m per m
    segments: list[ChannelSegment] = field(default_factory=lambda: [ChannelSegment()])
    freeboard: float = 0.3  # m of air above the banks (the atmosphere is above that)
    cell_size: float = 0.1  # m
    water_depth: float = 0.5  # m of water above the bed at the start (0 = dry)


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
    rating: RatingCurve = field(default_factory=RatingCurve)
    channel: Channel | None = None  # an open channel built in the program; it replaces the base mesh
    #: the line the long section follows, drawn in the 3D view, as [[x, y], ...]; empty = the channel or the x axis
    section_line: list[list[float]] = field(default_factory=list)

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
