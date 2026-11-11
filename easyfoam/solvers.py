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
    "RNGkEpsilon": ("RNG k-epsilon (RANS, swirling and separating flow)", ("k", "epsilon", "nut")),
    "kOmega": ("k-omega, standard (RANS)", ("k", "omega", "nut")),
    "kkLOmega": ("k-kl-omega (RANS with laminar-turbulent transition)", ("kt", "kl", "omega", "nut")),
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

#: non-Newtonian viscosity models -> (label, default coefficients)
VISCOSITY_MODELS: dict[str, tuple[str, dict[str, float]]] = {
    "Newtonian": ("Newtonian (constant viscosity)", {}),
    "CrossPowerLaw": ("Cross power law (shear-thinning)", {"nu0": 0.01, "nuInf": 1e-05, "m": 0.4, "n": 3.0}),
    "BirdCarreau": ("Bird-Carreau (polymers, blood)", {"nu0": 1e-03, "nuInf": 1e-06, "k": 1.0, "n": 0.5}),
    "HerschelBulkley": ("Herschel-Bulkley (yield stress: mud, slurry)", {"k": 0.01, "n": 0.8, "tau0": 0.1, "nu0": 1.0}),
    "powerLaw": ("Power law", {"nuMax": 1e-02, "nuMin": 1e-06, "k": 1e-03, "n": 0.7}),
    "Casson": ("Casson (blood, suspensions)", {"m": 3.9e-06, "tau0": 2.9e-06, "nuMin_": 1e-06, "nuMax_": 1e-03}),
}

#: wave theories of the wave maker -> label
WAVE_MODELS: dict[str, str] = {
    "StokesII": "Stokes 2nd order (most regular waves)",
    "StokesI": "Stokes 1st order (small, linear waves)",
    "StokesV": "Stokes 5th order (steep waves in deeper water)",
    "cnoidal": "Cnoidal (long waves in shallow water)",
    "solitary": "Solitary wave (one crest, e.g. a surge)",
}
