"""Command line: the same operations as the GUI, scriptable.

    easyfoam runtimes                 list OpenFOAM installations found
    easyfoam new CASE [--example X]   create a project folder
    easyfoam import-stl CASE FILE     add an STL surface
    easyfoam write CASE               write the meshing dictionaries only
    easyfoam mesh CASE                generate the mesh
    easyfoam run CASE [--np N]        run the solver
    easyfoam info CASE                show mesh patches and saved times
    easyfoam long-section CASE        water level, energy line, Froude number along the channel
    easyfoam pressure CASE WALL       pressure head along a structure
    easyfoam loads CASE WALL...       force and overturning moment of the water on structures
    easyfoam channel CASE [--piece..] build an open channel: section, bed slope, pieces and bends
    easyfoam terrain CASE FILE        flow over the ground of a survey (XYZ, ASC, GeoTIFF, LandXML)
    easyfoam gui [CASE]               open the desktop application
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from easyfoam import __version__, casegen
from easyfoam.examples import EXAMPLES
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.geometry import UNITS, fit_base_mesh, import_geometry
from easyfoam.model import PROJECT_FILE, Project
from easyfoam.pipeline import Job, prepare_mesh, prepare_run, runtime_for
from easyfoam.runtime import detect_runtimes


class CliError(Exception):
    pass


def _load(case: Path) -> Project:
    if not (case / PROJECT_FILE).is_file():
        raise CliError(f"{case} is not an EasyFOAM project (no {PROJECT_FILE}); create one with 'easyfoam new'")
    return Project.load(case)


def _run_job(case: Path, project: Project, name: str, steps, parse_step=None) -> int:
    runtime = runtime_for(project)
    print(f"[easyfoam] using {runtime.label}")
    job = Job(case, runtime, name, steps, on_line=print,
              on_step=lambda s: print(f"[easyfoam] --- {s} ---"), parse_step=parse_step)  # fmt: skip
    try:
        result = job.run()
    except KeyboardInterrupt:
        job.stop()
        print("[easyfoam] stopped")
        return 130
    if result.ok:
        print(f"[easyfoam] {name} finished")
        return 0
    print(f"[easyfoam] {name} FAILED in step '{result.failed_step}' (exit code {result.exit_code})",
          file=sys.stderr)  # fmt: skip
    return 1


def cmd_runtimes(args) -> int:
    found = detect_runtimes()
    for rt in found:
        print(f"{rt.label}\n    {rt.bashrc}")
    if not found:
        print("No OpenFOAM installation found.")
    return 0


def cmd_new(args) -> int:
    case = Path(args.case)
    if (case / PROJECT_FILE).exists():
        raise CliError(f"{case} already contains an EasyFOAM project")
    project = EXAMPLES[args.example](args.name or case.name)
    path = project.save(case)
    print(f"Created project '{project.name}' ({args.example}) in {path.parent}")
    return 0


def cmd_import_stl(args) -> int:
    case = Path(args.case)
    project = _load(case)
    shape = import_geometry(case, Path(args.file), args.name, args.unit)
    project.shapes = [s for s in project.shapes if s.name != shape.name] + [shape]
    if args.fit:
        fit_base_mesh(project, case)
    project.save(case)
    print(f"Added surface '{shape.name}'")
    return 0


def cmd_write(args) -> int:
    case = Path(args.case)
    project = _load(case)
    for path in casegen.write_files(case, casegen.mesh_files(project, case)):
        print(path)
    return 0


def cmd_mesh(args) -> int:
    case = Path(args.case)
    project = _load(case)
    return _run_job(case, project, "mesh", prepare_mesh(case, project))


def cmd_run(args) -> int:
    case = Path(args.case)
    project = _load(case)
    if args.np:
        project.run.processors = args.np
        project.save(case)
    return _run_job(case, project, "run", prepare_run(case, project), parse_step=project.physics.solver)


def cmd_info(args) -> int:
    case = Path(args.case)
    project = _load(case)
    print(f"Project  : {project.name}")
    print(f"Solver   : {project.physics.solver}, turbulence {project.physics.turbulence}")
    patches = read_boundary(case)
    print("Mesh     : " + ("not generated yet" if not patches else f"{len(patches)} patches"))
    for p in patches:
        print(f"    {p.name:<20} {p.type:<10} {p.n_faces} faces -> {project.boundary_for(p.name, p.type).kind}")
    times = sorted((d.name for d in case.iterdir() if casegen._is_time_dir(d)), key=float)
    print("Times    : " + (", ".join(times) or "none"))
    return 0


def _result(case: Path, project: Project, time: float | None):
    from easyfoam.results import CaseResults

    results = CaseResults(case, project.name)
    if not results.times:
        raise CliError("there are no results yet; run the simulation first")
    chosen = results.times[-1] if time is None else min(results.times, key=lambda t: abs(t - time))
    return results, chosen, results.read(chosen)


def cmd_long_section(args) -> int:
    from easyfoam import hydraulics as hy

    case = Path(args.case)
    project = _load(case)
    results, time, _data = _result(case, project, args.time)
    chosen = [t for t in results.times if 0 < t <= time + 1e-9][-max(1, args.average):] or [time]
    try:
        section = hy.average_sections(
            [hy.long_section(results.read(t), project, case, stations=args.stations, time=t) for t in chosen]
        )
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    when = f"at {time:g} s" if len(chosen) == 1 else f"averaged over {chosen[0]:g} to {chosen[-1]:g} s"
    print(f"Long section {when} ({len(section.chainage)} stations)")
    print(f"{'chainage':>9} {'bed':>8} {'level':>8} {'depth':>7} {'Q m3/s':>9} {'V m/s':>7} {'Fr':>6} {'energy':>8}")
    step = max(1, len(section.chainage) // args.rows)
    for i in range(0, len(section.chainage), step):
        print(f"{section.chainage[i]:9.3f} {section.bed[i]:8.3f} {section.water_level[i]:8.3f} "
              f"{section.hydraulic_depth[i]:7.3f} {section.discharge[i]:9.4g} {section.velocity[i]:7.3f} "
              f"{section.froude[i]:6.2f} {section.energy_level[i]:8.3f}")  # fmt: skip
    print()
    print("\n".join(hy.summary(section)))
    if args.csv:
        section.write_csv(Path(args.csv))
        print(f"\nSaved {args.csv}")
    return 0


def cmd_pressure(args) -> int:
    from easyfoam import hydraulics as hy

    case = Path(args.case)
    project = _load(case)
    _results, time, data = _result(case, project, args.time)
    if args.wall not in data.patches:
        raise CliError(f"there is no boundary called '{args.wall}'; see 'easyfoam info'")
    profile = hy.pressure_profile(data.patches[args.wall], project)
    lowest = int(profile.head.argmin())
    print(f"Pressure along {args.wall} at {time:g} s: from {profile.head.max():.3g} m down to "
          f"{profile.head[lowest]:.3g} m of water (at x = {profile.x[lowest]:.3g} m, z = {profile.z[lowest]:.3g} m)")  # fmt: skip
    if args.csv:
        profile.write_csv(Path(args.csv))
        print(f"Saved {args.csv}")
    return 0


def cmd_loads(args) -> int:
    from easyfoam import hydraulics as hy

    case = Path(args.case)
    project = _load(case)
    _results, time, data = _result(case, project, args.time)
    missing = [w for w in args.walls if w not in data.patches]
    if missing:
        raise CliError(f"no boundary called {', '.join(missing)}; see 'easyfoam info'")
    loads = hy.structure_loads([data.patches[w] for w in args.walls], project, args.about)
    print(f"Loads on {', '.join(args.walls)} at {time:g} s (pressure only):")
    print("\n".join(loads.lines()))
    return 0


def _pieces(texts: list[str]):
    """``straight:LENGTH`` and ``bend:RADIUS:ANGLE`` (degrees, + left, - right) into centreline pieces."""
    from easyfoam.model import ChannelSegment

    pieces = []
    for text in texts:
        parts = text.split(":")
        try:
            if parts[0] == "straight" and len(parts) == 2:
                pieces.append(ChannelSegment("straight", length=float(parts[1])))
            elif parts[0] == "bend" and len(parts) == 3:
                pieces.append(ChannelSegment("bend", radius=float(parts[1]), angle=float(parts[2])))
            else:
                raise ValueError
        except ValueError:
            raise CliError(f"'{text}': give straight:LENGTH or bend:RADIUS:ANGLE") from None
    return pieces


def cmd_channel(args) -> int:
    from easyfoam import channel as chm
    from easyfoam.model import Channel

    case = Path(args.case)
    project = _load(case)
    ch = Channel(section=args.section, bottom_width=args.width, depth=args.depth, side_slope=args.side_slope,
                 berm_width=args.floodplain_width, berm_depth=args.floodplain_depth,
                 berm_slope=args.floodplain_slope, diameter=args.diameter, slope=args.slope,
                 segments=_pieces(args.piece or ["straight:20"]), freeboard=args.freeboard, cell_size=args.cell,
                 water_depth=args.water)  # fmt: skip
    try:
        done = chm.use_channel(project, ch)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    if args.discharge is not None:
        project.boundaries["inlet"].flow_rate = args.discharge
    project.save(case)
    print(f"Built a {ch.section} channel, {chm.total_length(ch):.4g} m long, about {chm.cell_count(ch):,} cells")
    for line in done:
        print(f"  {line}")
    return 0


def cmd_terrain(args) -> int:
    from easyfoam import terrain as tr

    case = Path(args.case)
    project = _load(case)
    try:
        survey = tr.read_survey(Path(args.file))
        origin = tuple(args.origin) if args.origin else tr.default_origin(survey)
        ground = tr.ground(survey, args.spacing or survey.spacing(), origin, args.angle,
                           tuple(args.region) if args.region else None)  # fmt: skip
        done = tr.use_terrain(project, case, ground, args.cell, args.water, args.top, args.discharge)
    except (ValueError, OSError) as exc:
        raise CliError(str(exc)) from exc
    project.save(case)
    print(f"Read {survey.kind}: {len(survey.points):,} points; local origin E {origin[0]:.10g}, N {origin[1]:.10g}")
    for line in done:
        print(f"  {line}")
    return 0


def cmd_gui(args) -> int:
    from easyfoam.gui.app import main as gui_main

    return gui_main([args.case] if args.case else [])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="easyfoam", description=__doc__.split("\n")[0])
    parser.add_argument("--version", action="version", version=f"easyfoam {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("runtimes", help="list OpenFOAM installations").set_defaults(func=cmd_runtimes)

    p = sub.add_parser("new", help="create a project folder")
    p.add_argument("case")
    p.add_argument("--name")
    p.add_argument("--example", choices=sorted(EXAMPLES), default="empty")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("import-stl", help="add an STL (or STEP / IGES) geometry file to the project")
    p.add_argument("case")
    p.add_argument("file")
    p.add_argument("--name")
    p.add_argument("--fit", action="store_true", help="size the base mesh around the geometry")
    p.add_argument("--unit", choices=sorted(UNITS), default="m", help="length unit of the file (default: m)")
    p.set_defaults(func=cmd_import_stl)

    for name, func, text in (
        ("write", cmd_write, "write the meshing dictionaries only"),
        ("mesh", cmd_mesh, "generate the mesh"),
        ("info", cmd_info, "show mesh patches and saved times"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("case")
        p.set_defaults(func=func)

    p = sub.add_parser("run", help="run the solver")
    p.add_argument("case")
    p.add_argument("--np", type=int, help="number of processor cores")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("long-section", help="water level, energy line and Froude number along the channel")
    p.add_argument("case")
    p.add_argument("--time", type=float, help="saved time to use (default: the latest)")
    p.add_argument("--stations", type=int, help="number of stations (default: one per base cell)")
    p.add_argument("--average", type=int, default=1,
                   help="average over this many saved times, ending at --time (for jumps and waves)")  # fmt: skip
    p.add_argument("--rows", type=int, default=20, help="rows to print (default 20)")
    p.add_argument("--csv", help="save every station to this CSV file")
    p.set_defaults(func=cmd_long_section)

    p = sub.add_parser("pressure", help="pressure head along the surface of a structure")
    p.add_argument("case")
    p.add_argument("wall", help="name of the boundary, for example weir")
    p.add_argument("--time", type=float)
    p.add_argument("--csv")
    p.set_defaults(func=cmd_pressure)

    p = sub.add_parser("loads", help="force and overturning moment of the water on structures")
    p.add_argument("case")
    p.add_argument("walls", nargs="+", help="names of the boundaries that make up the structure")
    p.add_argument("--time", type=float)
    p.add_argument("--about", type=float, nargs=3, metavar=("X", "Y", "Z"),
                   help="point for the moments (default: the downstream toe)")  # fmt: skip
    p.set_defaults(func=cmd_loads)

    p = sub.add_parser("channel", help="build an open channel: cross-section, bed slope, straight pieces and bends")
    p.add_argument("case")
    p.add_argument("--section", default="trapezoidal", choices=["rectangular", "trapezoidal", "compound", "circular"])
    p.add_argument("--width", type=float, default=2.0, help="bottom width [m]")
    p.add_argument("--depth", type=float, default=1.0, help="bank height [m]")
    p.add_argument("--side-slope", type=float, default=1.5, help="banks, horizontal per vertical")
    p.add_argument("--floodplain-width", type=float, default=4.0, help="compound: each floodplain [m]")
    p.add_argument("--floodplain-depth", type=float, default=0.6, help="compound: outer bank height [m]")
    p.add_argument("--floodplain-slope", type=float, default=2.0, help="compound: outer banks, H per V")
    p.add_argument("--diameter", type=float, default=1.2, help="circular culvert [m]")
    p.add_argument("--slope", type=float, default=0.001, help="bed slope [m/m]")
    p.add_argument("--piece", action="append", metavar="PIECE",
                   help="straight:LENGTH or bend:RADIUS:ANGLE, from the inlet (repeat; default straight:20)")  # fmt: skip
    p.add_argument("--freeboard", type=float, default=0.3, help="air above the banks [m]")
    p.add_argument("--cell", type=float, default=0.1, help="cell size [m]")
    p.add_argument("--water", type=float, default=0.5, help="initial water depth [m]")
    p.add_argument("--discharge", type=float, help="inflow [m3/s] (default: uniform flow at the initial depth)")
    p.set_defaults(func=cmd_channel)

    p = sub.add_parser("terrain", help="flow over the ground of a survey (XYZ, ESRI ASCII grid, GeoTIFF, LandXML)")
    p.add_argument("case")
    p.add_argument("file", help="the survey file")
    p.add_argument("--spacing", type=float, help="grid spacing of the ground [m] (default: the survey's)")
    p.add_argument("--origin", type=float, nargs=2, metavar=("E", "N"), help="survey point that becomes x = y = 0")
    p.add_argument("--angle", type=float, default=0.0, help="direction the river flows, degrees from east")
    p.add_argument("--region", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), help="part to model, local")
    p.add_argument("--cell", type=float, default=1.0, help="mesh cell size [m]")
    p.add_argument("--water", type=float, help="initial water level [m]")
    p.add_argument("--top", type=float, help="top of the model [m]")
    p.add_argument("--discharge", type=float, default=1.0, help="inflow [m3/s]")
    p.set_defaults(func=cmd_terrain)

    p = sub.add_parser("gui", help="open the desktop application")
    p.add_argument("case", nargs="?")
    p.set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
