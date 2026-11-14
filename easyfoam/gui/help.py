"""The tutorial that explains the step on screen, for the "?" button of each step.

The tutorials website (``docs/``) comes with an index of its tutorials and of the first step of each that shows
a workflow step; the tutorial chosen is the one closest to the project open: a river reach for terrain, the
stilling basin for a basin, the contact tank for tracers, and so on.
"""

from __future__ import annotations

import json
import tempfile
from functools import cache
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"

#: tutorials that suit a kind of project, closest first
FOR_KIND: dict[str, tuple[str, ...]] = {
    "terrain": ("reach", "flood", "channel"),
    "channel": ("channel", "flood", "jump"),
    "basin": ("basin", "jump"),
    "structure": ("ogee", "spillway", "weir"),
    "tracers": ("tank",),
    "moving": ("floating", "gate"),
    "waves": ("waves",),
    "free surface": ("weir", "spillway", "dambreak", "draw-shapes"),
    "single fluid": ("sphere", "pipe", "cavity"),
}
FALLBACK = ("weir", "sphere", "cavity", "draw-shapes", "getting-started")


@cache
def _index(docs: Path = DOCS) -> tuple[dict, ...]:
    try:
        return tuple(json.loads((docs / "tutorials" / "index.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ()


def project_kinds(project) -> list[str]:
    """What kind of project it is, most telling first."""
    if project is None:
        return []
    from easyfoam.solvers import solver_spec

    kinds = []
    structures = [s.structure.kind for s in project.shapes if getattr(s, "structure", None) is not None]
    if any(s.name == "terrain" for s in project.shapes):
        kinds.append("terrain")
    if getattr(project, "channel", None) is not None:
        kinds.append("channel")
    if "basin" in structures:
        kinds.append("basin")
    if structures:
        kinds.append("structure")
    if project.tracers:
        kinds.append("tracers")
    if any(s.motion.kind != "none" for s in project.shapes):
        kinds.append("moving")
    if any(b.kind in ("waveInlet", "waveOutlet") for b in project.boundaries.values()):
        kinds.append("waves")
    kinds.append("free surface" if solver_spec(project.physics.solver).multiphase else "single fluid")
    return kinds


def tutorial_for(project, step: str, docs: Path = DOCS) -> tuple[Path, int, str] | None:
    """The tutorial page that shows ``step`` for a project like this one: (page, step number, title), or None."""
    tutorials = {t["slug"]: t for t in _index(docs)}
    candidates = [slug for kind in project_kinds(project) for slug in FOR_KIND.get(kind, ())] + list(FALLBACK)
    for slug in candidates:
        tutorial = tutorials.get(slug)
        if tutorial is None or step not in tutorial.get("steps", {}):
            continue
        page = docs / "tutorials" / f"{slug}.html"
        if page.is_file():
            return page, int(tutorial["steps"][step]), tutorial["title"]
    return None


def opener(page: Path, number: int) -> Path:
    """A small local page that forwards to the step of the tutorial.

    Opening a file with ``#step-5`` straight away loses the ``#step-5`` on Windows; a page that forwards to it keeps
    it, in every browser.
    """
    target = page.resolve().as_uri() + f"#step-{number}"
    forward = Path(tempfile.gettempdir()) / "easyfoam-tutorial.html"
    forward.write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>EasyFOAM tutorial</title>"
        f"<meta http-equiv=\"refresh\" content=\"0; url={target}\">"
        f"<script>location.replace({json.dumps(target)})</script>"
        f"<p><a href=\"{target}\">Open the tutorial</a></p>",
        encoding="utf-8",
    )
    return forward
