"""Read the histories written by the discharge and water-level monitors."""

from __future__ import annotations

from pathlib import Path

from easyfoam.foam.probes import Series, parse_probe_file

FLOW_PREFIX = "flow_"


def _start_time(folder: Path) -> float:
    try:
        return float(folder.name)
    except ValueError:
        return float("inf")


def _read_joined(root: Path, filename: str) -> Series:
    """One monitor file, joined across the start-time folders of restarted runs."""
    times: list[float] = []
    series: list[list[float]] = []
    if not root.is_dir():
        return times, series
    for folder in sorted((d for d in root.iterdir() if d.is_dir()), key=_start_time):
        try:
            part_times, part = parse_probe_file((folder / filename).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not part_times:
            continue
        if not series:
            times, series = part_times, part
        elif len(part) == len(series):
            times = times + part_times
            series = [a + b for a, b in zip(series, part)]
    return times, series


def read_discharge(case_dir: Path) -> dict[str, tuple[list[float], list[float]]]:
    """``{boundary: (times, volume flow in m3/s)}``; positive means out of the domain."""
    root = Path(case_dir) / "postProcessing"
    found: dict[str, tuple[list[float], list[float]]] = {}
    if not root.is_dir():
        return found
    for folder in sorted(d for d in root.iterdir() if d.is_dir() and d.name.startswith(FLOW_PREFIX)):
        times, series = _read_joined(folder, "surfaceFieldValue.dat")
        if times and series:
            found[folder.name[len(FLOW_PREFIX):]] = (times, series[0])
    return found


def read_water_levels(case_dir: Path) -> Series:
    """Times and, per gauge, the water depth above the bed."""
    times, columns = _read_joined(Path(case_dir) / "postProcessing" / "waterLevel", "height.dat")
    return times, columns[0::2]  # each gauge writes two columns: depth, then offset from the gauge point
