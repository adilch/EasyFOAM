"""Open channels built in the program: a cross-section swept along a centreline that falls at the bed slope.

blockMesh alone makes the mesh, fitted to the channel: hexahedra that follow the banks, the bends and the
slope of the bed, with no cells wasted outside it. The cross-section is cut into quadrilaterals (a block
each) and split at the initial water depth, so that the water at the start fills whole cells: a cell zone
that setFields fills.

Coordinates: x and y in plan, z up. The channel starts at the origin heading along +x, and its bed at the
outlet is at z = 0. Across the channel, n is the distance to the left of the centreline, looking downstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from easyfoam.foam.boundaryfile import Patch
from easyfoam.foam.dictfmt import Named
from easyfoam.model import CHANNEL_SECTIONS, Channel

WATER_ZONE = "water"
#: the boundaries a built channel can have, in this order, with their patch types
PATCH_TYPES = {
    "inlet": "patch", "outlet": "patch", "bed": "wall", "banks": "wall", "floodplain": "wall", "barrel": "wall",
    "atmosphere": "patch",
}  # fmt: skip
#: the faces of a hexahedron (blockMesh numbering) on each side of a block, normals pointing out
SIDE_FACES = {"right": (0, 4, 7, 3), "left": (1, 2, 6, 5), "bottom": (0, 1, 5, 4), "top": (3, 7, 6, 2)}
#: the corners of a quadrilateral at the ends of each of its sides
SIDE_CORNERS = {"bottom": (0, 1), "left": (1, 2), "top": (2, 3), "right": (3, 0)}


@dataclass
class Quad:
    """A block of the cross-section.

    Its corners index the section's points anticlockwise in the (n, z) plane, starting at the bottom on the
    right-bank side (lowest n): blockMesh then counts across towards the left bank, up, and downstream.
    """

    corners: tuple[int, int, int, int]
    across: int  # cells from the right side to the left side
    up: int  # cells from the bottom to the top
    zone: str = ""  # cell zone: WATER_ZONE below the initial water depth
    sides: dict[str, str] = field(default_factory=dict)  # right | left | bottom | top -> boundary name
    arcs: dict[str, tuple[float, float]] = field(default_factory=dict)  # side -> (n, z) of a point on its arc


@dataclass
class Section:
    points: list[tuple[float, float]]  # (n, z) of the corners of the blocks
    quads: list[Quad]
    half_width: float  # m, how far the section reaches to each side
    height: float  # m, from the bed to the top of the domain


@dataclass
class Station:
    """Where a piece of the centreline starts or ends."""

    x: float
    y: float
    heading: float  # radians from +x, anticlockwise
    chainage: float  # m along the centreline
    bed: float  # m, level of the bed at the centreline


# --- the cross-section -----------------------------------------------------------------------------------


def _cells(length: float, size: float) -> int:
    return max(1, math.ceil(length / size - 1e-9))


def _levels(bottom: float, top: float, water: float) -> list[float]:
    """The levels a part of the section is split at: its bottom and top, and the water level if inside."""
    return [bottom, water, top] if bottom < water < top else [bottom, top]


class _Points:
    def __init__(self) -> None:
        self.points: list[tuple[float, float]] = []
        self._index: dict[tuple[float, float], int] = {}

    def __call__(self, n: float, z: float) -> int:
        key = (round(n, 9), round(z, 9))
        if key not in self._index:
            self._index[key] = len(self.points)
            self.points.append((float(n), float(z)))
        return self._index[key]


def section(ch: Channel) -> Section:
    """The cross-section of the channel cut into blocks."""
    if ch.section == "circular":
        return _circular(ch)
    if ch.section == "compound":
        return _compound(ch)
    return _trapezoid(ch, 0.0 if ch.section == "rectangular" else ch.side_slope)


def _trapezoid(ch: Channel, slope: float) -> Section:
    size, half = ch.cell_size, ch.bottom_width / 2
    top = ch.depth + ch.freeboard
    levels = _levels(0.0, top, ch.water_depth)
    point = _Points()
    across = _cells(ch.bottom_width + slope * top, size)

    def edge(z: float) -> float:
        return half + slope * z

    quads = []
    for z0, z1 in zip(levels, levels[1:]):
        corners = (point(-edge(z0), z0), point(edge(z0), z0), point(edge(z1), z1), point(-edge(z1), z1))
        zone = WATER_ZONE if z1 <= ch.water_depth + 1e-9 else ""
        quads.append(Quad(corners, across, _cells(z1 - z0, size), zone, {"right": "banks", "left": "banks"}))
    quads[0].sides["bottom"] = "bed"
    quads[-1].sides["top"] = "atmosphere"
    return Section(point.points, quads, edge(top), top)


def _compound(ch: Channel) -> Section:
    """A main channel with a floodplain on each side, each with its own banks."""
    size, water = ch.cell_size, ch.water_depth
    depth, slope = ch.depth, ch.side_slope
    top = depth + ch.berm_depth + ch.freeboard
    berm = ch.bottom_width / 2 + slope * depth  # half width of the main channel at floodplain level
    point = _Points()
    main = _cells(ch.bottom_width + slope * depth, size)
    plain = _cells(ch.berm_width + ch.berm_slope * (top - depth) / 2, size)

    def bank(z: float) -> float:
        return ch.bottom_width / 2 + slope * z

    def outer(z: float) -> float:
        return berm + ch.berm_width + ch.berm_slope * (z - depth)

    quads = []
    lower = _levels(0.0, depth, water)
    for z0, z1 in zip(lower, lower[1:]):
        corners = (point(-bank(z0), z0), point(bank(z0), z0), point(bank(z1), z1), point(-bank(z1), z1))
        zone = WATER_ZONE if z1 <= water + 1e-9 else ""
        quads.append(Quad(corners, main, _cells(z1 - z0, size), zone, {"right": "banks", "left": "banks"}))
    quads[0].sides["bottom"] = "bed"
    levels = _levels(depth, top, water)
    for z0, z1 in zip(levels, levels[1:]):
        up, zone = _cells(z1 - z0, size), WATER_ZONE if z1 <= water + 1e-9 else ""
        middle = Quad((point(-berm, z0), point(berm, z0), point(berm, z1), point(-berm, z1)), main, up, zone)
        left = Quad((point(berm, z0), point(outer(z0), z0), point(outer(z1), z1), point(berm, z1)), plain, up, zone,
                    {"left": "banks"})  # fmt: skip
        right = Quad((point(-outer(z0), z0), point(-berm, z0), point(-berm, z1), point(-outer(z1), z1)), plain, up,
                     zone, {"right": "banks"})  # fmt: skip
        if z0 == depth:
            left.sides["bottom"] = right.sides["bottom"] = "floodplain"
        if z1 == top:
            for quad in (middle, left, right):
                quad.sides["top"] = "atmosphere"
        quads += [middle, left, right]
    return Section(point.points, quads, outer(top), top)


def _circular(ch: Channel) -> Section:
    """A culvert barrel: an O-grid of a square core and four blocks reaching out to the circle."""
    size, radius = ch.cell_size, ch.diameter / 2
    centre, core, corner = radius, 0.5 * radius, radius / math.sqrt(2)
    point = _Points()
    s0, s1, s2, s3 = (point(-core, centre - core), point(core, centre - core), point(core, centre + core),
                      point(-core, centre + core))  # fmt: skip
    c0, c1, c2, c3 = (point(-corner, centre - corner), point(corner, centre - corner),
                      point(corner, centre + corner), point(-corner, centre + corner))  # fmt: skip
    arc, out = _cells(math.pi * radius / 2, size), _cells(radius - core, size)
    quads = [
        Quad((s0, s1, s2, s3), arc, arc),
        Quad((c0, c1, s1, s0), arc, out, sides={"bottom": "barrel"}, arcs={"bottom": (0.0, centre - radius)}),
        Quad((s3, s2, c2, c3), arc, out, sides={"top": "barrel"}, arcs={"top": (0.0, centre + radius)}),
        Quad((s1, c1, c2, s2), out, arc, sides={"left": "barrel"}, arcs={"left": (radius, centre)}),
        Quad((c0, s0, s3, c3), out, arc, sides={"right": "barrel"}, arcs={"right": (-radius, centre)}),
    ]
    return Section(point.points, quads, radius, ch.diameter)


# --- the centreline --------------------------------------------------------------------------------------


def total_length(ch: Channel) -> float:
    return sum(segment.run() for segment in ch.segments)


def stations(ch: Channel) -> list[Station]:
    """The ends of the pieces of the centreline."""
    total = total_length(ch)
    out = [Station(0.0, 0.0, 0.0, 0.0, ch.slope * total)]
    for segment in ch.segments:
        start = out[-1]
        if segment.kind == "bend":
            turn = math.radians(segment.angle)
            cx, cy = _bend_centre(start, segment.radius, turn)
            x, y = _turned(start.x, start.y, cx, cy, turn)
            heading = start.heading + turn
        else:
            x = start.x + segment.length * math.cos(start.heading)
            y = start.y + segment.length * math.sin(start.heading)
            heading = start.heading
        chainage = start.chainage + segment.run()
        out.append(Station(x, y, heading, chainage, ch.slope * (total - chainage)))
    return out


def _bend_centre(start: Station, radius: float, turn: float) -> tuple[float, float]:
    side = 1.0 if turn > 0 else -1.0  # left turns curve round a centre on the left
    return start.x - side * radius * math.sin(start.heading), start.y + side * radius * math.cos(start.heading)


def _turned(x: float, y: float, cx: float, cy: float, angle: float) -> tuple[float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return cx + c * (x - cx) - s * (y - cy), cy + s * (x - cx) + c * (y - cy)


def place(station: Station, n: float, z: float) -> list[float]:
    """The point at ``n`` to the left of the centreline and ``z`` above the bed, at a station."""
    s, c = math.sin(station.heading), math.cos(station.heading)
    return [station.x - n * s, station.y + n * c, station.bed + z]


def centreline_points(ch: Channel, step: float | None = None) -> np.ndarray:
    """The centreline in plan as a polyline, (n, 2); bends are cut into pieces no longer than ``step``."""
    step = step or max(ch.cell_size, 1e-3)
    ends = stations(ch)
    points = [[0.0, 0.0]]
    for segment, start in zip(ch.segments, ends):
        if segment.kind == "bend":
            turn = math.radians(segment.angle)
            cx, cy = _bend_centre(start, segment.radius, turn)
            count = max(4, math.ceil(segment.run() / step))
            points += [list(_turned(start.x, start.y, cx, cy, turn * k / count)) for k in range(1, count + 1)]
        else:
            points.append([start.x + segment.length * math.cos(start.heading),
                           start.y + segment.length * math.sin(start.heading)])  # fmt: skip
    return np.asarray(points, float)


# --- checks ----------------------------------------------------------------------------------------------


def problems(ch: Channel) -> list[str]:
    """What stops the channel from being built, in plain words (empty when it can be)."""
    out: list[str] = []
    if ch.section not in CHANNEL_SECTIONS:
        return [f"unknown cross-section '{ch.section}'"]
    if ch.cell_size <= 0:
        out.append("the cell size must be above zero")
        return out
    circular = ch.section == "circular"
    if circular:
        if ch.diameter <= 0:
            out.append("the culvert diameter must be above zero")
        if any(s.kind == "bend" for s in ch.segments):
            out.append("a circular culvert is built straight: use straight pieces only")
    else:
        if ch.bottom_width <= 0 or ch.depth <= 0:
            out.append("the bottom width and the bank height must be above zero")
        if ch.side_slope < 0 or ch.freeboard < 0:
            out.append("the bank slope and the freeboard cannot be negative")
        if ch.section == "compound" and (ch.berm_width <= 0 or ch.berm_depth <= 0 or ch.berm_slope < 0):
            out.append("the floodplains need a width and a bank height above zero")
    if not ch.segments:
        out.append("the centreline needs at least one piece")
    if out:
        return out
    sec = section(ch)
    for k, segment in enumerate(ch.segments, start=1):
        if segment.kind == "bend":
            if segment.angle == 0 or abs(segment.angle) > 180:
                out.append(f"piece {k}: a bend turns by an angle between 0 and 180 degrees, left (+) or right (-)")
            if segment.radius <= sec.half_width:
                out.append(f"piece {k}: the bend radius must be more than half the channel's width "
                           f"({sec.half_width:.3g} m)")  # fmt: skip
        elif segment.length <= 0:
            out.append(f"piece {k}: a straight piece must be longer than zero")
    water, size = ch.water_depth, ch.cell_size
    if water < 0 or water >= sec.height:
        out.append(f"the initial water depth must lie between 0 and the top of the domain ({sec.height:.3g} m)")
    elif 0 < water < size / 2 or sec.height - water < size / 2 or _near_break(ch, water, size / 2):
        out.append("the initial water level is less than half a cell from the bed, the top or the floodplains")
    return out


def _near_break(ch: Channel, water: float, gap: float) -> bool:
    return ch.section == "compound" and water != ch.depth and abs(water - ch.depth) < gap


def cell_count(ch: Channel) -> int:
    sec = section(ch)
    across = sum(q.across * q.up for q in sec.quads)
    return across * sum(_cells(s.run(), ch.cell_size) for s in ch.segments)


# --- what goes into the case -----------------------------------------------------------------------------


def block_mesh_dict(ch: Channel) -> dict:
    """blockMesh's dictionary for the channel: one block per part of the section per piece of centreline."""
    found = problems(ch)
    if found:
        raise ValueError("the channel cannot be built: " + "; ".join(found))
    sec, ends = section(ch), stations(ch)
    count = len(sec.points)
    vertices = [place(station, n, z) for station in ends for n, z in sec.points]
    blocks: list = []
    edges: list = []
    faces: dict[str, list] = {name: [] for name in PATCH_TYPES}
    last = len(ch.segments) - 1
    for k, segment in enumerate(ch.segments):
        along = _cells(segment.run(), ch.cell_size)
        for quad in sec.quads:
            ids = [k * count + c for c in quad.corners] + [(k + 1) * count + c for c in quad.corners]
            blocks += ["hex", ids, *([quad.zone] if quad.zone else []), [quad.across, quad.up, along],
                       "simpleGrading", [1, 1, 1]]  # fmt: skip
            for side, name in quad.sides.items():
                faces[name].append([ids[i] for i in SIDE_FACES[side]])
            if k == 0:
                faces["inlet"].append([ids[i] for i in (0, 3, 2, 1)])
            if k == last:
                faces["outlet"].append([ids[i] for i in (4, 5, 6, 7)])
        if segment.kind == "bend":
            start, end = ends[k], ends[k + 1]
            turn = math.radians(segment.angle)
            cx, cy = _bend_centre(start, segment.radius, turn)
            for i, (n, z) in enumerate(sec.points):
                x, y, _ = place(start, n, z)
                mx, my = _turned(x, y, cx, cy, turn / 2)
                edges += ["arc", k * count + i, (k + 1) * count + i, [mx, my, (start.bed + end.bed) / 2 + z]]
    for k, station in enumerate(ends):
        for quad in sec.quads:
            for side, (n, z) in quad.arcs.items():
                a, b = (quad.corners[i] for i in SIDE_CORNERS[side])
                edges += ["arc", k * count + a, k * count + b, place(station, n, z)]
    return {
        "scale": 1,
        "vertices": vertices,
        "blocks": blocks,
        "edges": edges,
        "boundary": [Named(name, {"type": PATCH_TYPES[name], "faces": f}) for name, f in faces.items() if f],
        "mergePatchPairs": [],
    }


def patches(ch: Channel) -> list[Patch]:
    """The boundaries the channel's mesh will have."""
    sec = section(ch)
    names = {name for quad in sec.quads for name in quad.sides.values()} | {"inlet", "outlet"}
    return [Patch(name, kind, 0, 0) for name, kind in PATCH_TYPES.items() if name in names]


def water_regions(ch: Channel) -> list[Named]:
    """setFields regions that fill the channel to the initial water depth."""
    if ch.water_depth <= 0:
        return []
    water = ["volScalarFieldValue", "alpha.water", 1]
    if ch.section != "circular":
        return [Named("zoneToCell", {"zones": [WATER_ZONE], "fieldValues": water})]
    regions = []  # a straight culvert: a box tilted with the bed, for each piece
    margin = ch.cell_size + ch.diameter
    for start, end in zip(stations(ch), stations(ch)[1:]):
        dx, dy, dz = end.x - start.x, end.y - start.y, end.bed - start.bed
        length = math.hypot(dx, dy)
        tx, ty = dx / length, dy / length
        origin = [start.x + ty * margin - tx * ch.cell_size, start.y - tx * margin - ty * ch.cell_size,
                  start.bed - margin]  # fmt: skip
        stretch = (length + 2 * ch.cell_size) / length
        regions.append(Named("rotatedBoxToCell", {
            "origin": origin, "i": [dx * stretch, dy * stretch, dz * stretch],
            "j": [-ty * 2 * margin, tx * 2 * margin, 0.0], "k": [0.0, 0.0, margin + ch.water_depth],
            "fieldValues": water,
        }))  # fmt: skip
    return regions


def bounds(ch: Channel) -> tuple[list[float], list[float]]:
    """The box that holds the channel, (min, max)."""
    sec = section(ch)
    line = centreline_points(ch)
    tangent = np.gradient(line, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    reach = np.vstack([line + sec.half_width * normal, line - sec.half_width * normal])
    beds = [s.bed for s in stations(ch)]
    low = [float(reach[:, 0].min()), float(reach[:, 1].min()), min(beds)]
    high = [float(reach[:, 0].max()), float(reach[:, 1].max()), max(beds) + sec.height]
    return low, high


def inside_point(ch: Channel) -> list[float]:
    """A point in the water space of the channel near its inlet, away from cell faces (for snappyHexMesh)."""
    sec, size = section(ch), ch.cell_size
    first = stations(ch)[0]
    point = place(first, 0.137 * size, 0.5 * sec.height + 0.171 * size)
    return [point[0] + 0.311 * size, point[1], point[2]]


def outline(ch: Channel, pieces: int = 24) -> list[tuple[float, float, str]]:
    """The boundary of the cross-section, (n, z, boundary of the edge that starts there), going round once."""
    if ch.section == "circular":
        radius = ch.diameter / 2
        return [(radius * math.sin(a), radius - radius * math.cos(a), "barrel")
                for a in np.linspace(0, 2 * math.pi, pieces, endpoint=False)]  # fmt: skip
    top = section(ch).height
    if ch.section == "compound":
        berm = ch.bottom_width / 2 + ch.side_slope * ch.depth
        outer = berm + ch.berm_width + ch.berm_slope * (top - ch.depth)
        right = [(-outer, top, "banks"), (-(berm + ch.berm_width), ch.depth, "floodplain"), (-berm, ch.depth, "banks")]
        bed = [(-ch.bottom_width / 2, 0.0, "bed"), (ch.bottom_width / 2, 0.0, "banks")]
        left = [(berm, ch.depth, "floodplain"), (berm + ch.berm_width, ch.depth, "banks"), (outer, top, "atmosphere")]
        return right + bed + left
    slope = 0.0 if ch.section == "rectangular" else ch.side_slope
    half = ch.bottom_width / 2
    return [(-half - slope * top, top, "banks"), (-half, 0.0, "bed"), (half, 0.0, "banks"),
            (half + slope * top, top, "atmosphere")]  # fmt: skip


def preview(ch: Channel) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """The surface of the channel to draw, per boundary: (points (n, 3), quads (m, 4) of point indices)."""
    edge = outline(ch)
    line = centreline_points(ch)
    tangent = np.gradient(line, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    total = total_length(ch)
    chain = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))])
    bed = ch.slope * (total - chain)
    rings = np.array([[[x - n * t[1], y + n * t[0], b + z] for n, z, _ in edge]
                      for (x, y), t, b in zip(line, tangent, bed)])  # fmt: skip
    points = rings.reshape(-1, 3)
    m = len(edge)
    out: dict[str, list] = {}
    for k in range(len(line) - 1):
        for i, (_n, _z, name) in enumerate(edge):
            j = (i + 1) % m
            out.setdefault(name, []).append([k * m + i, k * m + j, (k + 1) * m + j, (k + 1) * m + i])
    caps = {"inlet": 0, "outlet": len(line) - 1}
    result = {name: (points, np.asarray(quads, int)) for name, quads in out.items()}
    for name, k in caps.items():
        result[name] = (points, np.asarray([[k * m + i for i in range(m)]], int))
    return result


def half_width_at(ch: Channel, z: float) -> float:
    """Half the width of the section at a height above the bed (the water's surface width / 2 at that depth)."""
    if ch.section == "circular":
        radius = ch.diameter / 2
        return math.sqrt(max(0.0, radius * radius - (z - radius) ** 2))
    if ch.section == "compound" and z > ch.depth:
        return ch.bottom_width / 2 + ch.side_slope * ch.depth + ch.berm_width + ch.berm_slope * (z - ch.depth)
    return ch.bottom_width / 2 + (0.0 if ch.section == "rectangular" else ch.side_slope) * z


def water_surface(ch: Channel) -> tuple[np.ndarray, np.ndarray] | None:
    """The water's surface at the start, to draw: (points (n, 3), quads (m, 4)); None when the channel is dry."""
    if ch.water_depth <= 0:
        return None
    half = half_width_at(ch, ch.water_depth)
    line = centreline_points(ch)
    tangent = np.gradient(line, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    chain = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))])
    level = ch.slope * (total_length(ch) - chain) + ch.water_depth
    right, left = line - half * normal, line + half * normal
    points = np.vstack([np.column_stack([right, level]), np.column_stack([left, level])])
    count = len(line)
    quads = np.array([[k, k + 1, count + k + 1, count + k] for k in range(count - 1)], int)
    return points, quads


def outlet_level(ch: Channel) -> float:
    """The water level at the outlet at the start: the bed there is at 0."""
    return ch.water_depth


def wetted(ch: Channel, depth: float) -> tuple[float, float]:
    """Flow area (m²) and wetted perimeter (m) of the section at a depth of water."""
    h = max(0.0, float(depth))
    if ch.section == "circular":
        d = ch.diameter
        h = min(h, d)
        angle = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * h / d)))
        return d * d / 8.0 * (angle - math.sin(angle)), d * angle / 2.0
    slope = 0.0 if ch.section == "rectangular" else ch.side_slope
    b = ch.bottom_width
    main = min(h, ch.depth) if ch.section == "compound" else h
    area = (b + slope * main) * main
    perimeter = b + 2.0 * main * math.hypot(1.0, slope)
    if ch.section == "compound" and h > ch.depth:
        over = h - ch.depth
        area += (b + 2.0 * slope * ch.depth) * over + 2.0 * (ch.berm_width * over + ch.berm_slope * over * over / 2.0)
        perimeter += 2.0 * (ch.berm_width + over * math.hypot(1.0, ch.berm_slope))
    return area, perimeter


def normal_discharge(ch: Channel, manning: float = 0.03) -> float:
    """The discharge that flows uniformly at the initial water depth (Manning's formula): a first guess."""
    area, perimeter = wetted(ch, ch.water_depth)
    if area <= 0 or perimeter <= 0:
        return 0.0
    if ch.slope <= 0:  # no slope to drive uniform flow: a gentle half a metre a second
        return 0.5 * area
    return area * (area / perimeter) ** (2.0 / 3.0) * math.sqrt(ch.slope) / manning


def _nice(value: float) -> float:
    """A round number near ``value`` (1, 2 or 5 times a power of ten)."""
    power = 10.0 ** math.floor(math.log10(value))
    return min((step * power for step in (1, 2, 5, 10)), key=lambda v: abs(v - value))


def free_surface_run(project, cell_size: float, length: float, speed: float) -> list[str]:
    """Time settings for a free-surface run over a channel or a valley, unless the run already has them.

    Settings made for a steady run (counted in iterations, a time step of 1) would wreck the water in the first
    step: the first step becomes a hundredth of the cell size, the step then follows the Courant number, and
    the run lasts about two passages of the water from inlet to outlet.
    """
    run = project.run
    if run.delta_t <= 0.05 * cell_size and run.end_time < 100:
        return []
    run.delta_t = _nice(0.01 * cell_size)
    run.adjust_time_step = True
    run.max_courant = 0.8 if run.max_courant <= 0 or run.max_courant > 0.8 else run.max_courant
    run.end_time = _nice(max(2.0 * length / max(speed, 0.1), 10 * run.delta_t))
    run.write_interval = run.end_time / 10
    return [f"the run lasts {run.end_time:g} s (about two passages of the water), saved every {run.write_interval:g} s"]


def use_channel(project, ch: Channel, manning: float = 0.03) -> list[str]:
    """Make the project model the channel: its mesh, the water in it at the start, and its boundaries.

    Boundaries already set keep their settings; new ones get an inflow (the uniform-flow discharge), a
    tailwater at the initial water level, walls and the atmosphere. Returns what was set, in plain words.
    """
    from easyfoam.model import Boundary
    from easyfoam.solvers import solver_spec

    found = problems(ch)
    if found:
        raise ValueError("the channel cannot be built: " + "; ".join(found))
    project.channel = ch
    low, high = bounds(ch)
    base = project.mesh.base
    base.min, base.max = low, high
    base.cells = [max(1, math.ceil((hi - lo) / ch.cell_size - 1e-9)) for lo, hi in zip(low, high)]
    physics = project.physics
    done = []
    if not solver_spec(physics.solver).multiphase:
        physics.solver = "interFoam"
        if physics.rho < 100:
            physics.material, physics.nu, physics.rho = "water", 1.0e-06, 998.0
        done.append("the flow type is now free surface (water and air)")
    physics.water_regions = []  # the channel fills itself to its initial water depth
    names = {p.name for p in patches(ch)}
    boundaries = project.boundaries
    inlet = boundaries.get("inlet")
    if inlet is None or inlet.kind not in ("flowRateInlet", "velocityInlet"):
        q = normal_discharge(ch, manning)
        boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=round(q, 6))
        done.append(f"the inlet lets in {q:.4g} m³/s, the uniform flow at the initial depth (Manning n = {manning:g})")
    outlet = boundaries.get("outlet")
    if outlet is None or outlet.kind not in ("waterLevelOutlet", "freeOutflow"):
        boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=outlet_level(ch))
        done.append(f"the outlet holds the tailwater at {outlet_level(ch):.4g} m (the initial depth)")
    elif outlet.kind == "waterLevelOutlet" and not outlet.level_series:
        outlet.level = outlet_level(ch)
    if "atmosphere" in names and "atmosphere" not in boundaries:
        boundaries["atmosphere"] = Boundary(kind="atmosphere")
    for wall in ("bed", "banks", "floodplain", "barrel"):
        if wall in names and wall not in boundaries:
            boundaries[wall] = Boundary(kind="wall")
    if "outlet" not in project.flow_monitors:
        project.flow_monitors.append("outlet")
    area, _perimeter = wetted(ch, ch.water_depth)
    inlet = project.boundaries["inlet"]
    speed = inlet.flow_rate / area if inlet.kind == "flowRateInlet" and area > 0 else 1.0
    done += free_surface_run(project, ch.cell_size, total_length(ch), speed)
    return done
