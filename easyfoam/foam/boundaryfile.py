"""Read ``constant/polyMesh/boundary`` - the list of mesh patches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_HEADER = re.compile(r"FoamFile\s*\{[^}]*\}", re.S)
_PATCH = re.compile(r"([A-Za-z_][\w.:-]*)\s*\{([^{}]*)\}", re.S)


@dataclass(frozen=True)
class Patch:
    name: str
    type: str
    n_faces: int
    start_face: int


def _entry(body: str, key: str, default: str = "") -> str:
    m = re.search(rf"\b{key}\s+([^;]+);", body)
    return m.group(1).strip() if m else default


def parse_boundary(text: str) -> list[Patch]:
    text = _HEADER.sub("", _COMMENT.sub("", text), count=1)
    return [
        Patch(
            name=m.group(1),
            type=_entry(m.group(2), "type", "patch"),
            n_faces=int(_entry(m.group(2), "nFaces", "0")),
            start_face=int(_entry(m.group(2), "startFace", "0")),
        )
        for m in _PATCH.finditer(text)
    ]


def read_boundary(case_dir: Path) -> list[Patch]:
    """Patches of the case's mesh, or an empty list when there is no mesh yet."""
    path = Path(case_dir) / "constant" / "polyMesh" / "boundary"
    if not path.is_file():
        return []
    return parse_boundary(path.read_text(encoding="utf-8", errors="replace"))
