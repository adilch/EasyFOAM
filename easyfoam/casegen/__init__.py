"""Turn a :class:`~easyfoam.model.Project` into the files of an OpenFOAM case."""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from easyfoam.casegen import mesh as _mesh
from easyfoam.casegen import motion as _motion
from easyfoam.casegen import setup as _setup
from easyfoam.foam.boundaryfile import Patch
from easyfoam.foam.dictfmt import foam_file
from easyfoam.model import Project
from easyfoam.solvers import solver_spec

mesh_steps = _mesh.mesh_steps
run_steps = _setup.run_steps
post_steps = _setup.post_steps


def _system(project: Project, patches: Sequence[Patch] | None = None) -> dict[str, str]:
    return {
        "system/controlDict": foam_file(
            "dictionary", "controlDict", _setup.control_dict(project, patches)
        ),
        "system/fvSchemes": foam_file("dictionary", "fvSchemes", _setup.fv_schemes(project)),
        "system/fvSolution": foam_file("dictionary", "fvSolution", _setup.fv_solution(project)),
        # empty marker file that lets ParaView and the built-in viewer open the case
        f"{project.name}.foam": "",
    }


def mesh_files(project: Project, case_dir: Path | None = None) -> dict[str, str]:
    """Files needed to build the mesh, as ``{relative path: text}``."""
    files = _system(project)
    files["system/blockMeshDict"] = foam_file(
        "dictionary", "blockMeshDict", _mesh.block_mesh_dict(project)
    )
    if _mesh.uses_snappy(project):
        files["system/snappyHexMeshDict"] = foam_file(
            "dictionary", "snappyHexMeshDict", _mesh.snappy_dict(project, case_dir)
        )
        features = _mesh.feature_extract_dict(project)
        if features is not None:
            files["system/surfaceFeatureExtractDict"] = foam_file(
                "dictionary", "surfaceFeatureExtractDict", features
            )
    return files


def setup_files(project: Project, patches: Sequence[Patch], case_dir: Path | None = None) -> dict[str, str]:
    """Files needed to run the solver on an existing mesh with the given patches."""
    files = _system(project, patches)
    files["system/decomposeParDict"] = foam_file(
        "dictionary", "decomposeParDict", _setup.decompose_dict(project)
    )
    files["constant/transportProperties"] = foam_file(
        "dictionary", "transportProperties", _setup.transport_properties(project), location="constant"
    )
    files["constant/turbulenceProperties"] = foam_file(
        "dictionary", "turbulenceProperties", _setup.turbulence_properties(project), location="constant"
    )
    if solver_spec(project.physics.solver).multiphase:
        files["constant/g"] = foam_file(
            "uniformDimensionedVectorField", "g", _setup.gravity_dict(project), location="constant"
        )
        files["system/setFieldsDict"] = foam_file("dictionary", "setFieldsDict", _setup.set_fields_dict(project))
        reference = _setup.href_dict(project, patches)
        if reference is not None:
            files["constant/hRef"] = foam_file(
                "uniformDimensionedScalarField", "hRef", reference, location="constant"
            )
        waves = _setup.wave_properties(project, patches)
        if waves is not None:
            files["constant/waveProperties"] = foam_file("dictionary", "waveProperties", waves, location="constant")
    options = _setup.fv_options(project)
    if options is not None:
        files["constant/fvOptions"] = foam_file("dictionary", "fvOptions", options, location="constant")
    moving = _setup.dynamic_mesh_dict(project, patches, case_dir)
    if moving is not None:
        files["constant/dynamicMeshDict"] = foam_file("dictionary", "dynamicMeshDict", moving, location="constant")
    displacement = _motion.point_displacement(project, patches)
    if displacement is not None:
        files["0/pointDisplacement"] = foam_file(displacement[0], "pointDisplacement", displacement[1], location="0")
    for name, (cls, data) in _setup.field_dicts(project, patches).items():
        files[f"0/{name}"] = foam_file(cls, name, data, location="0")
    return files


def write_files(case_dir: Path, files: Mapping[str, str]) -> list[Path]:
    written = []
    for rel, text in files.items():
        path = Path(case_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))  # bytes: keep LF endings on Windows
        written.append(path)
    return written


def _is_time_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        float(path.name)
    except ValueError:
        return False
    return True


def clean_results(case_dir: Path) -> None:
    """Delete computed results; keep the mesh, the set-up and the start fields."""
    for entry in Path(case_dir).iterdir():
        computed_time = _is_time_dir(entry) and entry.name != "0"
        if computed_time or entry.name == "postProcessing" or (
            entry.is_dir() and entry.name.startswith("processor")
        ):
            shutil.rmtree(entry, ignore_errors=True)


def clean_mesh(case_dir: Path) -> None:
    """Delete the mesh and everything computed on it; keep geometry and settings."""
    case_dir = Path(case_dir)
    clean_results(case_dir)
    for rel in ("0", "constant/polyMesh", "constant/extendedFeatureEdgeMesh"):
        shutil.rmtree(case_dir / rel, ignore_errors=True)
