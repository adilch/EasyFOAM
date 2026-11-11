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
