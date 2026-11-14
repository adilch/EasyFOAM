"""Small things the application remembers between sessions (recent projects)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from easyfoam.model import PROJECT_FILE

MAX_RECENT = 8


def state_file() -> Path:
    override = os.environ.get("EASYFOAM_STATE_FILE")
    return Path(override) if override else Path.home() / ".easyfoam" / "state.json"


def _read() -> dict:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    try:
        path = state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # remembering is a convenience; never fail because of it


def load_recent() -> list[str]:
    """Recently opened project folders that still exist, newest first."""
    return [p for p in _read().get("recent", []) if (Path(p) / PROJECT_FILE).is_file()]


def add_recent(folder: os.PathLike | str) -> list[str]:
    folder = str(Path(folder).resolve())
    data = _read()
    others = [p for p in data.get("recent", []) if os.path.normcase(p) != os.path.normcase(folder)]
    data["recent"] = [folder, *others][:MAX_RECENT]
    _write(data)
    return load_recent()


def projects_folder() -> Path:
    """Where new projects are created by default."""
    saved = _read().get("projects_folder")
    return Path(saved) if saved else Path.home() / "Documents" / "EasyFOAM"


def remember_projects_folder(folder: os.PathLike | str) -> None:
    data = _read()
    data["projects_folder"] = str(folder)
    _write(data)


def load_layout() -> dict:
    """How the panels of the main window were arranged last time (empty if never saved)."""
    layout = _read().get("layout")
    return layout if isinstance(layout, dict) else {}


def save_layout(layout: dict) -> None:
    data = _read()
    data["layout"] = layout
    _write(data)
