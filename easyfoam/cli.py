"""Command line: the same operations as the GUI, scriptable.

    easyfoam runtimes                 list OpenFOAM installations found
    easyfoam new CASE [--example X]   create a project folder
    easyfoam import-stl CASE FILE     add an STL surface
    easyfoam write CASE               write the meshing dictionaries only
    easyfoam mesh CASE                generate the mesh
    easyfoam run CASE [--np N]        run the solver
    easyfoam info CASE                show mesh patches and saved times
    easyfoam gui [CASE]               open the desktop application
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from easyfoam import __version__, casegen
from easyfoam.examples import EXAMPLES
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.geometry import fit_base_mesh, import_stl
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
    shape = import_stl(case, Path(args.file), args.name)
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

    p = sub.add_parser("import-stl", help="add an STL surface to the project")
    p.add_argument("case")
    p.add_argument("file")
    p.add_argument("--name")
    p.add_argument("--fit", action="store_true", help="size the base mesh around the geometry")
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
