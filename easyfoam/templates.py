"""Project templates: a set-up of one's own (flow type, boundaries, run settings, shapes) to start new projects from.

A template is a folder holding the project file and the geometry files it uses, under the folder where EasyFOAM
keeps what it remembers (``~/.easyfoam/templates``). No mesh and no results go into it.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from easyfoam.geometry import safe_name
from easyfoam.model import PROJECT_FILE, Project

ABOUT_FILE = "template.json"


@dataclass
class Template:
    name: str
    folder: Path
    description: str = ""


def templates_dir() -> Path:
    override = os.environ.get("EASYFOAM_STATE_FILE")  # next to the state file, so tests keep theirs apart
    base = Path(override).parent if override else Path.home() / ".easyfoam"
    return base / "templates"


def list_templates(folder: Path | None = None) -> list[Template]:
    """The templates saved, by name."""
    folder = folder or templates_dir()
    found = []
    for entry in sorted(folder.glob("*")) if folder.is_dir() else []:
        if not (entry / PROJECT_FILE).is_file():
            continue
        try:
            about = json.loads((entry / ABOUT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            about = {}
        found.append(Template(str(about.get("name") or entry.name), entry, str(about.get("description", ""))))
    return sorted(found, key=lambda t: t.name.lower())


def _geometry_files(project: Project) -> list[str]:
    return sorted({s.file for s in project.shapes if s.kind == "stl" and s.file})


def save_template(project: Project, case_dir: Path, name: str, description: str = "",
                  folder: Path | None = None) -> Template:  # fmt: skip
    """Keep the set-up of a project as a template (one of the same name is replaced)."""
    name = name.strip()
    if not name:
        raise ValueError("the template needs a name")
    target = (folder or templates_dir()) / safe_name(name)
    if target.exists():
        shutil.rmtree(target)
    (target / "constant" / "triSurface").mkdir(parents=True)
    copy = Project.from_dict(project.to_dict())
    copy.runtime = None  # which OpenFOAM runs it belongs to the computer, not to the set-up
    copy.save(target)
    for file in _geometry_files(project):
        source = Path(case_dir) / "constant" / "triSurface" / file
        if source.is_file():
            shutil.copy2(source, target / "constant" / "triSurface" / file)
    about = {"name": name, "description": description, "from": project.name, "saved": time.strftime("%Y-%m-%d")}
    (target / ABOUT_FILE).write_text(json.dumps(about, indent=2), encoding="utf-8")
    return Template(name, target, description)


def create_from_template(template: Template | Path, case_dir: Path, name: str) -> Project:
    """Make a new project in ``case_dir`` from a template."""
    folder = template.folder if isinstance(template, Template) else Path(template)
    if not (folder / PROJECT_FILE).is_file():
        raise ValueError(f"{folder} is not an EasyFOAM template")
    case_dir = Path(case_dir)
    if case_dir.exists() and any(case_dir.iterdir()):
        raise ValueError(f"{case_dir} already exists and is not empty")
    project = Project.load(folder)
    project.name = safe_name(name)
    project.save(case_dir)
    surfaces = folder / "constant" / "triSurface"
    for file in _geometry_files(project):
        if (surfaces / file).is_file():
            (case_dir / "constant" / "triSurface").mkdir(parents=True, exist_ok=True)
            shutil.copy2(surfaces / file, case_dir / "constant" / "triSurface" / file)
    return project
