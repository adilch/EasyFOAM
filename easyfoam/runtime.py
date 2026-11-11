"""Where OpenFOAM lives and how to launch it.

A :class:`Runtime` describes one OpenFOAM installation (inside WSL on Windows,
or native on Linux).  Work is always launched as a generated bash script kept
in ``<case>/.easyfoam/`` so that exactly what ran can be inspected and re-run
by hand.  Scripts print ``@@EASYFOAM ...`` marker lines the runner understands.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath

MARK = "@@EASYFOAM"

#: glob patterns (bash) for the environment script of common OpenFOAM installs
BASHRC_GLOBS = (
    "/usr/lib/openfoam/openfoam*/etc/bashrc",  # openfoam.com packages
    "/opt/openfoam*/etc/bashrc",  # openfoam.org packages
    "/opt/OpenFOAM/OpenFOAM-*/etc/bashrc",
    "$HOME/OpenFOAM/OpenFOAM-*/etc/bashrc",  # source builds
)


@dataclass(frozen=True)
class Step:
    """One command of a run; its output is also kept in ``log.<name>``."""

    name: str
    command: str


@dataclass(frozen=True)
class Runtime:
    kind: str  # "wsl" or "posix"
    label: str
    bashrc: str
    distro: str = ""

    def _prefix(self) -> list[str]:
        return ["wsl.exe", "-d", self.distro, "--"] if self.kind == "wsl" else []

    def case_path(self, path: PurePath) -> str:
        """The path as OpenFOAM sees it."""
        if self.kind == "wsl":
            return windows_to_wsl_path(PureWindowsPath(path))
        return str(path)

    def argv(self, script: PurePath) -> list[str]:
        """Command line that runs a generated script in its own session."""
        return [*self._prefix(), "setsid", "-w", "bash", self.case_path(script)]

    def kill_argv(self, pid: int) -> list[str]:
        """Command line that kills every process of a running script."""
        return [*self._prefix(), "pkill", "-KILL", "-s", str(pid)]

    def to_json(self) -> dict:
        return {"kind": self.kind, "label": self.label, "bashrc": self.bashrc, "distro": self.distro}

    @classmethod
    def from_json(cls, data: dict) -> Runtime:
        return cls(data["kind"], data.get("label", ""), data["bashrc"], data.get("distro", ""))


def windows_to_wsl_path(path: PureWindowsPath) -> str:
    drive = path.drive
    rest = "/".join(path.parts[1:])
    if drive.startswith("\\\\"):  # \\wsl.localhost\<distro>\home\... or \\wsl$\<distro>\...
        return "/" + rest
    return f"/mnt/{drive[0].lower()}/{rest}"


def parse_wsl_distros(raw: bytes) -> list[str]:
    """Decode the UTF-16 output of ``wsl.exe -l -q``."""
    text = raw.decode("utf-16-le", errors="replace").replace("\ufeff", "")
    return [line.strip() for line in text.splitlines() if line.strip()]


def runtimes_from_bashrc_paths(kind: str, paths: Iterable[str], distro: str = "") -> list[Runtime]:
    where = f"WSL: {distro}" if kind == "wsl" else "this computer"
    found = []
    for bashrc in (p.strip() for p in paths):
        if not bashrc:
            continue
        name = PurePath(bashrc.replace("\\", "/")).parent.parent.name
        found.append(Runtime(kind, f"{name} ({where})", bashrc, distro))
    return found


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def detect_runtimes(timeout: float = 20.0) -> list[Runtime]:
    """Find OpenFOAM installations on this machine (never raises)."""
    probe = "ls -d " + " ".join(BASHRC_GLOBS) + " 2>/dev/null"
    found: list[Runtime] = []
    try:
        if sys.platform == "win32":
            listing = subprocess.run(
                ["wsl.exe", "-l", "-q"], capture_output=True, timeout=timeout, **_no_window()
            )
            for distro in parse_wsl_distros(listing.stdout):
                if distro.startswith("docker-desktop"):
                    continue
                out = subprocess.run(
                    ["wsl.exe", "-d", distro, "--", "bash", "-c", probe],
                    capture_output=True, text=True, timeout=timeout, **_no_window(),
                )  # fmt: skip
                found += runtimes_from_bashrc_paths("wsl", out.stdout.splitlines(), distro)
        else:
            out = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, timeout=timeout)
            found += runtimes_from_bashrc_paths("posix", out.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        pass
    return found


def render_script(bashrc: str, case_path: str, steps: Sequence[Step]) -> str:
    """Bash script that runs the steps in order and stops at the first failure."""
    lines = [
        "#!/bin/bash",
        f'echo "{MARK} pid $$"',
        f"source {bashrc}",
        f'cd "{case_path}" || exit 97',
    ]
    for step in steps:
        lines += [
            f'echo "{MARK} step {step.name}"',
            f"{step.command} 2>&1 | tee log.{step.name}",
            f'rc=${{PIPESTATUS[0]}}; if [ "$rc" -ne 0 ]; then echo "{MARK} failed {step.name} $rc"; exit "$rc"; fi',
        ]
    lines.append(f'echo "{MARK} done"')
    return "\n".join(lines) + "\n"


def write_script(case_dir: Path, name: str, runtime: Runtime, steps: Sequence[Step]) -> Path:
    folder = Path(case_dir) / ".easyfoam"
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / f"{name}.sh"
    text = render_script(runtime.bashrc, runtime.case_path(Path(case_dir).resolve()), steps)
    script.write_bytes(text.encode("utf-8"))  # bytes: keep LF endings on Windows
    return script


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, **_no_window()
        )
    else:
        proc.kill()


def stream_process(
    argv: Sequence[str],
    on_line: Callable[[str], None],
    stop_event: threading.Event | None = None,
    on_stop: Callable[[], None] | None = None,
    cwd: os.PathLike | None = None,
) -> int:
    """Run a process, hand each output line to ``on_line`` and return its exit code.

    Setting ``stop_event`` from another thread calls ``on_stop`` (if given) and
    then kills the process tree.
    """
    proc = subprocess.Popen(
        list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=cwd, **_no_window(),
    )  # fmt: skip

    def watch() -> None:
        while proc.poll() is None:
            if stop_event.wait(0.2):
                if on_stop is not None:
                    try:
                        on_stop()
                    except Exception:  # stopping must not fail because cleanup did
                        pass
                _kill_tree(proc)
                return

    if stop_event is not None:
        threading.Thread(target=watch, daemon=True).start()

    assert proc.stdout is not None
    for line in proc.stdout:
        on_line(line.rstrip("\r\n"))
    proc.stdout.close()
    return proc.wait()
