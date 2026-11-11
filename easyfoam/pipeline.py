"""Run meshing and solving for a case and report what happens.

``prepare_mesh`` / ``prepare_run`` write the case files and return the steps;
a :class:`Job` executes steps through a runtime and can be stopped.  Nothing
here depends on the GUI, so the command line and the tests use the same code.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from easyfoam import casegen
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.foam.logparser import LogParser
from easyfoam.model import Project
from easyfoam.runtime import MARK, Runtime, Step, detect_runtimes, stream_process, write_script

LineSink = Callable[[str], None]


class StepTracker:
    """Understands the ``@@EASYFOAM`` marker lines printed by generated scripts."""

    def __init__(
        self,
        on_line: LineSink | None = None,
        on_step: LineSink | None = None,
        parse_step: str | None = None,
    ) -> None:
        self.on_line = on_line
        self.on_step = on_step
        self.parse_step = parse_step
        self.parser = LogParser()
        self.pid: int | None = None
        self.current: str | None = None
        self.failed_step: str | None = None
        self.done = False

    def feed(self, line: str) -> None:
        if line.startswith(MARK):
            words = line.split()
            kind = words[1] if len(words) > 1 else ""
            if kind == "pid" and len(words) > 2 and words[2].isdigit():
                self.pid = int(words[2])
            elif kind == "step" and len(words) > 2:
                self.current = words[2]
                if self.on_step:
                    self.on_step(self.current)
            elif kind == "failed" and len(words) > 2:
                self.failed_step = words[2]
            elif kind == "done":
                self.done = True
            return
        if self.parse_step is not None and self.current == self.parse_step:
            self.parser.feed(line)
        if self.on_line:
            self.on_line(line)


@dataclass
class JobResult:
    ok: bool
    exit_code: int
    failed_step: str | None
    stopped: bool
    parser: LogParser


class Job:
    """A sequence of steps running in a runtime (blocking ``run``, thread-safe ``stop``)."""

    def __init__(
        self,
        case_dir: Path,
        runtime: Runtime,
        name: str,
        steps: Sequence[Step],
        on_line: LineSink | None = None,
        on_step: LineSink | None = None,
        parse_step: str | None = None,
    ) -> None:
        self.case_dir = Path(case_dir)
        self.runtime = runtime
        self.name = name
        self.steps = list(steps)
        self.tracker = StepTracker(on_line, on_step, parse_step)
        self._stop = threading.Event()

    @property
    def parser(self) -> LogParser:
        return self.tracker.parser

    def stop(self) -> None:
        self._stop.set()

    def _kill_session(self) -> None:
        if self.tracker.pid is not None:
            subprocess.run(self.runtime.kill_argv(self.tracker.pid), capture_output=True, timeout=20)

    def run(self) -> JobResult:
        script = write_script(self.case_dir, self.name, self.runtime, self.steps)
        code = stream_process(
            self.runtime.argv(script.resolve()), self.tracker.feed, self._stop, self._kill_session
        )
        stopped = self._stop.is_set()
        ok = code == 0 and self.tracker.done and not stopped
        return JobResult(ok, code, self.tracker.failed_step, stopped, self.tracker.parser)


def runtime_for(project: Project) -> Runtime:
    """The runtime saved in the project, or the first one found on this machine."""
    if project.runtime:
        return Runtime.from_json(project.runtime)
    found = detect_runtimes()
    if not found:
        raise RuntimeError(
            "No OpenFOAM installation was found. On Windows install OpenFOAM inside WSL "
            "(see the README), on Linux install an openfoam package."
        )
    return found[0]


def prepare_mesh(case_dir: Path, project: Project) -> list[Step]:
    """Remove the old mesh, write the meshing dictionaries, return the steps to run."""
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    casegen.clean_mesh(case_dir)
    casegen.write_files(case_dir, casegen.mesh_files(project, case_dir))
    return casegen.mesh_steps(project)


def post_steps_for(case_dir: Path, project: Project, function: str) -> list[Step]:
    """Steps that compute a derived quantity (y+, …) for the latest saved result."""
    case_dir = Path(case_dir)
    computed = [d for d in case_dir.iterdir() if casegen._is_time_dir(d) and d.name != "0"]
    if not computed:
        raise RuntimeError("There are no results yet - run the simulation first.")
    return casegen.post_steps(project, function)


def prepare_run(case_dir: Path, project: Project) -> list[Step]:
    """Remove old results, write the solver set-up for the current mesh, return the steps."""
    case_dir = Path(case_dir)
    patches = read_boundary(case_dir)
    if not patches:
        raise RuntimeError("There is no mesh yet - generate the mesh before running the solver.")
    casegen.clean_results(case_dir)
    casegen.write_files(case_dir, casegen.setup_files(project, patches))
    return casegen.run_steps(project)
