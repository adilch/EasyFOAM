"""A report of a project, ready for a design note: what was modelled, the mesh, the run, plots and pictures, and the
results checked against hydraulic theory (continuity, Bélanger, critical depth, the WES crest, USBR basins, Manning).

``build`` gathers it all from the project and its case folder; the window adds its pictures and plots. ``write``
saves it as a web page that holds everything (pictures included) or as a PDF.
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from easyfoam import __version__
from easyfoam.model import KIND_LABELS, Project, manning_from_ks, roughness_height
from easyfoam.solvers import SOLVERS, TURBULENCE, VISCOSITY_MODELS, solver_spec

OK, LOOK, FAIL, INFO = "ok", "look", "fail", "info"  # passes; worth a look; fails; for information only
VERDICT_WORDS = {OK: "Agrees", LOOK: "Look at it", FAIL: "Does not agree", INFO: "For information"}
_CELLS = re.compile(r"^\s*cells:\s+(\d+)")
G = 9.81


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    title: str = ""


@dataclass
class Figure:
    title: str
    png: bytes
    caption: str = ""


@dataclass
class Check:
    what: str
    theory: str  # what theory, or the set-up, gives
    found: str  # what the run gives
    verdict: str  # ok | look | fail | info
    note: str = ""


@dataclass
class Section:
    title: str
    text: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)


@dataclass
class Report:
    title: str
    facts: list[tuple[str, str]]
    sections: list[Section]
    checks: list[Check]


# --- numbers in words -------------------------------------------------------------------------------------------


def num(value: float | None, unit: str = "", digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    text = f"{value:.{digits}g}"
    return f"{text} {unit}".strip()


def vec(values: Sequence[float], unit: str = "") -> str:
    return f"({', '.join(f'{v:.4g}' for v in values)}) {unit}".strip()


def _relative(found: float, expected: float) -> float:
    return abs(found - expected) / abs(expected) if expected else math.inf


def _verdict(found: float, expected: float, good: float, fair: float) -> str:
    error = _relative(found, expected)
    return OK if error <= good else LOOK if error <= fair else FAIL


def _percent(found: float, expected: float) -> str:
    return f"{100 * (found / expected - 1):+.1f} %" if expected else ""


# --- what was modelled ------------------------------------------------------------------------------------------


def setup_section(project: Project) -> Section:
    ph, spec = project.physics, solver_spec(project.physics.solver)
    model = Table(["", ""], [
        ["Flow type", spec.label],
        ["Turbulence", TURBULENCE.get(ph.turbulence, (ph.turbulence,))[0]],
        ["Near walls", "wall functions" if ph.wall_treatment == "wallFunctions" else "boundary layer resolved"],
        ["Numerics", ph.numerics],
    ], "Model")  # fmt: skip
    if ph.max_velocity > 0:
        model.rows.append(["Velocity limited to", num(ph.max_velocity, "m/s")])
    fluid = Table(["", ""], [
        ["Fluid", ph.material],
        ["Kinematic viscosity ν", num(ph.nu, "m²/s")],
        ["Density ρ", num(ph.rho, "kg/m³")],
        ["Behaviour", VISCOSITY_MODELS.get(ph.viscosity_model, (ph.viscosity_model,))[0]],
    ], "Fluid")  # fmt: skip
    if spec.multiphase:
        fluid.rows += [
            ["Gravity", vec(ph.gravity, "m/s²")],
            ["Air: ν, ρ", f"{num(ph.air_nu, 'm²/s')}, {num(ph.air_rho, 'kg/m³')}"],
            ["Surface tension", num(ph.surface_tension, "N/m")],
        ]
        if ph.water_regions:
            boxes = "; ".join(f"x {r[0]:.4g}–{r[3]:.4g}, y {r[1]:.4g}–{r[4]:.4g}, z {r[2]:.4g}–{r[5]:.4g}"
                              for r in ph.water_regions[:4])  # fmt: skip
            more = f" and {len(ph.water_regions) - 4} more" if len(ph.water_regions) > 4 else ""
            fluid.rows.append(["Water at the start [m]", boxes + more])
        if ph.adaptive_levels:
            fluid.rows.append(["Refined at the water surface", f"{ph.adaptive_levels} levels"])
    elif any(ph.initial_velocity):
        fluid.rows.append(["Starting velocity", vec(ph.initial_velocity, "m/s")])
    tables = [model, fluid]
    if project.tracers:
        tables.append(Table(["Tracer", "Carries", "Diffusivity [m²/s]", "Decay [1/h]"], [
            [t.name, "age of the water" if t.kind == "age" else "concentration", num(t.diffusivity),
             "—" if t.kind == "age" else num(t.decay * 3600)] for t in project.tracers
        ], "Tracers"))  # fmt: skip
    run = project.run
    steady = solver_spec(ph.solver).steady
    control = Table(["", ""], [
        ["End", f"{run.end_time:g} iterations" if steady else num(run.end_time, "s")],
        ["Saved every", f"{run.write_interval:g} iterations" if steady else num(run.write_interval, "s")],
        ["Processor cores", str(run.processors)],
    ], "Run control")  # fmt: skip
    if not steady:
        step = f"adjusted to keep the Courant number below {run.max_courant:g}" if (run.adjust_time_step or spec.multiphase) \
            else f"{run.delta_t:g} s, fixed"  # fmt: skip
        control.rows.insert(1, ["Time step", step])
    elif run.residual_target > 0:
        control.rows.insert(1, ["Stops when residuals fall below", num(run.residual_target)])
    tables.append(control)
    return Section("What was modelled", tables=tables)


def _pieces(ch) -> str:
    bends = sum(s.kind == "bend" for s in ch.segments)
    length = sum(s.run() for s in ch.segments)
    return f"{length:g} m long" + (f" with {bends} bend{'s' if bends > 1 else ''}" if bends else ", straight")


def geometry_section(project: Project, case_dir: Path | None) -> Section:
    from easyfoam import geometry
    from easyfoam import structures as sm

    section = Section("Geometry")
    if project.channel is not None:
        ch = project.channel
        what = {"rectangular": "rectangular", "trapezoidal": f"trapezoidal, banks {ch.side_slope:g} H : 1 V",
                "compound": "compound, with floodplains", "circular": f"circular, diameter {ch.diameter:g} m"}  # fmt: skip
        section.text.append(
            f"An open channel built in EasyFOAM: {what.get(ch.section, ch.section)} section, bed {ch.bottom_width:g} m "
            f"wide, slope {ch.slope:g} m/m, {_pieces(ch)}, water {ch.water_depth:g} m deep at the start."
        )
    rows = []
    for shape in project.shapes:
        try:
            lo, hi = geometry.shape_bounds(shape, case_dir)
            extent = f"{vec(lo)} to {vec(hi)}"
        except (OSError, ValueError):
            extent = "—"
        what = shape.kind if shape.kind != "stl" else f"surface from {shape.file or 'a file'}"
        if shape.structure is not None:
            what = sm.kind_name(shape.structure.kind)
        use = "region to refine" if shape.role == "refinement" else "solid surface"
        level = f"level {shape.region_level}" if shape.role == "refinement" else f"levels {shape.level_min}–{shape.level_max}"
        rows.append([shape.name, what, use, level, extent])
    if rows:
        section.tables.append(Table(["Shape", "What it is", "Used as", "Refined", "Extent [m]"], rows))
    for shape in project.shapes:
        if shape.structure is None:
            continue
        st = shape.structure
        values = [[spec.label, num(sm.value(st, spec.key), spec.unit)] for spec in sm.VALUES.get(st.kind, ())
                  if not spec.choices]  # fmt: skip
        values += [[spec.label, dict(spec.choices).get(sm.value(st, spec.key), "")] for spec in sm.VALUES.get(st.kind, ())
                   if spec.choices]  # fmt: skip
        values = [["Station, bed level, width", f"x = {st.station:g} m, z = {st.bed:g} m, {st.width:g} m wide"], *values]
        section.tables.append(Table(["Design value", ""], values, f"{shape.name}: {sm.kind_name(st.kind)}"))
        try:
            section.text += [f"{shape.name}: {line}" for line in sm.build(st).info]
        except (ValueError, KeyError):
            pass
    if not project.shapes and project.channel is None:
        section.text.append("No shapes: the flow fills the base mesh.")
    return section


def mesh_cells(case_dir: Path | None) -> int | None:
    """The number of cells of the mesh, from the checkMesh log."""
    try:
        found = [m.group(1) for line in (Path(case_dir) / "log.checkMesh").read_text(errors="replace").splitlines()
                 if (m := _CELLS.match(line))]  # fmt: skip
    except (OSError, TypeError):
        return None
    return int(found[-1]) if found else None


def mesh_quality(case_dir: Path | None) -> tuple[str, list[str]]:
    """What checkMesh said: OK, failed or unknown, and the lines of the checks that failed."""
    try:
        text = (Path(case_dir) / "log.checkMesh").read_text(errors="replace")
    except (OSError, TypeError):
        return "unknown", []
    failed = [line.strip().lstrip("*").strip() for line in text.splitlines() if line.strip().startswith("***")]
    if "Mesh OK." in text:
        return "ok", failed
    if re.search(r"Failed \d+ mesh checks", text):
        return "failed", failed
    return "unknown", failed


def mesh_section(project: Project, case_dir: Path | None) -> Section:
    base, mesh = project.mesh.base, project.mesh
    size = [(hi - lo) / max(1, n) for lo, hi, n in zip(base.min, base.max, base.cells)]
    rows = [
        ["Base mesh", f"{vec(base.min)} to {vec(base.max)} m"],
        ["Base cells", f"{base.cells[0]} × {base.cells[1]} × {base.cells[2]}, cells of {vec(size, 'm')}"],
        ["Cut around the shapes", "yes (snappyHexMesh)" if mesh.snappy and project.shapes else "no"],
    ]
    if project.channel is not None:
        rows[0] = ["Mesh", f"follows the channel, cells of about {project.channel.cell_size:g} m"]
        rows.pop(1)
    cells = mesh_cells(case_dir)
    rows.append(["Cells in the mesh", f"{cells:,}" if cells else "not generated yet"])
    quality, failed = mesh_quality(case_dir)
    rows.append(["checkMesh", {"ok": "Mesh OK", "failed": "some checks failed", "unknown": "—"}[quality]])
    section = Section("Mesh", tables=[Table(["", ""], rows)])
    if failed:
        section.text.append("checkMesh: " + "; ".join(failed[:6]))
    return section


def boundary_section(project: Project, case_dir: Path | None) -> Section:
    from easyfoam.casegen.mesh import predicted_patches
    from easyfoam.foam.boundaryfile import read_boundary

    patches = (read_boundary(case_dir) if case_dir else []) or predicted_patches(project)
    multiphase = solver_spec(project.physics.solver).multiphase
    rows = []
    for patch in patches:
        bc = project.boundary_for(patch.name, patch.type)
        kind = KIND_LABELS.get(bc.kind, f"set by the mesh ({patch.type})")
        details = []
        if bc.kind == "velocityInlet":
            details.append(f"U = {vec(bc.velocity, 'm/s')}")
            if multiphase and bc.water_fraction < 1:
                details.append(f"water share {bc.water_fraction:g}")
        elif bc.kind == "flowRateInlet":
            details.append("Q changes in time (hydrograph)" if bc.flow_series else f"Q = {num(bc.flow_rate, 'm³/s')}")
        elif bc.kind == "waterLevelOutlet":
            details.append("level changes in time" if bc.level_series else f"water level {num(bc.level, 'm')}")
        elif bc.kind == "pressureOutlet":
            details.append(f"p = {num(bc.pressure)}")
        elif bc.kind == "waveInlet":
            details.append(f"waves {num(bc.wave_height, 'm')} high, period {num(bc.wave_period, 's')}, {bc.wave_model}")
        if bc.kind in ("wall", "movingWall"):
            ks = roughness_height(bc)
            if bc.roughness == "manning":
                details.append(f"Manning's n = {bc.manning:g}")
            elif ks > 0:
                details.append(f"roughness ks = {num(ks * 1000, 'mm')} (n ≈ {manning_from_ks(ks):.3g})")
            else:
                details.append("smooth")
        rows.append([patch.name, kind, ", ".join(details)])
    return Section("Boundaries", tables=[Table(["Boundary", "Condition", "Values"], rows)])


# --- the run ----------------------------------------------------------------------------------------------------


def read_log(project: Project, case_dir: Path | None):
    """The solver log of the last run, read (or None if there is none)."""
    from easyfoam.foam.logparser import LogParser

    log = Path(case_dir) / f"log.{project.physics.solver}" if case_dir else None
    if log is None or not log.is_file():
        return None
    parser = LogParser()
    with log.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parser.feed(line)
    return parser


def run_section(project: Project, parser) -> Section:
    section = Section("The run")
    if parser is None or not parser.times:
        section.text.append("The simulation has not been run yet.")
        return section
    from easyfoam.pace import took

    steady = solver_spec(project.physics.solver).steady
    reached = parser.times[-1]
    rows = [
        ["Reached", f"iteration {reached:g} of {project.run.end_time:g}" if steady
         else f"{reached:g} s of {project.run.end_time:g} s"],
        ["Finished", "yes" if parser.finished else ("no: " + parser.error if parser.error else "no, stopped early")],
        ["Time steps", f"{len(parser.times):,}"],
    ]  # fmt: skip
    if parser.execution_time:
        rows.append(["Computer time", took(parser.execution_time)])
    if parser.courant and not steady:
        rows.append(["Largest Courant number", num(max(c[1] for c in parser.courant[len(parser.courant) // 10:]), digits=3)])
    section.tables.append(Table(["", ""], rows))
    if parser.residuals:
        section.tables.append(Table(["Quantity", "Last initial residual"],
                                    [[name, f"{values[-1][1]:.2e}"] for name, values in sorted(parser.residuals.items())],
                                    "Residuals at the end"))  # fmt: skip
    return section


def _tail_mean(times: Sequence[float], values: Sequence[float], share: float = 0.25) -> float:
    """The mean over the last quarter of a record: what a run settled to."""
    t, v = np.asarray(times, float), np.asarray(values, float)
    if t.size == 0:
        return math.nan
    start = t[-1] - share * (t[-1] - t[0])
    return float(np.mean(v[t >= start]))


def results_section(project: Project, case_dir: Path | None, long=None, rating=None) -> Section:
    from easyfoam.foam.coeffs import read_coefficients
    from easyfoam.foam.monitors import read_discharge, read_level_elevations
    from easyfoam.foam.probes import read_probes

    section = Section("Results")
    if case_dir is None:
        return section
    flows = read_discharge(case_dir)
    if flows:
        section.tables.append(Table(["Through", "At the end [m³/s]", "Mean, last quarter of the run [m³/s]"], [
            [name, num(values[-1]), num(_tail_mean(times, values))] for name, (times, values) in sorted(flows.items())
        ], "Discharge (positive leaves the domain)"))  # fmt: skip
    if solver_spec(project.physics.solver).multiphase and project.probes:
        times, levels = read_level_elevations(case_dir, project.probes)
        if times and levels:
            section.tables.append(Table(["Gauge", "At x, y [m]", "Water level at the end [m]", "Mean, last quarter [m]"], [
                [str(i + 1), f"{project.probes[i][0]:g}, {project.probes[i][1]:g}", num(series[-1]),
                 num(_tail_mean(times, series))] for i, series in enumerate(levels)
            ], "Gauges"))  # fmt: skip
    else:
        probes = read_probes(case_dir)
        if "p" in probes and probes["p"][0]:
            _times, series = probes["p"]
            speed = probes.get("U", ([], []))[1]
            rows = []
            for i, values in enumerate(series):
                where = vec(project.probes[i]) if i < len(project.probes) else ""
                u = speed[i][-1] if i < len(speed) and speed[i] else None
                rows.append([str(i + 1), where, num(values[-1]), num(u)])
            section.tables.append(Table(["Probe", "At [m]", "p/ρ at the end [m²/s²]", "Speed [m/s]"], rows, "Probes"))
    if project.forces.enabled:
        coefficients = read_coefficients(case_dir)
        rows = [[name, num(values[-1])] for name, values in coefficients.items() if name in ("Cd", "Cl", "Cm", "CmPitch")
                and values]  # fmt: skip
        if rows:
            section.tables.append(Table(["Coefficient", "At the end"], rows, "Forces"))
    if long is not None:
        from easyfoam import hydraulics as hy

        section.text += hy.summary(long)
    if rating:
        section.tables.append(Table(["Discharge [m³/s]", "Head over the crest [m]", "Coefficient C = Q / (W H^1.5)"], [
            [num(p.discharge), num(p.head), num(p.coefficient, digits=3)] for p in rating
        ], "Rating curve"))  # fmt: skip
    return section


# --- checked against theory -------------------------------------------------------------------------------------


def run_checks(project: Project, parser, case_dir: Path | None) -> list[Check]:
    checks: list[Check] = []
    steady = solver_spec(project.physics.solver).steady
    quality, failed = mesh_quality(case_dir)
    if quality != "unknown":
        checks.append(Check("Mesh quality (checkMesh)", "all checks passed", "Mesh OK" if quality == "ok" else
                            f"{len(failed)} check(s) failed", OK if quality == "ok" else LOOK,
                            "; ".join(failed[:3])))  # fmt: skip
    if parser is None or not parser.times:
        return checks
    end, reached = project.run.end_time, parser.times[-1]
    done = parser.finished or reached >= end - 1e-6 * max(1.0, end)
    stopped_early = steady and parser.finished and reached < end  # a steady run that met its residual target
    checks.append(Check("The run went to its end", f"{end:g} {'iterations' if steady else 's'}",
                        f"{reached:g} {'iterations' if steady else 's'}" + (" (residuals met the target)" if stopped_early
                                                                             else ""),
                        FAIL if parser.error else OK if done else LOOK, parser.error or ""))  # fmt: skip
    if steady and parser.residuals:
        worst = max(values[-1][1] for values in parser.residuals.values())
        target = project.run.residual_target or 1e-4
        checks.append(Check("Residuals at the end", f"below {target:g}", f"largest {worst:.2e}",
                            OK if worst <= target else LOOK if worst <= 1e-2 else FAIL,
                            "" if worst <= target else "not converged to the target: run more iterations"))  # fmt: skip
    if not steady and parser.courant:
        limit = project.run.max_courant
        largest = max(c[1] for c in parser.courant[len(parser.courant) // 10:])
        checks.append(Check("Courant number", f"kept below {limit:g}", f"largest {largest:.3g}",
                            OK if largest <= 1.1 * limit else LOOK if largest <= 2 * limit else FAIL,
                            "after the first tenth of the run"))  # fmt: skip
    return checks


def continuity_checks(project: Project, case_dir: Path | None, long=None) -> list[Check]:
    """The water that comes in goes out again: set inflow against measured outflow, upstream against downstream."""
    from easyfoam.foam.monitors import read_discharge

    checks: list[Check] = []
    inflow = [b for b in project.boundaries.values() if b.kind == "flowRateInlet"]
    steady_in = sum(b.flow_rate for b in inflow) if inflow and not any(b.flow_series for b in inflow) else None
    flows = read_discharge(case_dir) if case_dir else {}
    out = {name: _tail_mean(t, v) for name, (t, v) in flows.items() if v and _tail_mean(t, v) > 0}
    steady = solver_spec(project.physics.solver).steady
    unsettled = "" if steady else ("a difference in a transient run can be water still filling or draining the "
                                   "domain: run longer, until the two agree")  # fmt: skip
    if steady_in and out:
        total = sum(out.values())
        verdict = _verdict(total, steady_in, 0.02, 0.05)
        checks.append(Check("Continuity: inflow set against outflow measured", num(steady_in, "m³/s"),
                            f"{num(total, 'm³/s')} through {', '.join(sorted(out))} ({_percent(total, steady_in)})",
                            verdict if steady or verdict == OK else LOOK,
                            "outflow averaged over the last quarter of the run" + (f"; {unsettled}" if verdict != OK
                                                                                    and unsettled else "")))  # fmt: skip
    if long is not None:
        order = long.flow_order()
        if order.size > 2:
            q_up, q_down = abs(long.discharge[order[0]]), abs(long.discharge[order[-1]])
            verdict = _verdict(q_down, q_up, 0.03, 0.08)
            checks.append(Check("Continuity along the channel", f"upstream {num(q_up, 'm³/s')}",
                                f"downstream {num(q_down, 'm³/s')} ({_percent(q_down, q_up)})",
                                verdict if verdict == OK else LOOK,
                                "from the long section" + (f"; {unsettled}" if verdict != OK and unsettled else "")))  # fmt: skip
    return checks


def hydraulic_checks(project: Project, long) -> list[Check]:
    """Jumps against Bélanger, control sections against critical depth, structures against their design."""
    from easyfoam import hydraulics as hy
    from easyfoam import structures as sm

    checks: list[Check] = []
    if long is None:
        return checks
    for jump in hy.find_jumps(long):
        checks.append(Check(f"Sequent depth of the jump at {jump.toe:.3g} m (Bélanger)",
                            f"{num(jump.y2_theory, 'm')} for y1 = {num(jump.y1, 'm', 3)}, Fr1 = {jump.froude1:.3g}",
                            f"{num(jump.y2, 'm')} ({_percent(jump.y2, jump.y2_theory)})",
                            _verdict(jump.y2, jump.y2_theory, 0.10, 0.20)))  # fmt: skip
        checks.append(Check("Energy lost in the jump", f"{num(jump.loss_theory, 'm', 3)} (Bélanger)",
                            f"{num(jump.loss, 'm', 3)}", _verdict(jump.loss, jump.loss_theory, 0.25, 0.5)))  # fmt: skip
    for control in hy.find_controls(long):
        checks.append(Check(f"Critical depth at the control at {control.chainage:.3g} m", f"(q²/g)^(1/3) = "
                            f"{num(control.critical_depth, 'm', 3)}", num(control.depth, "m", 3),
                            _verdict(control.depth, control.critical_depth, 0.10, 0.25)))  # fmt: skip
    for shape in project.shapes:
        st = shape.structure
        if st is None:
            continue
        try:
            if st.kind == "ogee":
                checks += _ogee_checks(st, long, sm)
            elif st.kind == "basin":
                checks += _basin_checks(st, long, sm)
        except (ValueError, KeyError, IndexError):
            continue
    if project.channel is not None:
        checks += _channel_checks(project, long)
    return checks


def _ogee_checks(st, long, sm) -> list[Check]:
    hd, crest = sm.value(st, "design_head"), st.bed + sm.value(st, "height")
    pool = (long.chainage > st.station - 6 * hd) & (long.chainage < st.station - 3 * hd) & long.wet
    if pool.sum() < 2:
        return []
    head = float(np.nanmean(long.water_level[pool])) - crest
    q = float(np.nanmean(np.abs(long.discharge[pool])))
    if head <= 0:
        return []
    coefficient = q / (st.width * head**1.5)
    ratio = head / hd
    return [
        Check("Discharge coefficient of the ogee crest (WES)", f"C = {sm.WES_C:g} at the design head Hd = {hd:g} m",
              f"C = {coefficient:.3g} at H = {num(head, 'm', 3)} (H/Hd = {ratio:.2f})",
              _verdict(coefficient, sm.WES_C, 0.03, 0.08) if 0.8 <= ratio <= 1.2 else INFO,
              "C = Q / (W H^1.5), with H measured 3 to 6 Hd upstream of the crest"),
    ]  # fmt: skip


def _basin_checks(st, long, sm) -> list[Check]:
    kind = int(sm.value(st, "basin_type"))
    y1, froude = sm.value(st, "y1"), sm.value(st, "froude")
    design = sm.basin_design(y1, froude, kind)
    y2, end = design["y2"], st.station + design["length"]
    x, depth = long.chainage, long.hydraulic_depth
    checks = []
    after = (x > end + 0.1 * design["length"]) & long.wet
    if after.sum() >= 2:
        measured = float(np.nanmean(depth[after]))
        checks.append(Check("Depth leaving the basin (Bélanger sequent depth)", f"y2 = {num(y2, 'm', 3)}",
                            f"{num(measured, 'm', 3)} ({_percent(measured, y2)})",
                            _verdict(measured, y2, 0.05, 0.12)))  # fmt: skip
    reached = x[(x > st.station) & (depth >= 0.9 * y2)]
    if len(reached):
        length = float(reached[0] - st.station)
        checks.append(Check(f"The jump is held in the basin (USBR type {kind})",
                            f"within the basin, {num(design['length'], 'm', 3)} = {design['length'] / y2:.2g} y2",
                            f"0.9 y2 reached {num(length, 'm', 3)} from its start ({length / y2:.2g} y2)",
                            OK if length <= 1.05 * design["length"]
                            else LOOK if length <= 1.3 * design["length"] else FAIL))  # fmt: skip
    return checks


def normal_depth(project: Project, discharge: float, n: float) -> float | None:
    """The depth at which the discharge flows uniformly in the channel (Manning), or None."""
    from easyfoam.channel import wetted

    ch = project.channel
    if ch is None or ch.slope <= 0 or n <= 0 or discharge <= 0:
        return None

    def carried(depth: float) -> float:
        area, perimeter = wetted(ch, depth)
        return area * (area / perimeter) ** (2 / 3) * math.sqrt(ch.slope) / n if perimeter > 0 else 0.0

    low, high = 1e-6, max(10.0, 10 * ch.depth)
    if carried(high) < discharge:
        return None
    for _ in range(80):
        middle = 0.5 * (low + high)
        low, high = (middle, high) if carried(middle) < discharge else (low, middle)
    return 0.5 * (low + high)


def _channel_checks(project: Project, long) -> list[Check]:
    from easyfoam.model import manning_from_ks, roughness_height

    bed = next((b for name, b in project.boundaries.items() if name == "bed"), None)
    if bed is None:
        return []
    ks = roughness_height(bed)
    n = bed.manning if bed.roughness == "manning" and bed.manning > 0 else manning_from_ks(ks)
    order = long.flow_order()
    if n <= 0 or order.size < 6:
        return []
    middle = order[len(order) // 3: 2 * len(order) // 3]
    q = float(np.nanmean(np.abs(long.discharge[middle])))
    depth = float(np.nanmean(long.depth[middle]))
    expected = normal_depth(project, q, n)
    if expected is None:
        return []
    return [Check("Depth in the middle third against uniform flow (Manning)", f"normal depth {num(expected, 'm', 3)} "
                  f"for Q = {num(q, 'm³/s')}, n = {n:.3g}, S = {project.channel.slope:g}",
                  f"{num(depth, 'm', 3)} ({_percent(depth, expected)})",
                  _verdict(depth, expected, 0.10, 0.25) if not any(s.kind == "bend" for s in project.channel.segments)
                  else INFO,
                  "uniform flow needs a long, straight reach; bends and the ends change the depth")]  # fmt: skip


# --- the whole report -------------------------------------------------------------------------------------------


def build(project: Project, case_dir: Path | None, runtime: str = "", figures: Sequence[Figure] = (),
          long=None, rating=None) -> Report:  # fmt: skip
    """Everything about a project and its last run, ready to be written out."""
    case_dir = Path(case_dir) if case_dir else None
    parser = read_log(project, case_dir)
    spec = SOLVERS.get(project.physics.solver)
    facts = [
        ("Project", project.name),
        ("Folder", str(case_dir) if case_dir else "—"),
        ("Written", dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Flow type", spec.label if spec else project.physics.solver),
        ("Programs", f"EasyFOAM {__version__}" + (f", OpenFOAM {runtime}" if runtime else "")),
    ]
    results = results_section(project, case_dir, long, rating)
    results.figures += list(figures)
    sections = [setup_section(project), geometry_section(project, case_dir), mesh_section(project, case_dir),
                boundary_section(project, case_dir), run_section(project, parser), results]  # fmt: skip
    checks = run_checks(project, parser, case_dir) + continuity_checks(project, case_dir, long) + hydraulic_checks(project, long)
    return Report(f"{project.name}: simulation report", facts, sections, checks)


# --- writing it out ---------------------------------------------------------------------------------------------

CSS = """
body { font-family: "Segoe UI", system-ui, -apple-system, Helvetica, Arial, sans-serif; color: #1f2933; margin: 0;
       background: #f3f5f8; line-height: 1.45; }
main { max-width: 980px; margin: 28px auto; background: white; padding: 36px 44px; border-radius: 10px;
       box-shadow: 0 1px 3px rgba(15, 23, 42, .12); }
h1 { font-size: 26px; margin: 0 0 6px; } h2 { font-size: 19px; margin: 30px 0 10px; color: #1d4ed8;
     border-bottom: 1px solid #dde2e8; padding-bottom: 4px; } h3 { font-size: 14px; margin: 18px 0 6px; color: #334155; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 12px; font-size: 13px; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid #e5e9ef; vertical-align: top; }
th { background: #f3f5f8; font-weight: 600; }
table.facts td:first-child, table.pairs td:first-child { width: 34%; color: #475569; }
p { margin: 6px 0; font-size: 14px; } p.note { color: #64748b; font-size: 12.5px; }
figure { margin: 14px 0 18px; } figure img { max-width: 100%; border: 1px solid #dde2e8; border-radius: 6px; }
figcaption { font-size: 12.5px; color: #64748b; margin-top: 4px; }
.verdict { font-weight: 600; white-space: nowrap; } .ok { color: #15803d; } .look { color: #b45309; } .fail { color: #b91c1c; }
.info { color: #475569; } .summary { display: flex; gap: 10px; margin: 10px 0 4px; flex-wrap: wrap; }
.summary span { padding: 3px 10px; border-radius: 12px; font-size: 13px; background: #f3f5f8; }
@media print { body { background: white; } main { box-shadow: none; margin: 0; max-width: none; padding: 0; }
               h2 { break-after: avoid; } figure, table { break-inside: avoid; } }
"""


def _table(table: Table, pairs: bool = False) -> str:
    head = "" if pairs else "<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in table.header) + "</tr>"
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in table.rows)
    title = f"<h3>{html.escape(table.title)}</h3>" if table.title else ""
    kind = ' class="pairs"' if pairs else ""
    return f"{title}<table{kind}>{head}{body}</table>"


def render_html(report: Report) -> str:
    """The report as a web page that holds everything, pictures included."""
    parts = [f"<h1>{html.escape(report.title)}</h1>"]
    facts = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>" for k, v in report.facts)
    parts.append(f'<table class="facts">{facts}</table>')
    if report.checks:
        counts = {v: sum(c.verdict == v for c in report.checks) for v in VERDICT_WORDS}
        badges = "".join(f'<span class="{v}">{html.escape(VERDICT_WORDS[v])}: {n}</span>' for v, n in counts.items() if n)
        parts.append(f'<h2>Checked against theory</h2><div class="summary">{badges}</div>')
        rows = "".join(
            f"<tr><td>{html.escape(c.what)}" + (f'<br><span class="info">{html.escape(c.note)}</span>' if c.note else "")
            + f"</td><td>{html.escape(c.theory)}</td><td>{html.escape(c.found)}</td>"
            f'<td class="verdict {c.verdict}">{html.escape(VERDICT_WORDS[c.verdict])}</td></tr>'
            for c in report.checks
        )  # fmt: skip
        parts.append(f"<table><tr><th>Check</th><th>Theory or set-up</th><th>This run</th><th></th></tr>{rows}</table>")
        parts.append('<p class="note">The checks compare the results with textbook formulas and with what was set '
                     "up. They point out what to look at; they do not certify a design.</p>")  # fmt: skip
    number = 0
    for section in report.sections:
        parts.append(f"<h2>{html.escape(section.title)}</h2>")
        for line in section.text:
            parts.append(f"<p>{html.escape(line)}</p>")
        for table in section.tables:
            parts.append(_table(table, pairs=table.header == ["", ""]))
        for figure in section.figures:
            number += 1
            source = "data:image/png;base64," + base64.b64encode(figure.png).decode("ascii")
            caption = f"Figure {number}. {figure.title}" + (f" — {figure.caption}" if figure.caption else "")
            parts.append(f'<figure><img src="{source}" alt="{html.escape(figure.title, quote=True)}">'
                         f"<figcaption>{html.escape(caption)}</figcaption></figure>")  # fmt: skip
    parts.append(f'<p class="note">Written by EasyFOAM {html.escape(__version__)}.</p>')
    body = "\n".join(parts)
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{html.escape(report.title)}</title>'
            f"<style>{CSS}</style></head><body><main>\n{body}\n</main></body></html>\n")  # fmt: skip


def write_html(report: Report, path: Path) -> Path:
    path = Path(path)
    path.write_text(render_html(report), encoding="utf-8")
    return path


PRINT_CSS = """
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; color: #1f2933; }
h1 { font-size: 18pt; margin-bottom: 4pt; } h2 { font-size: 13pt; color: #1d4ed8; margin-top: 16pt; margin-bottom: 4pt; }
h3 { font-size: 10.5pt; color: #334155; margin-top: 10pt; margin-bottom: 2pt; }
p { font-size: 10pt; margin-top: 3pt; margin-bottom: 3pt; } td, th { font-size: 9pt; }
.note { color: #64748b; font-size: 8.5pt; } .caption { color: #64748b; font-size: 8.5pt; }
"""
NEWLINE = "\n"
_PRINT_COLOURS = {OK: "#15803d", LOOK: "#b45309", FAIL: "#b91c1c", INFO: "#475569"}


def _print_table(header: Sequence[str], rows: Sequence[Sequence[str]], pairs: bool = False) -> str:
    cells = "" if pairs else "<tr>" + "".join(f'<th align="left" bgcolor="#eef2f7">{h}</th>' for h in header) + "</tr>"
    for row in rows:
        cells += "<tr>" + "".join(
            f'<td{" width=34%" if pairs and i == 0 else ""}>{c}</td>' for i, c in enumerate(row)) + "</tr>"
    return (f'<table width="100%" border="1" cellspacing="0" cellpadding="4" style="border-color: #d5dbe3; '
            f'border-style: solid;">{cells}</table>')  # fmt: skip


def render_print_html(report: Report) -> str:
    """The report as a page for Qt's PDF writer, which reads simpler pages than a browser; the pictures are
    resources named figure-1.png, figure-2.png ..."""
    esc = html.escape
    parts = [f"<h1>{esc(report.title)}</h1>", _print_table([], [[esc(k), esc(v)] for k, v in report.facts], pairs=True)]
    if report.checks:
        counts = {v: sum(c.verdict == v for c in report.checks) for v in VERDICT_WORDS}
        summary = " · ".join(f'<span style="color: {_PRINT_COLOURS[v]};">{esc(VERDICT_WORDS[v])}: {n}</span>'
                             for v, n in counts.items() if n)  # fmt: skip
        parts.append(f"<h2>Checked against theory</h2><p>{summary}</p>")
        rows = [[esc(c.what) + (f'<br><span class="note">{esc(c.note)}</span>' if c.note else ""), esc(c.theory),
                 esc(c.found), f'<b style="color: {_PRINT_COLOURS[c.verdict]};">{esc(VERDICT_WORDS[c.verdict])}</b>']
                for c in report.checks]  # fmt: skip
        parts.append(_print_table(["Check", "Theory or set-up", "This run", ""], rows))
        parts.append('<p class="note">The checks compare the results with textbook formulas and with what was set '
                     "up. They point out what to look at; they do not certify a design.</p>")  # fmt: skip
    number = 0
    for section in report.sections:
        parts.append(f"<h2>{esc(section.title)}</h2>")
        parts += [f"<p>{esc(line)}</p>" for line in section.text]
        for table in section.tables:
            if table.title:
                parts.append(f"<h3>{esc(table.title)}</h3>")
            pairs = table.header == ["", ""]
            parts.append(_print_table([esc(h) for h in table.header],
                                      [[esc(str(c)) for c in row] for row in table.rows], pairs))  # fmt: skip
        for figure in section.figures:
            number += 1
            caption = f"Figure {number}. {figure.title}" + (f" — {figure.caption}" if figure.caption else "")
            parts.append(f'<p><img src="figure-{number}.png" width="600"></p><p class="caption">{esc(caption)}</p>')
    parts.append(f'<p class="note">Written by EasyFOAM {esc(__version__)}.</p>')
    return "<html><body>" + NEWLINE.join(parts) + "</body></html>"


def write_pdf(report: Report, path: Path) -> Path:
    """The report as an A4 PDF (needs Qt's GUI module)."""
    from PySide6.QtCore import QMarginsF, QUrl
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

    path = Path(path)
    document = QTextDocument()
    document.setDefaultStyleSheet(PRINT_CSS)
    figures = [f for s in report.sections for f in s.figures]
    for number, figure in enumerate(figures, start=1):
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(f"figure-{number}.png"),
                             QImage.fromData(figure.png, "PNG"))  # fmt: skip
    document.setHtml(render_print_html(report))
    writer = QPdfWriter(str(path))
    writer.setResolution(96)  # lengths in pixels mean what they mean on the screen
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setTitle(report.title)
    writer.setCreator(f"EasyFOAM {__version__}")
    document.print_(writer)
    return path


def write(report: Report, path: Path) -> Path:
    """Save the report: a PDF if the name ends in .pdf, otherwise a web page."""
    path = Path(path)
    return write_pdf(report, path) if path.suffix.lower() == ".pdf" else write_html(report, path)
