"""Read the mesh and the computed fields of a case (through VTK)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CaseData:
    internal: Any  # pyvista.UnstructuredGrid with cell and point data
    patches: dict[str, Any]  # patch name -> pyvista surface


class CaseResults:
    """The saved times and fields of a (reconstructed) OpenFOAM case."""

    def __init__(self, case_dir: Path, name: str) -> None:
        import pyvista as pv  # imported here: only the GUI extra provides it

        foam = Path(case_dir) / f"{name}.foam"
        foam.touch(exist_ok=True)
        self._reader = pv.POpenFOAMReader(str(foam))
        self._reader.case_type = "reconstructed"
        self._reader.enable_all_patch_arrays()
        self._reader.enable_all_cell_arrays()

    @property
    def times(self) -> list[float]:
        return [float(t) for t in self._reader.time_values]

    @property
    def fields(self) -> list[str]:
        return list(self._reader.cell_array_names)

    def read(self, time: float | None = None) -> CaseData:
        times = self.times
        if times:
            self._reader.set_active_time_value(times[-1] if time is None else time)
        blocks = self._reader.read()
        boundary = blocks["boundary"] if "boundary" in blocks.keys() else {}
        patches = {key: boundary[key] for key in boundary.keys()} if boundary else {}
        return CaseData(blocks["internalMesh"], patches)


def cavitation_index(pressure, speed, rho: float, ambient: float, vapour: float, water=None, cap: float = 5.0):
    """Cavitation index: (absolute pressure - vapour pressure) / (1/2 rho speed^2), per cell.

    ``pressure`` is the gauge pressure in pascals. Values near or below about 0.2 warn of
    cavitation damage on spillway surfaces. The index is capped at ``cap`` where the water
    hardly moves, and set to ``cap`` in cells that are mostly air (``water`` below 0.5).
    """
    import numpy as np

    pressure, speed = np.asarray(pressure, dtype=float), np.asarray(speed, dtype=float)
    dynamic = 0.5 * rho * speed**2
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma = np.where(dynamic > 0, (pressure + ambient - vapour) / dynamic, cap)
    sigma = np.clip(sigma, None, cap)
    if water is not None:
        sigma = np.where(np.asarray(water) < 0.5, cap, sigma)
    return sigma


def add_cavitation_index(
    grid, rho: float, ambient: float, vapour: float, name: str = "cavitationIndex", cap: float = 20.0
) -> float | None:
    """Add the cavitation index to a result grid that has ``p`` and ``U``.

    Returns the lowest index found in the water (uncapped), or ``None`` if the grid lacks the fields.
    """
    import numpy as np

    data = grid.cell_data
    if "p" not in data or "U" not in data:
        return None
    speed = np.linalg.norm(np.asarray(data["U"]), axis=1)
    water = data["alpha.water"] if "alpha.water" in data else None
    data[name] = cavitation_index(data["p"], speed, rho, ambient, vapour, water, cap)
    exact = cavitation_index(data["p"], speed, rho, ambient, vapour, water, cap=float("inf"))
    finite = exact[np.isfinite(exact)]
    return float(finite.min()) if finite.size else float("inf")
