"""Hydraulic results of a free-surface run, in the terms of a hydraulic engineer.

- long section: bed, water level, energy line, discharge, Froude number station by station;
- hydraulic jumps (with Bélanger's sequent depth) and control sections (Froude number passing 1);
- pressure along the surface of a structure;
- forces and overturning moments on structures;
- bed shear stress, and how it compares with the critical stress of a sediment (Shields).

Everything works on the results as read by :mod:`easyfoam.results` (PyVista grids). Levels and
depths are in m, discharges in m³/s, heads in m of water, forces in N and moments in N·m.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from easyfoam.model import Project

WATER = "alpha.water"
#: vertical samples per base cell: evenly divisible by the cells of up to three refinement levels
SAMPLES_PER_CELL = 8
MAX_LATERAL = 64  # sampling lines across the channel at each station, at most
TOE_SLOPE = 0.02  # a (smoothed) water surface rising faster than this, in m per m, belongs to a jump
END_SLOPE = 0.01
ROLLER_ALPHA = 1.1  # a jet with a velocity coefficient above this already has the roller over it


# --- the channel axis -------------------------------------------------------------


@dataclass
class Centreline:
    """The channel axis in plan, along which the long section is taken."""

    points: np.ndarray  # (n, 2): x, y
    half_width: float  # how far to each side the cross-sections reach

    @property
    def chainage(self) -> np.ndarray:
        steps = np.linalg.norm(np.diff(self.points, axis=0), axis=1)
        return np.concatenate([[0.0], np.cumsum(steps)])

    @property
    def length(self) -> float:
        return float(self.chainage[-1])

    def at(self, s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Positions (n, 2) and unit tangents (n, 2) at chainages ``s``."""
        s = np.atleast_1d(np.asarray(s, float))
        chain = self.chainage
        segment = np.clip(np.searchsorted(chain, s, side="right") - 1, 0, len(chain) - 2)
        start, end = self.points[segment], self.points[segment + 1]
        length = (chain[segment + 1] - chain[segment])[:, None]
        tangent = (end - start) / np.where(length > 0, length, 1.0)
        position = start + tangent * (s - chain[segment])[:, None]
        return position, tangent


def default_centreline(project: Project) -> Centreline:
    """The line drawn for the long section in the 3D view; or the centreline of a built channel; or else a straight
    axis along x through the middle of the base mesh."""
    drawn = np.asarray(getattr(project, "section_line", None) or [], float).reshape(-1, 2)
    if len(drawn) >= 2 and np.linalg.norm(np.diff(drawn, axis=0), axis=1).sum() > 0:
        if project.channel is not None:
            from easyfoam import channel

            half = channel.section(project.channel).half_width
        else:
            base = project.mesh.base
            along_x = abs(drawn[-1, 0] - drawn[0, 0]) >= abs(drawn[-1, 1] - drawn[0, 1])
            half = (base.max[1] - base.min[1] if along_x else base.max[0] - base.min[0]) / 2
        return Centreline(drawn, half)
    if project.channel is not None:
        from easyfoam import channel

        return Centreline(channel.centreline_points(project.channel), channel.section(project.channel).half_width)
    base = project.mesh.base
    middle = (base.min[1] + base.max[1]) / 2
    points = np.array([[base.min[0], middle], [base.max[0], middle]], float)
    return Centreline(points, (base.max[1] - base.min[1]) / 2)


def gravity(project: Project) -> float:
    g = [float(c) for c in project.physics.gravity]
    if abs(g[0]) > 1e-9 * abs(g[2]) or abs(g[1]) > 1e-9 * abs(g[2]) or g[2] >= 0:
        raise ValueError("hydraulic results need gravity pointing straight down the z axis")
    return -g[2]


def reference_level(project: Project, case_dir: Path | None) -> float:
    """The level ``hRef`` that the solver measures ``p_rgh`` from (0 unless there is a tailwater outlet)."""
    if case_dir is None:
        return 0.0
    from easyfoam.casegen.freesurface import href_dict
    from easyfoam.foam.boundaryfile import read_boundary

    entry = href_dict(project, read_boundary(Path(case_dir)))
    return float(entry["value"]) if entry else 0.0


# --- the long section -------------------------------------------------------------

#: column name -> (heading in tables, attribute)
COLUMNS = {
    "chainage": "chainage [m]",
    "x": "x [m]",
    "y": "y [m]",
    "bed": "bed level [m]",
    "water_level": "water level [m]",
    "depth": "depth [m]",
    "hydraulic_depth": "hydraulic depth A/T [m]",
    "area": "flow area [m2]",
    "top_width": "top width [m]",
    "discharge": "discharge [m3/s]",
    "unit_discharge": "discharge per metre width [m2/s]",
    "velocity": "mean velocity [m/s]",
    "froude": "Froude number [-]",
    "specific_energy": "specific energy [m]",
    "energy_level": "energy level [m]",
    "total_head": "total head from the flow field [m]",
    "coriolis": "velocity coefficient alpha [-]",
}


@dataclass
class LongSection:
    """Station-by-station hydraulic quantities along the channel (NaN where the channel is dry)."""

    chainage: np.ndarray
    x: np.ndarray
    y: np.ndarray
    bed: np.ndarray
    water_level: np.ndarray
    depth: np.ndarray  # water level above the lowest point of the section
    hydraulic_depth: np.ndarray  # flow area / top width
    area: np.ndarray
    top_width: np.ndarray
    discharge: np.ndarray
    unit_discharge: np.ndarray
    velocity: np.ndarray
    froude: np.ndarray
    specific_energy: np.ndarray  # hydraulic depth + V²/2g
    energy_level: np.ndarray  # water level + V²/2g (the 1D energy line)
    total_head: np.ndarray  # flux-weighted p/ρg + z + u²/2g of the flow field itself
    coriolis: np.ndarray  # energy (velocity) coefficient alpha of the velocity distribution
    g: float = 9.81
    time: float | None = None

    @property
    def wet(self) -> np.ndarray:
        return np.isfinite(self.area) & (self.area > 0)

    def flow_order(self) -> np.ndarray:
        """Indices of the wet stations, in the direction the water flows."""
        wet = np.flatnonzero(self.wet)
        if wet.size and np.nanmedian(self.discharge[wet]) < 0:
            return wet[::-1]
        return wet

    def value_at(self, name: str, chainage: float) -> float:
        wet = self.wet
        return float(np.interp(chainage, self.chainage[wet], getattr(self, name)[wet]))

    def rows(self) -> list[list[float]]:
        columns = [getattr(self, name) for name in COLUMNS]
        return [[float(c[i]) for c in columns] for i in range(len(self.chainage))]

    def write_csv(self, path: Path) -> None:
        write_table(path, list(COLUMNS.values()), self.rows())


def _sample(grid, points: np.ndarray):
    """The cell values of ``grid`` at ``points``, and which points lie inside the fluid."""
    import pyvista as pv

    source = grid.copy(deep=False)
    source.point_data.clear()  # sample the cell values: piecewise constant, exactly as the solver has them
    probed = pv.PolyData(points).sample(source)
    return probed.point_data, np.asarray(probed.point_data["vtkValidPointMask"]).astype(bool)


def long_section(
    data,
    project: Project,
    case_dir: Path | None = None,
    centreline: Centreline | None = None,
    stations: int | None = None,
    time: float | None = None,
) -> LongSection:
    """Integrate the water across the channel at stations along its axis.

    At each station vertical lines across the width sample the result; along each line the water
    fraction gives the depth (as a gauge does), and together the lines give the flow area, the
    discharge and the energy carried through the section.
    """
    grid = data.internal
    if WATER not in grid.array_names:
        raise ValueError("a long section needs the results of a free-surface run (water and air)")
    g = gravity(project)
    rho = float(project.physics.rho)
    href = reference_level(project, case_dir)
    base = project.mesh.base
    line = centreline or default_centreline(project)

    if project.channel is not None:
        cell_x = project.channel.cell_size
    else:
        cell_x = (base.max[0] - base.min[0]) / max(1, base.cells[0])
    count = stations or int(np.clip(round(line.length / cell_x), 2, 2000))
    chainage = (np.arange(count) + 0.5) * line.length / count
    position, tangent = line.at(chainage)
    if project.channel is not None:  # across its own width, not across the box round its bends
        lines_across = math.ceil(2 * line.half_width / project.channel.cell_size) + 1
    else:
        lines_across = int(base.cells[1])
    across = min(MAX_LATERAL, max(1, lines_across)) if line.half_width > 0 else 1
    offsets = (np.arange(across) + 0.5) / across * 2 * line.half_width - line.half_width
    strip = 2 * line.half_width / across if line.half_width > 0 else 1.0
    z_low, z_high = float(base.min[2]), float(base.max[2])
    levels = int(min(1600, max(40, base.cells[2] * SAMPLES_PER_CELL)))
    dz = (z_high - z_low) / levels
    z = z_low + (np.arange(levels) + 0.5) * dz
    wet_depth = max(1e-4, 0.1 * (z_high - z_low) / max(1, base.cells[2]))
    has_head = "p_rgh" in grid.array_names

    names = [n for n in COLUMNS if n not in ("chainage", "x", "y")]
    out = {n: np.full(count, np.nan) for n in names}
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    chunk = max(1, 400000 // (across * levels))
    for first in range(0, count, chunk):
        sl = slice(first, min(count, first + chunk))
        n_st = sl.stop - sl.start
        plan = position[sl, None, :] + offsets[None, :, None] * normal[sl, None, :]  # (n, across, 2)
        pts = np.empty((n_st, across, levels, 3))
        pts[..., 0] = plan[..., 0][..., None]
        pts[..., 1] = plan[..., 1][..., None]
        pts[..., 2] = z
        values, valid = _sample(grid, pts.reshape(-1, 3))
        shape = (n_st, across, levels)
        valid = valid.reshape(shape)
        alpha = np.where(valid, np.clip(np.asarray(values[WATER]).reshape(shape), 0.0, 1.0), 0.0)
        velocity = np.where(valid[..., None], np.asarray(values["U"]).reshape(*shape, 3), 0.0)
        t = tangent[sl]
        u_along = velocity[..., 0] * t[:, None, None, 0] + velocity[..., 1] * t[:, None, None, 1]
        if has_head:
            # static pressure from p_rgh with the local mixture density, so that the half-water cells at the
            # surface carry the head of their own elevation, not the head of the water below them
            p_rgh = np.where(valid, np.asarray(values["p_rgh"]).reshape(shape), 0.0)
            mixture = alpha * rho + (1.0 - alpha) * float(project.physics.air_rho)
            static = p_rgh - mixture * g * (z - href)
            head = static / (rho * g) + z + (velocity**2).sum(-1) / (2 * g)
        else:
            head = np.zeros(shape)

        depth = alpha.sum(-1) * dz  # (n, across)
        reached = valid.any(-1)
        bottom = z_low + np.argmax(valid, axis=-1) * dz
        surface = bottom + depth
        q_col = (alpha * u_along).sum(-1) * dz
        e_col = (alpha * u_along * head).sum(-1) * dz
        k3_col = (alpha * u_along**3).sum(-1) * dz
        wet = depth > wet_depth

        area = depth.sum(1) * strip
        width = wet.sum(1) * strip
        discharge = q_col.sum(1) * strip
        with np.errstate(invalid="ignore", divide="ignore"):
            level = np.where(wet, surface, 0).sum(1) * strip / width
            bed = np.where(reached, bottom, np.inf).min(1)
            mean_v = discharge / area
            hyd_depth = area / width
            froude = np.abs(mean_v) / np.sqrt(g * hyd_depth)
            total = e_col.sum(1) * strip / discharge
            coriolis = k3_col.sum(1) * strip / (mean_v**3 * area)
        dry = (width <= 0) | (area <= 0)
        results = {
            "bed": np.where(np.isfinite(bed), bed, np.nan),
            "water_level": level,
            "depth": level - bed,
            "hydraulic_depth": hyd_depth,
            "area": area,
            "top_width": width,
            "discharge": discharge,
            "unit_discharge": discharge / np.where(width > 0, width, np.nan),
            "velocity": mean_v,
            "froude": froude,
            "specific_energy": hyd_depth + mean_v**2 / (2 * g),
            "energy_level": level + mean_v**2 / (2 * g),
            "total_head": np.where(np.abs(discharge) > 1e-12, total, np.nan) if has_head else np.nan,
            "coriolis": np.where(np.abs(mean_v) > 1e-9, coriolis, np.nan),
        }
        for name, value in results.items():
            value = np.broadcast_to(np.asarray(value, float), (n_st,)).copy()
            value[dry] = np.nan
            out[name][sl] = value
        out["bed"][sl] = np.where(np.isfinite(bed), bed, np.nan)  # the bed is known even where it is dry
    return LongSection(chainage=chainage, x=position[:, 0], y=position[:, 1], g=g, time=time, **out)


def average_sections(sections: Sequence[LongSection]) -> LongSection:
    """The mean of long sections taken at several times (for jumps and waves that move about)."""
    if not sections:
        raise ValueError("no long sections to average")
    names = [n for n in COLUMNS if n not in ("chainage", "x", "y")]
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # a station dry at every time stays NaN
            mean = {n: np.nanmean(np.stack([getattr(s, n) for s in sections]), axis=0) for n in names}
    first = sections[0]
    return LongSection(chainage=first.chainage, x=first.x, y=first.y, g=first.g, time=sections[-1].time, **mean)


# --- jumps and control sections ---------------------------------------------------

JUMP_KINDS = (
    (1.7, "undular jump"),
    (2.5, "weak jump"),
    (4.5, "oscillating jump"),
    (9.0, "steady jump"),
    (math.inf, "strong jump"),
)


def sequent_depth(y1: float, froude1: float) -> float:
    """Bélanger's sequent (conjugate) depth after a jump in a rectangular channel."""
    return 0.5 * y1 * (math.sqrt(1.0 + 8.0 * froude1 * froude1) - 1.0)


def jump_loss(y1: float, y2: float) -> float:
    """Energy lost in a jump between depths y1 and y2 (rectangular channel)."""
    return (y2 - y1) ** 3 / (4.0 * y1 * y2)


@dataclass
class Jump:
    toe: float  # chainage where the surface starts to rise
    end: float  # chainage where it stops rising
    y1: float
    velocity1: float
    froude1: float
    y2: float  # measured depth after the jump
    y2_theory: float  # Bélanger
    loss: float  # specific energy lost, measured
    loss_theory: float

    @property
    def length(self) -> float:
        return abs(self.end - self.toe)

    @property
    def kind(self) -> str:
        return next(label for limit, label in JUMP_KINDS if self.froude1 < limit)

    def lines(self) -> list[str]:
        ratio = self.y2 / self.y2_theory if self.y2_theory else math.nan
        return [
            f"Hydraulic jump ({self.kind}) from chainage {self.toe:.3g} m to {self.end:.3g} m, "
            f"about {self.length:.3g} m long.",
            f"Before: depth {self.y1:.3g} m, velocity {self.velocity1:.3g} m/s, Froude number {self.froude1:.3g}.",
            f"After: depth {self.y2:.3g} m; Bélanger's sequent depth is {self.y2_theory:.3g} m "
            f"({100 * (ratio - 1):+.0f} %).",
            f"Energy lost: {self.loss:.3g} m (theory {self.loss_theory:.3g} m).",
        ]


@dataclass
class Control:
    """A control section: the flow passes from subcritical to supercritical (as over a crest)."""

    chainage: float
    depth: float
    critical_depth: float

    def lines(self) -> list[str]:
        return [
            f"Critical flow at chainage {self.chainage:.3g} m: depth {self.depth:.3g} m, "
            f"critical depth (q²/g)^(1/3) = {self.critical_depth:.3g} m."
        ]


def _smoothed(values: np.ndarray, width: int) -> np.ndarray:
    """Running mean over ``width`` stations (shorter at the ends)."""
    if width <= 1:
        return values.copy()
    kernel = np.ones(width)
    total = np.convolve(values, kernel, mode="same")
    count = np.convolve(np.ones_like(values), kernel, mode="same")
    return total / count


def find_jumps(section: LongSection) -> list[Jump]:
    """Hydraulic jumps: supercritical flow that rises to subcritical, on a bed without steps.

    The toe is where the incoming jet still has a uniform velocity: under the roller the flow at the
    surface turns back and the velocity coefficient rises well above 1. (Without velocities, the toe is
    where the surface, smoothed over one and a half downstream depths, starts to rise.) The depth after
    the jump is the mean over a stretch of a few depths past its end, not the overshoot of the roller.
    In an oscillating jump, average the long section over several saved times first.
    """
    order = section.flow_order()
    if order.size < 3:
        return []
    s = np.abs(section.chainage[order] - section.chainage[order[0]])
    y, fr = section.hydraulic_depth[order], section.froude[order]
    v, bed = np.abs(section.velocity[order]), section.bed[order]
    spacing = float(np.median(np.diff(s))) or 1.0

    jumps, i = [], 1
    while i < len(order):
        if not (fr[i - 1] > 1.0 and fr[i] <= 1.0):
            i += 1
            continue
        downstream = (s >= s[i]) & (s <= s[i] + 5.0 * y[i])
        width = max(3, int(round(1.5 * float(np.max(y[downstream])) / spacing)) | 1)  # 1.5 downstream depths
        smooth = _smoothed(y, width)

        def rise(a: int, b: int, smooth: np.ndarray = smooth) -> float:
            return (smooth[b] - smooth[a]) / max(s[b] - s[a], 1e-12)

        alpha = section.coriolis[order]
        toe = i - 1
        if np.isfinite(alpha[: i]).all():
            # the roller turns the flow back at the surface, which makes the velocity distribution uneven:
            # the toe is where the incoming jet is still uniform (velocity coefficient below 1.1)
            while toe > 0 and fr[toe - 1] > 1.0 and alpha[toe] > ROLLER_ALPHA:
                toe -= 1
        else:  # no velocity distribution: the surface, smoothed, must have stopped rising
            while toe > 0 and fr[toe - 1] > 1.0 and rise(toe - 1, toe) > TOE_SLOPE:
                toe -= 1
            toe = min(i - 1, toe + width // 2)  # a running mean starts to rise half its width before the kink
        end = i
        while end + 1 < len(order) and rise(end, end + 1) > END_SLOPE:
            end += 1
        end = max(i, end - width // 2)  # and stops rising half its width after the roller ends
        after = (s >= s[end]) & (s <= s[end] + 3.0 * y[end])
        y2 = float(np.mean(y[after]))
        q2 = float(np.mean(v[after] * y[after]))
        e1 = y[toe] + v[toe] ** 2 / (2 * section.g)
        e2 = y2 + (q2 / y2) ** 2 / (2 * section.g)
        steady_bed = abs(bed[end] - bed[toe]) < 0.3 * max(y2 - y[toe], 1e-9)  # not a drop or a step
        if fr[toe] > 1.1 and y2 > y[toe] and steady_bed and e1 - e2 > -0.05 * e1:
            y2_theory = sequent_depth(float(y[toe]), float(fr[toe]))
            jumps.append(
                Jump(
                    toe=float(section.chainage[order[toe]]),
                    end=float(section.chainage[order[end]]),
                    y1=float(y[toe]),
                    velocity1=float(v[toe]),
                    froude1=float(fr[toe]),
                    y2=y2,
                    y2_theory=y2_theory,
                    loss=float(e1 - e2),
                    loss_theory=jump_loss(float(y[toe]), y2_theory),
                )
            )
        i = end + 1
    return jumps


def find_controls(section: LongSection) -> list[Control]:
    order = section.flow_order()
    fr, y, bed = section.froude[order], section.hydraulic_depth[order], section.bed[order]
    found = []
    for i in range(1, len(order)):
        gradual = abs(y[i] - y[i - 1]) < 0.3 * max(y[i], y[i - 1]) and abs(bed[i] - bed[i - 1]) < 0.3 * y[i - 1]
        if fr[i - 1] < 1.0 <= fr[i] and gradual:
            a, b = order[i - 1], order[i]
            share = (1.0 - fr[i - 1]) / (fr[i] - fr[i - 1])
            chainage = float(section.chainage[a] + share * (section.chainage[b] - section.chainage[a]))
            q = float(abs(section.unit_discharge[a] + share * (section.unit_discharge[b] - section.unit_discharge[a])))
            depth = float(section.hydraulic_depth[a] + share * (section.hydraulic_depth[b] - section.hydraulic_depth[a]))
            found.append(Control(chainage, depth, (q * q / section.g) ** (1.0 / 3.0)))
    return found


def summary(section: LongSection) -> list[str]:
    """What a hydraulic engineer would note first about a long section."""
    order = section.flow_order()
    if order.size == 0:
        return ["There is no water in the channel at this time."]
    first, last = order[0], order[-1]
    q_in, q_out = section.discharge[first], section.discharge[last]
    lines = [
        f"Discharge {abs(q_in):.4g} m³/s at the upstream end, {abs(q_out):.4g} m³/s at the downstream end.",
        f"Water level {section.water_level[first]:.4g} m upstream, {section.water_level[last]:.4g} m downstream; "
        f"Froude number from {np.nanmin(section.froude[order]):.2g} to {np.nanmax(section.froude[order]):.2g}.",
    ]
    loss = section.energy_level[first] - section.energy_level[last]
    lines.append(f"Energy line drops {loss:.3g} m from end to end.")
    for control in find_controls(section):
        lines += control.lines()
    for jump in find_jumps(section):
        lines += jump.lines()
    return lines


# --- structures: pressure along the surface, and loads ----------------------------


def pressure_scale(project: Project) -> float:
    """What multiplies the solver's ``p`` to give pascals."""
    from easyfoam.solvers import solver_spec

    return 1.0 if solver_spec(project.physics.solver).multiphase else float(project.physics.rho)


@dataclass
class PressureProfile:
    distance: np.ndarray  # along the surface, from its upstream end [m]
    x: np.ndarray
    z: np.ndarray
    head: np.ndarray  # pressure head p/ρg [m of water]; negative = below atmospheric

    def rows(self) -> list[list[float]]:
        return [[float(a), float(b), float(c), float(d)] for a, b, c, d in zip(self.distance, self.x, self.z, self.head)]

    def write_csv(self, path: Path) -> None:
        write_table(path, ["distance along the surface [m]", "x [m]", "z [m]", "pressure head [m]"], self.rows())


def pressure_profile(surface, project: Project, lateral: float | None = None) -> PressureProfile:
    """Pressure head along the surface of a structure, cut across the channel at ``lateral`` (y)."""
    if "p" not in surface.array_names:
        raise ValueError("the result has no pressure on this surface")
    g = gravity(project)
    scale = pressure_scale(project)
    rho = float(project.physics.rho)
    # merge corners that faces share (to within rounding), so that the pressure is averaged across them
    points = surface.clean(tolerance=1e-7, lines_to_points=False, polys_to_lines=False).cell_data_to_point_data()
    x0, x1, y0, y1, z0, z1 = surface.bounds
    middle = (y0 + y1) / 2 if lateral is None else lateral
    cut = points.slice(normal=(0, 1, 0), origin=((x0 + x1) / 2, middle, (z0 + z1) / 2))
    if cut.n_points < 2:
        raise ValueError("the surface does not cross the middle of the channel")
    joined = cut.clean(tolerance=1e-7).strip(join=True)  # neighbouring faces share their cut points
    lines, i = np.asarray(joined.lines), 0
    pieces = []
    while i < len(lines):
        n = int(lines[i])
        pieces.append(lines[i + 1 : i + 1 + n])
        i += n + 1
    xyz = np.asarray(joined.points)
    p = np.asarray(joined.point_data["p"], float) * scale
    pieces.sort(key=lambda ids: xyz[ids, 0].min())
    chain, distance, total = [], [], 0.0
    for ids in pieces:
        ids = ids if xyz[ids[0], 0] <= xyz[ids[-1], 0] else ids[::-1]
        steps = np.r_[0.0, np.linalg.norm(np.diff(xyz[ids], axis=0), axis=1)]
        distance.append(total + np.cumsum(steps))
        total = distance[-1][-1]
        chain.append(ids)
    ids = np.concatenate(chain)
    return PressureProfile(np.concatenate(distance), xyz[ids, 0], xyz[ids, 2], p[ids] / (rho * g))


def area_vectors(surface) -> tuple[np.ndarray, np.ndarray]:
    """Centres and area vectors (normal × area, in the order of the face's corners) of a surface's faces.

    The faces of an OpenFOAM boundary are ordered so that the vector points out of the fluid.
    """
    faces, points = np.asarray(surface.faces), np.asarray(surface.points, float)
    starts, sizes, i = [], [], 0
    while i < len(faces):
        starts.append(i + 1)
        sizes.append(int(faces[i]))
        i += sizes[-1] + 1
    starts, sizes = np.asarray(starts), np.asarray(sizes)
    centres = np.zeros((len(sizes), 3))
    vectors = np.zeros((len(sizes), 3))
    for n in np.unique(sizes):
        rows = np.flatnonzero(sizes == n)
        ids = faces[starts[rows, None] + np.arange(n)[None, :]]
        corners = points[ids]  # (faces, n, 3)
        centres[rows] = corners.mean(axis=1)
        vectors[rows] = 0.5 * np.cross(corners, np.roll(corners, -1, axis=1)).sum(axis=1)
    return centres, vectors


@dataclass
class Loads:
    """The force of the water on a structure and its moment about a point."""

    force: np.ndarray  # N, on the structure
    moment: np.ndarray  # N·m about ``point``
    point: np.ndarray
    width: float | None = None  # the structure spans the channel: this wide

    def per_metre(self, value: np.ndarray) -> np.ndarray | None:
        return None if not self.width else value / self.width

    def lines(self) -> list[str]:
        fx, _fy, fz = self.force
        lines = [
            f"Horizontal force along the flow {fx / 1000:.4g} kN, vertical force {fz / 1000:.4g} kN "
            f"({'uplift' if fz > 0 else 'downward'}).",
            f"Overturning moment about ({', '.join(f'{c:.3g}' for c in self.point)}) m: "
            f"{self.moment[1] / 1000:.4g} kN·m ({'downstream' if self.moment[1] > 0 else 'upstream'}).",
        ]
        if self.width:
            per = self.force / self.width
            lines.append(
                f"Per metre of width ({self.width:.3g} m wide): {per[0] / 1000:.4g} kN/m along the flow, "
                f"{per[2] / 1000:.4g} kN/m vertically, moment {self.moment[1] / self.width / 1000:.4g} kN·m/m."
            )
        return lines


def toe_point(surfaces: Sequence) -> np.ndarray:
    """The downstream end of the base of the structure: the usual point for overturning moments."""
    bounds = np.array([s.bounds for s in surfaces])
    return np.array([bounds[:, 1].max(), (bounds[:, 2].min() + bounds[:, 3].max()) / 2, bounds[:, 4].min()])


def structure_loads(surfaces: Sequence, project: Project, point: Sequence[float] | None = None) -> Loads:
    """Pressure force and moment of the water on the given boundary surfaces (friction left out)."""
    scale = pressure_scale(project)
    about = toe_point(surfaces) if point is None else np.asarray(point, float)
    force, moment = np.zeros(3), np.zeros(3)
    for surface in surfaces:
        if surface is None or surface.n_cells == 0:
            continue
        if "p" not in surface.array_names:
            raise ValueError("the result has no pressure on this surface")
        centres, vectors = area_vectors(surface)
        f = np.asarray(surface.cell_data["p"], float)[:, None] * scale * vectors
        force += f.sum(axis=0)
        moment += np.cross(centres - about, f).sum(axis=0)
    base = project.mesh.base
    y_lo = min(s.bounds[2] for s in surfaces)
    y_hi = max(s.bounds[3] for s in surfaces)
    tolerance = 1e-6 * max(1.0, base.max[1] - base.min[1])
    spans = y_lo <= base.min[1] + tolerance and y_hi >= base.max[1] - tolerance
    return Loads(force, moment, about, (base.max[1] - base.min[1]) if spans else None)


# --- bed shear stress and sediment --------------------------------------------------


def critical_shear_stress(
    d50: float, rho_sediment: float = 2650.0, rho_water: float = 998.0, nu: float = 1.0e-6, g: float = 9.81
) -> float:
    """Shear stress at which grains of size ``d50`` (m) start to move, in Pa (Shields, Soulsby-Whitehouse 1997)."""
    s = rho_sediment / rho_water
    grain = d50 * (g * (s - 1.0) / (nu * nu)) ** (1.0 / 3.0)
    shields = 0.30 / (1.0 + 1.2 * grain) + 0.055 * (1.0 - math.exp(-0.020 * grain))
    return shields * g * (rho_sediment - rho_water) * d50


def add_bed_shear(surface, project: Project, critical: float | None) -> float | None:
    """Add ``bedShearStress`` [Pa] (and ``sedimentMobility`` = stress / critical stress) to a wall surface.

    Returns the largest stress on it in the water, or ``None`` when the surface has no shear stress.
    """
    if surface is None or "wallShearStress" not in surface.array_names:
        return None
    kinematic = np.linalg.norm(np.asarray(surface.cell_data["wallShearStress"], float), axis=1)
    physics = project.physics
    if WATER in surface.array_names:
        water = np.clip(np.asarray(surface.cell_data[WATER], float), 0.0, 1.0)
        rho = water * physics.rho + (1.0 - water) * physics.air_rho
        wet = water > 0.5
    else:
        rho = np.full(kinematic.shape, float(physics.rho))
        wet = np.ones(kinematic.shape, bool)
    stress = rho * kinematic
    surface.cell_data["bedShearStress"] = stress
    if critical:
        surface.cell_data["sedimentMobility"] = stress / critical
    return float(stress[wet].max()) if wet.any() else 0.0


# --- tables -----------------------------------------------------------------------


def write_table(path: Path, header: Sequence[str], rows: Sequence[Sequence[float]]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(header)
        for row in rows:
            out.writerow(["" if isinstance(v, float) and math.isnan(v) else f"{v:.6g}" for v in row])


@dataclass
class Table:
    """A table to show and save: a heading per column and rows of numbers."""

    title: str
    header: list[str]
    rows: list[list[float]] = field(default_factory=list)

    def write_csv(self, path: Path) -> None:
        write_table(path, self.header, self.rows)


# --- rating curves ----------------------------------------------------------------


@dataclass
class RatingPoint:
    """The head over a structure at one discharge of a rating-curve run."""

    discharge: float  # set at the inlet, m³/s
    level: float  # mean water level at the gauge over the end of the hold, m
    head: float  # above the crest, m
    outflow: float  # mean discharge leaving the domain over the same window (nan if not recorded)
    coefficient: float  # C in Q = C·B·H^1.5, m^0.5/s
    discharge_coefficient: float  # Cd in Q = Cd·(2/3)·sqrt(2g)·B·H^1.5
    drift: float  # change of the level over the averaging window, m
    steady: bool


RATING_HEADER = [
    "discharge [m3/s]", "water level at the gauge [m]", "head over the crest [m]", "outflow [m3/s]",
    "weir coefficient C [m^0.5/s]", "discharge coefficient Cd [-]", "level drift over the window [m]", "steady",
]  # fmt: skip


def rating_points(
    times: Sequence[float],
    levels: Sequence[float],
    discharges: Sequence[float],
    hold: float,
    crest: float,
    width: float,
    g: float = 9.81,
    out_times: Sequence[float] | None = None,
    outflow: Sequence[float] | None = None,
    window: float = 0.4,
) -> list[RatingPoint]:
    """Average the gauge level over the last ``window`` share of each hold and turn it into a rating curve."""
    t = np.asarray(times, float)
    level = np.asarray(levels, float)
    points = []
    for k, q in enumerate(discharges):
        start, end = (k + 1 - window) * hold, (k + 1) * hold
        last = k == len(discharges) - 1
        chosen = (t >= start) & ((t <= end) if last else (t < end))  # the next discharge starts at ``end``
        if chosen.sum() < 2:
            continue
        mean = float(level[chosen].mean())
        slope = float(np.polyfit(t[chosen], level[chosen], 1)[0])
        drift = slope * (end - start)
        out = math.nan
        if out_times is not None and outflow is not None and len(out_times):
            ot = np.asarray(out_times, float)
            pick = (ot >= start) & (ot <= end)
            if pick.any():
                out = float(np.abs(np.asarray(outflow, float)[pick]).mean())
        head = mean - crest
        c = q / (width * head**1.5) if head > 0 else math.nan
        settled = abs(drift) < 0.02 * max(head, 1e-9) and (math.isnan(out) or abs(out - q) < 0.05 * q)
        points.append(RatingPoint(q, mean, head, out, c, c / (2.0 / 3.0 * math.sqrt(2 * g)), drift, settled))
    return points


def crest_level(project: Project, case_dir: Path | None) -> float:
    """The crest of the structure: the top of the highest solid shape inside the base mesh."""
    from easyfoam import geometry

    if project.rating.crest is not None:
        return float(project.rating.crest)
    base = project.mesh.base
    tops = []
    for shape in project.shapes:
        if shape.role != "wall":
            continue
        lo, hi = geometry.shape_bounds(shape, case_dir)
        if hi[2] < base.max[2] and lo[0] < base.max[0] and hi[0] > base.min[0]:
            tops.append(hi[2])
    if not tops:
        raise ValueError("set the crest level of the structure (no solid shape inside the base mesh was found)")
    return max(tops)


def rating_curve(project: Project, case_dir: Path) -> list[RatingPoint]:
    """The rating curve measured by a rating-curve run (see :class:`easyfoam.model.RatingCurve`)."""
    from easyfoam.foam.monitors import read_discharge, read_level_elevations

    rating = project.rating
    if not rating.discharges:
        raise ValueError("no discharges are set for a rating curve (Run step)")
    if not project.probes or rating.gauge >= len(project.probes):
        raise ValueError("a rating curve needs a probe point upstream of the structure to measure the water level")
    times, levels = read_level_elevations(case_dir, project.probes)
    if not times or rating.gauge >= len(levels):
        raise ValueError("the run has not recorded the water level at the gauge yet")
    outflow = next(iter(read_discharge(case_dir).values()), (None, None))
    base = project.mesh.base
    return rating_points(
        times, levels[rating.gauge], rating.discharges, rating.hold, crest_level(project, case_dir),
        base.max[1] - base.min[1], gravity(project), outflow[0], outflow[1],
    )  # fmt: skip


# --- a 1D backwater calculation to compare with ----------------------------------------


def backwater(section: LongSection, n: float, width: float | None = None, substeps: int = 8) -> np.ndarray:
    """The 1D gradually varied flow profile with Manning's ``n``, from the downstream end upstream.

    It starts from the depth computed at the most downstream wet station and integrates
    dh/ds = (S0 - Sf) / (1 - Fr²) upstream with the discharge of the long section, for a wide channel
    (or a rectangular one of the given width). It stops where the flow is no longer clearly subcritical
    or the bed has a step (a structure). Depths are returned as water levels; NaN where not computed.
    """
    order = section.flow_order()
    levels = np.full(len(section.chainage), np.nan)
    if order.size < 2 or n <= 0:
        return levels
    g = section.g
    q_total = float(np.nanmedian(np.abs(section.discharge[order])))

    def slope(h: float, b: float) -> float:
        if width is None:
            q = abs(float(section.unit_discharge[order[-1]]))
            area, radius, top = h, h, 1.0
            flow = q
        else:
            area, radius, top = width * h, width * h / (width + 2 * h), width
            flow = q_total
        velocity = flow / area
        friction = (n * velocity) ** 2 / radius ** (4.0 / 3.0)
        froude2 = velocity**2 * top / (g * area)
        return (b - friction) / (1.0 - froude2), froude2

    last = order[-1]
    depth = float(section.hydraulic_depth[last])
    levels[last] = section.bed[last] + depth
    for k in range(len(order) - 1, 0, -1):
        here, there = order[k], order[k - 1]
        step = float(section.chainage[there] - section.chainage[here])  # negative when going upstream
        if abs(section.bed[there] - section.bed[here]) > 0.3 * depth:
            break  # a structure: the 1D profile does not cross it
        bed_slope = -(section.bed[there] - section.bed[here]) / step if step else 0.0
        h, ds = depth, step / substeps
        for _ in range(substeps):
            k1, fr2 = slope(h, bed_slope)
            if fr2 > 0.8:
                return levels
            k2, _ = slope(h + 0.5 * ds * k1, bed_slope)
            k3, _ = slope(h + 0.5 * ds * k2, bed_slope)
            k4, _ = slope(h + ds * k3, bed_slope)
            h += ds * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
        depth = h
        levels[there] = section.bed[there] + depth
    return levels
