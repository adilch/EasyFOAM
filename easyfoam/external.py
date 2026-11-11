"""Finding and launching companion programs (ParaView)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path


def _default_roots() -> list[Path]:
    if sys.platform == "win32":
        return [Path(os.environ.get(v, "")) for v in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(v)]
    return [Path("/opt"), Path("/usr/local"), Path("/Applications")]


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", path.parts[-3]))


def find_paraview(
    search_roots: Iterable[Path] | None = None,
    on_path: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """The newest installed ParaView, or the one on PATH, or ``None``."""
    exe = "paraview.exe" if sys.platform == "win32" else "paraview"
    candidates: list[Path] = []
    for root in _default_roots() if search_roots is None else search_roots:
        if Path(root).is_dir():
            candidates += [p for p in Path(root).glob(f"ParaView*/bin/{exe}") if p.is_file()]
    if candidates:
        return max(candidates, key=_version_key)
    found = on_path("paraview")
    return Path(found) if found else None


def open_in_paraview(foam_file: Path) -> bool:
    """Start ParaView on a case; returns False when ParaView is not installed."""
    exe = find_paraview()
    if exe is None:
        return False
    Path(foam_file).touch(exist_ok=True)
    subprocess.Popen([str(exe), str(foam_file)], cwd=str(Path(foam_file).parent))
    return True
