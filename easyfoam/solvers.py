"""The solvers and turbulence models EasyFOAM knows how to set up."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SolverSpec:
    label: str
    steady: bool
    multiphase: bool = False  # water and air with a free surface


SOLVERS: dict[str, SolverSpec] = {
    "simpleFoam": SolverSpec("Incompressible flow, steady (simpleFoam)", steady=True),
    "pimpleFoam": SolverSpec("Incompressible flow, transient (pimpleFoam)", steady=False),
    "interFoam": SolverSpec("Free surface: water and air (interFoam)", steady=False, multiphase=True),
    "interIsoFoam": SolverSpec(
        "Free surface, sharper interface (interIsoFoam)", steady=False, multiphase=True
    ),
}

#: turbulence model -> (label, extra fields it solves for)
TURBULENCE: dict[str, tuple[str, tuple[str, ...]]] = {
    "laminar": ("Laminar (no turbulence model)", ()),
    "kEpsilon": ("k-epsilon (RANS)", ("k", "epsilon", "nut")),
    "kOmegaSST": ("k-omega SST (RANS)", ("k", "omega", "nut")),
    "realizableKE": ("Realizable k-epsilon (RANS)", ("k", "epsilon", "nut")),
    "SpalartAllmaras": ("Spalart-Allmaras (RANS, external aerodynamics)", ("nuTilda", "nut")),
}

#: name -> (kinematic viscosity m2/s, density kg/m3), around 20 degC and 1 atm
MATERIALS: dict[str, tuple[float, float]] = {
    "air": (1.5e-05, 1.2),
    "water": (1.0e-06, 998.0),
    "seawater": (1.05e-06, 1025.0),
    "engine oil": (1.0e-04, 880.0),
    "glycerine": (1.2e-03, 1260.0),
}


def solver_spec(name: str) -> SolverSpec:
    try:
        return SOLVERS[name]
    except KeyError:
        raise ValueError(f"solver '{name}' is not supported; known: {', '.join(SOLVERS)}") from None


def turbulence_fields(model: str) -> tuple[str, ...]:
    try:
        return TURBULENCE[model][1]
    except KeyError:
        raise ValueError(
            f"turbulence model '{model}' is not supported; known: {', '.join(TURBULENCE)}"
        ) from None

#: derived quantities the solver can compute from saved results
POST_FUNCTIONS: dict[str, str] = {
    "yPlus": "y+ (wall resolution)",
    "wallShearStress": "Wall shear stress",
    "vorticity": "Vorticity",
    "Q": "Q criterion (vortex cores)",
}
