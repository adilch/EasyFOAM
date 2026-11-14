"""Hydraulic structures made from their design values.

An ogee crest from its design head, a stepped spillway, a labyrinth weir, the USBR stilling basins, a culvert
through an embankment and a vertical-slot fishway. Each is built in a straight channel that runs along +x: across
it from ``y0`` to ``y0 + width``, standing on the bed at level ``bed``, starting at ``station``. Parts that meet the
side walls or the bed reach a little beyond them, so that the mesh is cut cleanly; snappyHexMesh removes the solid
from the base mesh like any other shape.

The shapes and sizes follow the usual design references: the WES standard crest (USACE Hydraulic Design Criteria
111-1, also USBR Design of Small Dams), Chanson for stepped chutes, Crookston and Tullis's notation for
labyrinths, USBR Engineering Monograph 25 (Peterka) for stilling basins and Rajaratnam, Van der Vinne and
Katopodis (1986) for vertical-slot fishways.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from easyfoam.drawn import _extrude, _outwards
from easyfoam.model import Structure

G = 9.81
WES_C = 2.18  # discharge coefficient of the WES crest at its design head, SI (Q = C L H^1.5), for P/Hd >= 1.33


@dataclass(frozen=True)
class Value:
    """One design value of a structure, as the program asks for it."""

    key: str
    label: str
    unit: str
    default: float
    tip: str = ""
    choices: tuple[tuple[float, str], ...] = ()  # a few fixed options instead of a number


#: kind -> (title, what it is for)
KINDS = {
    "ogee": ("Ogee crest", "A spillway crest shaped to the lower nappe of the flow at its design head (WES)."),
    "stepped": ("Stepped spillway", "An ogee crest followed by a stepped chute that takes energy out of the flow."),
    "labyrinth": ("Labyrinth weir", "A weir folded in plan: a long crest across a narrow channel."),
    "basin": ("USBR stilling basin", "Chute blocks, baffle blocks and an end sill that hold a hydraulic jump."),
    "culvert": ("Culvert", "An embankment across the channel with box or pipe barrels through it."),
    "fishway": ("Vertical-slot fishway", "Pools separated by baffles with a vertical slot, stepping down a slope."),
}

VALUES: dict[str, tuple[Value, ...]] = {
    "ogee": (
        Value("design_head", "Design head Hd", "m", 0.1, "The head over the crest the shape is made for."),
        Value("height", "Crest height P", "m", 0.4, "Height of the crest above the bed upstream."),
        Value("face_slope", "Downstream face", "H per V", 0.75, "Slope of the straight face below the curve."),
        Value("toe_radius", "Toe radius", "m", 0.1, "Radius of the curve that joins the face to the bed; 0 = sharp."),
    ),
    "stepped": (
        Value("design_head", "Design head Hd", "m", 0.08, "The head over the crest the shape is made for."),
        Value("height", "Crest height", "m", 1.0, "Height of the crest above the bed at the foot of the chute."),
        Value("face_slope", "Chute slope", "H per V", 0.8, "Slope of the line through the step edges."),
        Value("step_height", "Step height", "m", 0.06, "Height of each step (made to fit the chute exactly)."),
    ),
    "labyrinth": (
        Value("height", "Weir height P", "m", 0.3, "Height of the walls above the bed."),
        Value("cycles", "Cycles", "", 2, "How many folds across the channel."),
        Value("angle", "Sidewall angle", "°", 15, "Angle of the side walls to the flow, 6 to 35 degrees."),
        Value("apex", "Apex width", "m", 0.05, "Length of the wall at each apex, measured on its centreline."),
        Value("thickness", "Wall thickness", "m", 0.025, ""),
    ),
    "basin": (
        Value(
            "basin_type",
            "USBR type",
            "",
            3,
            "Type II for high dams, III for small ones (both Froude above 4.5), IV for Froude 2.5 to 4.5.",
            ((2.0, "Type II"), (3.0, "Type III"), (4.0, "Type IV")),
        ),
        Value("y1", "Depth entering y1", "m", 0.03, "Depth of the fast water entering the basin."),
        Value("froude", "Froude number Fr1", "", 6.0, "Froude number of the water entering the basin."),
    ),
    "culvert": (
        Value("circular", "Barrels", "", 0, "", ((0.0, "Box"), (1.0, "Pipe"))),
        Value("span", "Span or diameter", "m", 0.2, "Width of a box barrel, or the diameter of a pipe."),
        Value("rise", "Rise (box)", "m", 0.15, "Height of a box barrel."),
        Value("count", "Number of barrels", "", 1, ""),
        Value("length", "Barrel length", "m", 0.6, "Length of the barrels: the embankment between the headwalls."),
        Value("road", "Road level", "m", 0.4, "Top of the embankment above the bed; water above it overtops."),
        Value(
            "invert",
            "Invert",
            "m",
            0.0,
            "Level of the barrel floor above the bed. Below zero the barrels are "
            "buried that deep in the bed, as culverts for fish passage often are.",
        ),
    ),
    "fishway": (
        Value("slot", "Slot width b", "m", 0.05, "Width of the vertical slot; pools are 10 b long and 8 b wide."),
        Value("pools", "Pools", "", 3, ""),
        Value("drop", "Drop per pool", "m", 0.03, "Fall of the floor from one pool to the next."),
        Value("wall", "Baffle height", "m", 0.35, "Height of the baffles above the floor."),
    ),
}


@dataclass
class Built:
    """A structure made: its solid surfaces, outlines to draw and its design figures in words."""

    bodies: list[np.ndarray] = field(default_factory=list)  # closed surfaces, (n, 3, 3) triangles each
    side: list[list[tuple[float, float]]] = field(default_factory=list)  # outlines in x-z
    plan: list[list[tuple[float, float]]] = field(default_factory=list)  # outlines in x-y
    water: list[list[tuple[float, float]]] = field(default_factory=list)  # design water levels in x-z, as lines
    openings: list[list[tuple[float, float]]] = field(default_factory=list)  # side view: where the water goes through
    openings_plan: list[list[tuple[float, float]]] = field(default_factory=list)  # plan: the same, from above
    info: list[str] = field(default_factory=list)


def kind_name(kind: str) -> str:
    """The name of a kind of structure for use within a sentence: 'ogee crest', but 'USBR stilling basin'."""
    title = KINDS[kind][0]
    return title if title[1:2].isupper() else title[0].lower() + title[1:]


def value(st: Structure, key: str) -> float:
    for spec in VALUES.get(st.kind, ()):
        if spec.key == key:
            return float(st.values.get(key, spec.default))
    raise KeyError(f"'{st.kind}' has no value '{key}'")


def defaults(kind: str, scale: float = 1.0) -> dict[str, float]:
    """The design values a new structure starts with; lengths are multiplied by ``scale``."""
    return {spec.key: spec.default * (scale if spec.unit == "m" else 1.0) for spec in VALUES[kind]}


def place(kind: str, lo, hi) -> Structure:
    """A new structure right across the box ``lo``-``hi``, on its floor, a third of the way along it.

    Its sizes start from the design values of a laboratory model, scaled by powers of ten to the height of the box.
    """
    height, width = hi[2] - lo[2], hi[1] - lo[1]
    scale = 10.0 ** round(math.log10(height / 1.5)) if height > 0 else 1.0
    values = defaults(kind, scale)
    if kind == "fishway" and width > 0:  # pools 8 slots wide fill the channel
        values["slot"] = float(f"{width / 8:.3g}")
    return Structure(kind=kind, station=round(lo[0] + (hi[0] - lo[0]) / 3, 6), bed=lo[2], y0=lo[1], width=width,
                     values=values)  # fmt: skip


def _margin(st: Structure) -> float:
    """How far parts reach beyond the side walls and below the bed."""
    return max(0.25 * st.width, 0.05)


def triangles(st: Structure) -> np.ndarray:
    """All the solid surfaces of a structure, as triangles (n, 3, 3)."""
    return np.concatenate(build(st).bodies)


def problems(st: Structure) -> list[str]:
    """What stops the structure from being made, in plain words (empty when it can be)."""
    if st.kind not in KINDS:
        return [f"unknown structure '{st.kind}'"]
    if st.width <= 0:
        return ["the channel width must be above zero"]
    out = [f"{spec.label[0].lower()}{spec.label[1:]} must be above zero" for spec in VALUES[st.kind]
           if not spec.choices and spec.key not in ("invert", "toe_radius") and value(st, spec.key) <= 0]  # fmt: skip
    if out:
        return out
    try:
        build(st)
    except ValueError as exc:
        return [str(exc)]
    return []


def fit_warnings(st: Structure, lo, hi) -> list[str]:
    """What looks wrong with where the structure stands in the box ``lo``-``hi`` (the base mesh), in plain words."""
    out = []
    if st.y0 > lo[1] + 1e-9 or st.y0 + st.width < hi[1] - 1e-9:
        out.append(f"it spans y = {st.y0:g} to {st.y0 + st.width:g} m but the base mesh runs from {lo[1]:g} to "
                   f"{hi[1]:g} m: water can pass beside it")  # fmt: skip
    if st.bed > lo[2] + 1e-9:
        out.append(f"its bed ({st.bed:g} m) is above the floor of the base mesh ({lo[2]:g} m): water can pass under it")
    try:
        points = np.concatenate(build(st).bodies).reshape(-1, 3)
    except ValueError:
        return out
    if st.station <= lo[0]:
        out.append("it starts at the upstream end of the base mesh: leave room for the water to arrive")
    if points[:, 0].max() >= hi[0]:
        out.append("it reaches past the downstream end of the base mesh")
    if points[:, 2].max() >= hi[2]:
        out.append("it stands higher than the top of the base mesh: nothing can flow over it")
    return out


def build(st: Structure) -> Built:
    return {"ogee": _ogee, "stepped": _stepped, "labyrinth": _labyrinth, "basin": _basin, "culvert": _culvert,
            "fishway": _fishway}[st.kind](st)  # fmt: skip


# --- bodies ------------------------------------------------------------------------------------------------------


def _across(profile, st: Structure) -> np.ndarray:
    """A profile in x-z extruded right across the channel."""
    m = _margin(st)
    return _extrude(profile, "xz", (st.y0 - m, st.y0 + st.width + m))


def _upright(outline, low: float, high: float) -> np.ndarray:
    """An outline in plan (x-y) extruded from ``low`` to ``high``."""
    return _extrude(outline, "xy", (low, high))


def _rect(x0: float, x1: float, y0: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --- ogee crest and stepped spillway ------------------------------------------------------------------------------


def _arc(centre, radius: float, start, end, count: int) -> list[tuple[float, float]]:
    a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
    a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
    if a1 - a0 > math.pi:
        a1 -= 2 * math.pi
    elif a0 - a1 > math.pi:
        a1 += 2 * math.pi
    return [(centre[0] + radius * math.cos(a0 + (a1 - a0) * k / count),
             centre[1] + radius * math.sin(a0 + (a1 - a0) * k / count)) for k in range(1, count + 1)]  # fmt: skip


def wes_crest(hd: float, xc: float, zc: float):
    """The WES crest around its apex (xc, zc): upstream points from the vertical face to the apex.

    The upstream quadrant is three circles of radii 0.5, 0.2 and 0.04 Hd that meet tangentially at 0.175 and
    0.276 Hd upstream of the apex; the last one turns vertical at 0.2818 Hd, where the upstream face begins.
    """
    r1, r2, r3 = 0.5 * hd, 0.2 * hd, 0.04 * hd
    c1 = np.array([xc, zc - r1])
    p1 = np.array([xc - 0.175 * hd, c1[1] + math.sqrt(r1**2 - (0.175 * hd) ** 2)])
    c2 = p1 + (r2 / r1) * (c1 - p1)
    x2 = xc - 0.276 * hd
    p2 = np.array([x2, c2[1] + math.sqrt(r2**2 - (x2 - c2[0]) ** 2)])
    c3 = p2 + (r3 / r2) * (c2 - p2)
    face = (float(c3[0] - r3), float(c3[1]))
    points = [face]
    points += _arc(c3, r3, face, p2, 4)
    points += _arc(c2, r2, p2, p1, 8)
    points += _arc(c1, r1, p1, (xc, zc), 10)
    return points


def _wes_downstream(hd: float, xc: float, zc: float, slope: float, bed: float):
    """Points down the WES curve z = zc - x^1.85 / (2 Hd^0.85) to where it is as steep as the face (or the bed)."""
    tangent = hd * (2.0 / (1.85 * slope)) ** (1.0 / 0.85)
    reach_bed = (2.0 * hd**0.85 * (zc - bed)) ** (1.0 / 1.85)
    end = min(tangent, reach_bed)
    xs = end * (np.linspace(0, 1, 25)[1:] ** 1.5)
    return [(xc + x, zc - x**1.85 / (2 * hd**0.85)) for x in xs], end < tangent


def _toe(top, slope: float, bed: float, radius: float):
    """From the end of the curve down the straight face to the bed, through a toe curve of the given radius."""
    xt, zt = top
    corner = (xt + slope * (zt - bed), bed)
    if radius <= 0:
        return [corner]
    turn = math.atan(1.0 / slope)
    along = radius * math.tan(turn / 2)
    length = math.hypot(corner[0] - xt, corner[1] - zt)
    along = min(along, 0.9 * length)
    radius = along / math.tan(turn / 2)
    direction = ((corner[0] - xt) / length, (corner[1] - zt) / length)
    start = (corner[0] - along * direction[0], corner[1] - along * direction[1])
    centre = (corner[0] + along, bed + radius)
    return [start] + _arc(centre, radius, start, (corner[0] + along, bed), 8)


def _ogee(st: Structure) -> Built:
    hd, p = value(st, "design_head"), value(st, "height")
    slope, radius = value(st, "face_slope"), max(0.0, value(st, "toe_radius"))
    below = max(0.25 * p, 0.05)
    x_face, bed = st.station, st.bed
    xc, zc = x_face + 0.2818 * hd, bed + p
    crest = wes_crest(hd, xc, zc)
    down, short = _wes_downstream(hd, xc, zc, slope, bed)
    profile = [(x_face, bed - below)] + crest + down
    if short:  # a low crest: the curve reaches the bed before it is as steep as the face
        end = profile[-1][0]
    else:
        profile += _toe(down[-1], slope, bed, radius)
        end = profile[-1][0]
    profile += [(end, bed - below)]
    built = Built([_across(profile, st)], side=[profile], plan=[_rect(x_face, end, st.y0, st.y0 + st.width)])
    built.water = [[(x_face - 4 * hd, zc + hd), (xc, zc + hd)]]  # the design head, upstream
    q = WES_C * st.width * hd**1.5
    built.info = [
        f"Design discharge for this width: Q = {WES_C} W Hd^1.5 = {q:.4g} m³/s ({q / st.width:.4g} m²/s per metre).",
        f"P/Hd = {p / hd:.2f}" + (" (at least 1.33: the approach flow does not lower the coefficient)."
                                   if p / hd >= 1.33 else ": below 1.33 the approach flow lowers the coefficient."),
        f"The crest runs {end - x_face:.3g} m along the channel; the apex is {xc - x_face:.3g} m from its upstream face.",
    ]  # fmt: skip
    return built


def _stepped(st: Structure) -> Built:
    hd, height = value(st, "design_head"), value(st, "height")
    slope, wanted = value(st, "face_slope"), value(st, "step_height")
    below = max(0.25 * height, 0.05)
    x_face, bed = st.station, st.bed
    xc, zc = x_face + 0.2818 * hd, bed + height
    crest = wes_crest(hd, xc, zc)
    down, short = _wes_downstream(hd, xc, zc, slope, bed)
    if short:
        raise ValueError("the crest is too low for steps: raise the crest or lower the design head")
    xt, zt = down[-1]
    count = max(1, round((zt - bed) / wanted))
    h = (zt - bed) / count
    tread = slope * h
    steps = []
    for k in range(count):
        steps.append((xt + k * tread, zt - (k + 1) * h))  # down a riser
        if k < count - 1:  # and along a tread; below the last riser the bed carries on
            steps.append((xt + (k + 1) * tread, zt - (k + 1) * h))
    end = xt + (count - 1) * tread
    profile = [(x_face, bed - below)] + crest + down + steps + [(end, bed - below)]
    built = Built([_across(profile, st)], side=[profile], plan=[_rect(x_face, end, st.y0, st.y0 + st.width)])
    built.water = [[(x_face - 4 * hd, zc + hd), (xc, zc + hd)]]
    q = WES_C * hd**1.5
    dc = (q * q / G) ** (1 / 3)
    skimming, nappe = 1.2 - 0.325 * h / tread, 0.89 - 0.4 * h / tread  # Chanson: onsets of skimming and nappe flow
    regime = "skimming flow" if dc / h > skimming else "nappe flow" if dc / h < nappe else "transition flow"
    built.info = [
        f"{count} steps {h:.3g} m high with treads {tread:.3g} m long, down {zt - bed:.3g} m of chute.",
        f"At the design head q = {q:.4g} m²/s and the critical depth is {dc:.3g} m: dc/h = {dc / h:.2f}, {regime} "
        f"(skimming above {skimming:.2f}, nappe below {nappe:.2f}).",
        f"Design discharge for this width: {q * st.width:.4g} m³/s.",
    ]
    return built


# --- labyrinth weir ---------------------------------------------------------------------------------------------


def _offset(line: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    """A polyline moved sideways by ``distance`` (to its left), with mitred corners."""
    pts = np.asarray(line, float)
    out = []
    for i in range(len(pts)):
        normals = []
        for a, b in ((i - 1, i), (i, i + 1)):
            if 0 <= a and b < len(pts):
                d = pts[b] - pts[a]
                d /= np.linalg.norm(d)
                normals.append(np.array([-d[1], d[0]]))
        n = sum(normals)
        n /= np.linalg.norm(n)
        scale = distance / max(float(np.dot(n, normals[0])), 0.2)
        out.append(tuple(pts[i] + n * scale))
    return out


def _labyrinth(st: Structure) -> Built:
    height, cycles = value(st, "height"), max(1, round(value(st, "cycles")))
    angle, apex, thick = math.radians(value(st, "angle")), value(st, "apex"), value(st, "thickness")
    w = st.width / cycles
    if apex <= thick:
        raise ValueError("the apex must be wider than the wall is thick")
    if 2 * apex >= w / 2:
        raise ValueError("the apices take up the whole cycle: use fewer cycles or narrower apices")
    if not math.radians(2) < angle < math.radians(80):
        raise ValueError("the sidewall angle must lie between 2 and 80 degrees")
    length = (w / 2 - apex) / math.tan(angle)
    m = _margin(st)
    x0 = st.station
    line = [(x0, st.y0 - m)]
    for k in range(cycles):
        yc = st.y0 + k * w
        line += [(x0, yc + apex / 2), (x0 + length, yc + w / 2 - apex / 2), (x0 + length, yc + w / 2 + apex / 2),
                 (x0, yc + w - apex / 2)]  # fmt: skip
    line.append((x0, st.y0 + st.width + m))
    footprint = _offset(line, thick / 2) + _offset(line, -thick / 2)[::-1]
    below = max(0.25 * height, 0.05)
    body = _upright(footprint, st.bed - below, st.bed + height)
    crest = cycles * (apex + 2 * math.hypot(length, w / 2 - apex) + apex)
    built = Built([body], side=[_rect(x0 - thick / 2, x0 + length + thick / 2, st.bed, st.bed + height)],
                  plan=[footprint])  # fmt: skip
    built.info = [
        f"Each of the {cycles} cycles is {w:.3g} m wide; the weir reaches {length:.3g} m along the channel.",
        f"Crest length {crest:.3g} m on the centreline: {crest / st.width:.2f} times the channel width.",
    ]
    return built


# --- USBR stilling basins -----------------------------------------------------------------------------------------


def basin_design(y1: float, froude: float, kind: int) -> dict[str, float]:
    """Sizes of a USBR stilling basin (Engineering Monograph 25) for the flow entering it."""
    v1 = froude * math.sqrt(G * y1)
    y2 = 0.5 * y1 * (math.sqrt(1 + 8 * froude**2) - 1)
    out = {"v1": v1, "q": v1 * y1, "y2": y2}
    if kind == 2:
        out.update(length=4.3 * y2, block_h=y1, block_w=y1, block_gap=y1, sill_h=0.2 * y2, tooth_w=0.15 * y2,
                   tooth_gap=0.15 * y2, tailwater=y2)  # fmt: skip
    elif kind == 3:
        h3 = y1 * (0.168 * froude + 0.63)
        out.update(length=2.7 * y2, block_h=y1, block_w=y1, block_gap=y1, baffle_h=h3, baffle_w=0.75 * h3,
                   baffle_gap=0.75 * h3, baffle_x=0.8 * y2, sill_h=y1 * (0.0556 * froude + 1.0), tailwater=y2)  # fmt: skip
    elif kind == 4:
        out.update(length=6.1 * y2, block_h=2 * y1, block_w=y1, block_gap=2.5 * y1, sill_h=1.25 * y1,
                   tailwater=1.1 * y2)  # fmt: skip
    else:
        raise ValueError("choose USBR type II, III or IV")
    return out


def _row(st: Structure, width: float, gap: float, count: int | None = None) -> list[float]:
    """Left edges of a row of blocks of the given width and gap, centred across the channel.

    As many fit as leave at least half a gap at each wall (or ``count``, if fewer).
    """
    fits = int(st.width / (width + gap) + 1e-9)
    count = fits if count is None else max(0, min(count, fits))
    start = st.y0 + (st.width - count * width - (count - 1) * gap) / 2
    return [start + k * (width + gap) for k in range(count)]


def _overlap(row_a: list[float], width_a: float, row_b: list[float], width_b: float) -> float:
    """How much two rows of blocks cover the same width of the channel."""
    return sum(max(0.0, min(a + width_a, b + width_b) - max(a, b)) for a in row_a for b in row_b)


def _basin(st: Structure) -> Built:
    y1, froude, kind = value(st, "y1"), value(st, "froude"), round(value(st, "basin_type"))
    d = basin_design(y1, froude, kind)
    x0, bed, below = st.station, st.bed, max(y1, 0.02)
    end = x0 + d["length"]
    built = Built()
    # chute blocks at the entrance of the basin
    hb, wb, gb = d["block_h"], d["block_w"], d["block_gap"]
    chute = _row(st, wb, gb)
    for y in chute:
        profile = [(x0, bed - below), (x0, bed + hb), (x0 + 2 * hb, bed + hb), (x0 + 2 * hb, bed - below)]
        built.bodies.append(_extrude(profile, "xz", (y, y + wb)))
        built.plan.append(_rect(x0, x0 + 2 * hb, y, y + wb))
    built.side.append([(x0, bed), (x0, bed + hb), (x0 + 2 * hb, bed + hb), (x0 + 2 * hb, bed)])
    if kind == 3:  # baffle blocks, staggered against the chute blocks as far as their spacing allows
        h3, w3, g3 = d["baffle_h"], d["baffle_w"], d["baffle_gap"]
        xb = x0 + d["baffle_x"]
        profile = [(xb, bed - below), (xb, bed + h3), (xb + 0.2 * h3, bed + h3), (xb + 1.2 * h3, bed),
                   (xb + 1.2 * h3, bed - below)]  # fmt: skip
        full = _row(st, w3, g3)
        rows = [full, _row(st, w3, g3, len(full) - 1)] if len(full) > 1 else [full]
        for y in min(rows, key=lambda row: _overlap(row, w3, chute, wb) / max(len(row), 1)):
            built.bodies.append(_extrude(profile, "xz", (y, y + w3)))
            built.plan.append(_rect(xb, xb + 1.2 * h3, y, y + w3))
        built.side.append([(x, max(z, bed)) for x, z in profile])
    h4 = d["sill_h"]
    sill = [(end - 2.25 * h4, bed - below), (end - 2.25 * h4, bed), (end - 0.25 * h4, bed + h4), (end, bed + h4),
            (end, bed - below)]  # fmt: skip
    if kind == 2:  # a dentated sill: teeth with spaces between them
        for y in _row(st, d["tooth_w"], d["tooth_gap"]):
            built.bodies.append(_extrude(sill, "xz", (y, y + d["tooth_w"])))
            built.plan.append(_rect(end - 2.25 * h4, end, y, y + d["tooth_w"]))
    else:
        built.bodies.append(_across(sill, st))
        built.plan.append(_rect(end - 2.25 * h4, end, st.y0, st.y0 + st.width))
    built.side.append([(x, max(z, bed)) for x, z in sill])
    if not built.bodies:
        raise ValueError("the channel is too narrow for the blocks")
    built.water = [
        [(x0 - 0.5 * d["length"], bed + y1), (x0, bed + y1)],
        [(end - 0.25 * d["length"], bed + d["tailwater"]), (end + 0.5 * d["length"], bed + d["tailwater"])],
    ]
    title = {2: "II", 3: "III", 4: "IV"}[kind]
    built.info = [
        f"Entering: V1 = {d['v1']:.3g} m/s, q = {d['q']:.4g} m²/s; the sequent depth is y2 = {d['y2']:.3g} m.",
        f"Type {title} basin {d['length']:.3g} m long; the tailwater should stand {d['tailwater']:.3g} m above the basin floor.",
        f"Chute blocks {hb:.3g} m high and {wb:.3g} m wide; end sill {h4:.3g} m high"
        + (f"; baffle blocks {d['baffle_h']:.3g} m high at {d['baffle_x']:.3g} m." if kind == 3 else "."),
    ]
    if not chute:
        built.info.append("The channel is narrower than a block and its gap, so it has no chute blocks: model a "
                          "wider slice to see them work.")  # fmt: skip
    if kind in (2, 3) and froude <= 4.5:
        built.info.append(f"Type {title} is for Fr1 above 4.5; between 2.5 and 4.5 use Type IV.")
    if kind == 3 and d["v1"] > 18:
        built.info.append("Above about 18 m/s cavitation would damage the baffle blocks of a Type III basin: "
                          "use Type II.")  # fmt: skip
    if kind == 4 and not 2.5 <= froude <= 4.5:
        built.info.append("Type IV is for Fr1 between 2.5 and 4.5; above 4.5 use Type III, or II for high dams.")
    return built


# --- culvert -----------------------------------------------------------------------------------------------------


def _quad(a, b, c, d, outward) -> list[list]:
    """Two triangles of the quad a-b-c-d, turned so that they face ``outward``."""
    a, b, c, d = (np.asarray(p, float) for p in (a, b, c, d))
    if np.dot(np.cross(b - a, c - a), outward) < 0:
        a, b, c, d = a, d, c, b
    return [[a, b, c], [a, c, d]]


def _strips(x0, x1, levels, fixed, plane, outward) -> list[list]:
    """A flat rectangle at ``fixed`` cut into strips at the given levels (which run along y or z)."""
    out = []
    for lo, hi in zip(levels, levels[1:]):
        if plane == "z":  # a face of constant z, strips across y
            pts = [(x0, lo, fixed), (x1, lo, fixed), (x1, hi, fixed), (x0, hi, fixed)]
        else:  # a face of constant y, strips across z
            pts = [(x0, fixed, lo), (x1, fixed, lo), (x1, fixed, hi), (x0, fixed, hi)]
        out += _quad(*pts, outward)
    return out


def culvert_surface(x0, x1, ylo, yhi, zlo, zhi, centres, zc, span, rise, circular) -> np.ndarray:
    """A closed block pierced along x by barrels, with every edge shared by exactly two triangles."""
    tris: list[list] = []
    if not circular:
        ys = sorted({ylo, yhi, *(y - span / 2 for y in centres), *(y + span / 2 for y in centres)})
        zs = sorted({zlo, zhi, zc, zc + rise})
        for x, out in ((x0, (-1, 0, 0)), (x1, (1, 0, 0))):
            for ya, yb in zip(ys, ys[1:]):
                for za, zb in zip(zs, zs[1:]):
                    ym, zm = (ya + yb) / 2, (za + zb) / 2
                    if any(abs(ym - y) < span / 2 and zc < zm < zc + rise for y in centres):
                        continue  # the barrel's opening
                    tris += _quad((x, ya, za), (x, yb, za), (x, yb, zb), (x, ya, zb), out)
        for y in centres:  # the barrel walls face into the barrel
            a, b = y - span / 2, y + span / 2
            tris += _quad((x0, a, zc), (x1, a, zc), (x1, b, zc), (x0, b, zc), (0, 0, 1))
            tris += _quad((x0, a, zc + rise), (x1, a, zc + rise), (x1, b, zc + rise), (x0, b, zc + rise), (0, 0, -1))
            tris += _quad((x0, a, zc), (x1, a, zc), (x1, a, zc + rise), (x0, a, zc + rise), (0, 1, 0))
            tris += _quad((x0, b, zc), (x1, b, zc), (x1, b, zc + rise), (x0, b, zc + rise), (0, -1, 0))
        edge_y, edge_z = ys, zs
    else:
        r = span / 2
        mid = zc + r
        levels = [mid + r * 1.2 * math.sin(a) for a in np.linspace(-math.pi / 2, math.pi / 2, 9)]
        zs = sorted({zlo, zhi, *(z for z in levels if zlo < z < zhi)})
        bounds = [ylo] + [(a + b) / 2 for a, b in zip(centres, centres[1:])] + [yhi]
        edge_y = []
        for (ya, yb), yc in zip(zip(bounds, bounds[1:]), centres):
            across = list(np.linspace(ya, yb, 10)[1:-1])
            outer = ([(y, zlo) for y in [ya, *across]] + [(yb, z) for z in zs[:-1]]
                     + [(y, zhi) for y in [yb, *across[::-1]]] + [(ya, z) for z in zs[:0:-1]])  # fmt: skip
            edge_y += [ya, *across]
            ring = [(yc + r * (y - yc) / math.hypot(y - yc, z - mid), mid + r * (z - mid) / math.hypot(y - yc, z - mid))
                    for y, z in outer]  # fmt: skip
            count = len(outer)
            for k in range(count):
                o0, o1, c0, c1 = outer[k], outer[(k + 1) % count], ring[k], ring[(k + 1) % count]
                for x, out in ((x0, (-1, 0, 0)), (x1, (1, 0, 0))):
                    tris += _quad((x, *c0), (x, *c1), (x, *o1), (x, *o0), out)
                inward = (0.0, yc - (c0[0] + c1[0]) / 2, mid - (c0[1] + c1[1]) / 2)
                tris += _quad((x0, *c0), (x0, *c1), (x1, *c1), (x1, *c0), inward)
        edge_y = sorted(set(edge_y + [yhi]))
        edge_z = zs
    tris += _strips(x0, x1, edge_y, zlo, "z", (0, 0, -1))
    tris += _strips(x0, x1, edge_y, zhi, "z", (0, 0, 1))
    tris += _strips(x0, x1, edge_z, ylo, "y", (0, -1, 0))
    tris += _strips(x0, x1, edge_z, yhi, "y", (0, 1, 0))
    return np.asarray(tris, float)


def _open_area(span: float, rise: float, invert: float, circular: bool) -> float:
    """Area of one barrel above the bed (a barrel with a negative invert is buried that deep in it)."""
    if not circular:
        return span * (rise + min(invert, 0.0))
    r, d = span / 2, max(0.0, -invert)
    buried = r * r * math.acos((r - d) / r) - (r - d) * math.sqrt(max(0.0, 2 * r * d - d * d))
    return math.pi * r * r - buried


def _culvert(st: Structure) -> Built:
    circular = value(st, "circular") >= 0.5
    span, rise = value(st, "span"), value(st, "span") if circular else value(st, "rise")
    count, length = max(1, round(value(st, "count"))), value(st, "length")
    road, invert = value(st, "road"), value(st, "invert")
    m = _margin(st)
    if invert <= -0.9 * rise:
        raise ValueError("the barrels are buried in the bed: raise the invert")
    if invert + rise >= road:
        raise ValueError("the barrels must fit below the road")
    pitch = st.width / count
    if span >= 0.9 * pitch:
        raise ValueError("the barrels do not fit side by side in the channel")
    below = max(0.25 * road, 0.05, 0.5 * rise - invert)
    floor, height = st.bed + invert, rise
    if not circular and invert <= 0:  # the bed is the floor of the barrel: keep the box's own floor below it
        floor, height = st.bed - 0.5 * below, st.bed + invert + rise - (st.bed - 0.5 * below)
    centres = [st.y0 + pitch * (k + 0.5) for k in range(count)]
    x0, x1 = st.station, st.station + length
    surface = culvert_surface(x0, x1, st.y0 - m, st.y0 + st.width + m, st.bed - below, st.bed + road, centres, floor,
                              span, height, circular)  # fmt: skip
    built = Built([_outwards(surface)], side=[_rect(x0, x1, st.bed, st.bed + road)],
                  plan=[_rect(x0, x1, st.y0, st.y0 + st.width)])  # fmt: skip
    bottom, top = st.bed + max(invert, 0.0), st.bed + invert + rise
    built.openings.append(_rect(x0, x1, bottom, top))
    for y in centres:
        built.openings_plan.append(_rect(x0, x1, y - span / 2, y + span / 2))
    area = count * _open_area(span, rise, invert, circular)
    head = st.bed + road - (bottom + top) / 2
    built.info = [
        f"{count} {'pipe' if circular else 'box'} barrel{'s' * (count > 1)}: {area:.4g} m² of opening"
        + (f", buried {-invert:.3g} m in the bed." if invert < 0 else "."),
        f"Just before the road overtops, the barrels pass about {0.6 * area * math.sqrt(2 * G * head):.4g} m³/s "
        "(orifice flow, Cd = 0.6, square-edged headwall).",
    ]
    return built


# --- vertical-slot fishway ---------------------------------------------------------------------------------------

SLOT_ANGLE = 30.0  # degrees: the slot points its jet this far from the flow, into the pool
SLOT_HEAD = 1.5  # slot widths: length along the flow of the baffle heads that form the slot


def fishway_baffle(st: Structure, x: float, b: float):
    """The two baffles across the channel at ``x`` (their upstream face), in plan: the long one and the short one.

    The slot between them lies beside the far wall (y0 + width). Its sides are parallel and b apart, and turned so
    that the jet leaves it pointing into the pool rather than straight at the next slot: the short baffle widens
    downstream and the long one ends in a head with a sloping face, then carries on as a thin wall.
    """
    far, m, t = st.y0 + st.width, _margin(st), 0.5 * b
    head, slope = SLOT_HEAD * b, math.tan(math.radians(SLOT_ANGLE))
    shift = head * slope  # how far the slot moves across the channel along the heads
    short_edge = far - b  # the short baffle is one slot width wide at its upstream face
    tip = short_edge - b / math.cos(math.radians(SLOT_ANGLE))  # the long baffle's tip: the slot is b wide across
    short = [(x, short_edge), (x + head, short_edge - shift), (x + head, far + m), (x, far + m)]
    long = [(x, tip), (x, st.y0 - m), (x + t, st.y0 - m), (x + t, tip - shift - t), (x + head, tip - shift - t),
            (x + head, tip - shift)]  # fmt: skip
    return long, short


def _fishway(st: Structure) -> Built:
    b, pools = value(st, "slot"), max(1, round(value(st, "pools")))
    drop, wall = value(st, "drop"), value(st, "wall")
    pool, wide = 10 * b, 8 * b
    x0, bed = st.station, st.bed
    rise = pools * drop
    x_end = x0 + pools * pool
    below = max(0.25 * wall, 0.05)
    # the floor rises from the bed at the foot of the fishway to the first pool, a step up from the bay upstream
    floor = [(x0, bed - below), (x0, bed + rise), (x_end, bed), (x_end, bed - below)]
    built = Built([_across(floor, st)], side=[floor[1:3] + [(x0, bed)]])
    top = bed + rise + wall
    for k in range(pools + 1):
        xk = x0 + k * pool - (SLOT_HEAD * b if k == pools else 0.0)
        for outline in fishway_baffle(st, xk, b):
            built.bodies.append(_upright(outline, bed - below, top))
            built.plan.append(outline)
        built.side.append(_rect(xk, xk + SLOT_HEAD * b, bed + (pools - k) * drop, top))
    vmax = math.sqrt(2 * G * drop)
    built.info = [
        f"{pools} pools {pool:.3g} m long and {wide:.3g} m wide (the channel is {st.width:.3g} m wide), slope {drop / pool:.3g}.",
        f"Each slot sends its jet {SLOT_ANGLE:g}° into the pool, where it loses its energy; the fastest water in the "
        f"slots is about √(2 g Δh) = {vmax:.3g} m/s.",
    ]
    if abs(st.width - wide) > 0.05 * wide:
        built.info.append(f"Make the channel {wide:.3g} m wide (8 b) for the usual proportions.")
    return built
