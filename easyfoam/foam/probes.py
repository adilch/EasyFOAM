"""Read the time histories written by OpenFOAM's ``probes`` function."""

from __future__ import annotations

import math
import re
from pathlib import Path

_VECTOR = re.compile(r"\(([^()]*)\)")

Series = tuple[list[float], list[list[float]]]  # times, one list of values per probe


def parse_probe_file(text: str) -> Series:
    """Times and one series per probe; vectors are reduced to their magnitude."""
    times: list[float] = []
    rows: list[list[float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)  # any whitespace: OpenFOAM mixes tabs and spaces
        head, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        try:
            time = float(head)
            vectors = _VECTOR.findall(rest)
            if vectors:
                values = [math.sqrt(sum(float(c) ** 2 for c in v.split())) for v in vectors]
            else:
                values = [float(v) for v in rest.split()]
        except ValueError:
            continue  # a line that is still being written
        if values and (not rows or len(values) == len(rows[0])):
            times.append(time)
            rows.append(values)
    probes = len(rows[0]) if rows else 0
    return times, [[row[i] for row in rows] for i in range(probes)]


def _start_time(folder: Path) -> float:
    try:
        return float(folder.name)
    except ValueError:
        return float("inf")


def read_probes(case_dir: Path, name: str = "probes") -> dict[str, Series]:
    """``{field: (times, series per probe)}`` for a case, joined across restarts."""
    root = Path(case_dir) / "postProcessing" / name
    if not root.is_dir():
        return {}
    joined: dict[str, Series] = {}
    for folder in sorted((d for d in root.iterdir() if d.is_dir()), key=_start_time):
        for file in sorted(f for f in folder.iterdir() if f.is_file()):
            try:
                times, series = parse_probe_file(file.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if not times:
                continue
            if file.name not in joined:
                joined[file.name] = (times, series)
            elif len(joined[file.name][1]) == len(series):
                old_times, old_series = joined[file.name]
                joined[file.name] = (old_times + times, [a + b for a, b in zip(old_series, series)])
    return joined
