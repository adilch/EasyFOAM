"""Read the force-coefficient history written by OpenFOAM's ``forceCoeffs`` function."""

from __future__ import annotations

from pathlib import Path


def parse_coefficients(text: str) -> dict[str, list[float]]:
    """Columns of a ``coefficient.dat`` file, keyed by the names in its header line."""
    names: list[str] = []
    rows: list[list[float]] = []
    for line in text.splitlines():
        if line.startswith("#"):
            words = line[1:].split()
            if words and words[0] == "Time":
                names = words
            continue
        try:
            values = [float(v) for v in line.split()]
        except ValueError:
            continue
        if names and len(values) == len(names):  # skips a line that is still being written
            rows.append(values)
    return {name: [row[i] for row in rows] for i, name in enumerate(names)} if rows else {}


def _start_time(folder: Path) -> float:
    try:
        return float(folder.name)
    except ValueError:
        return float("inf")


def read_coefficients(case_dir: Path, name: str = "forceCoeffs") -> dict[str, list[float]]:
    """The whole coefficient history of a case, joined across restarts."""
    root = Path(case_dir) / "postProcessing" / name
    if not root.is_dir():
        return {}
    joined: dict[str, list[float]] = {}
    for folder in sorted((d for d in root.iterdir() if d.is_dir()), key=_start_time):
        file = folder / "coefficient.dat"
        if not file.is_file():
            continue
        try:
            part = parse_coefficients(file.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for key, values in part.items():
            joined.setdefault(key, []).extend(values)
    return joined
