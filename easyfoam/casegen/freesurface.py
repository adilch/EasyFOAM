"""Set-up dictionaries for free-surface flow (water and air, solver interFoam).

Differences from single-phase flow: the water fraction ``alpha.water`` is
solved for, the pressure variable is ``p_rgh`` (pressure without the
hydrostatic part, in pascals), gravity matters, and the water has to be placed
in the domain before the run (``setFields``).
"""

from __future__ import annotations

from collections.abc import Sequence

from easyfoam.foam.boundaryfile import Patch
from easyfoam.foam.dictfmt import Named, Q
from easyfoam.model import Boundary, Project
from easyfoam.solvers import turbulence_fields

WATER = "alpha.water"
DIMENSIONS = {"U": "[0 1 -1 0 0 0 0]", "p_rgh": "[1 -1 -2 0 0 0 0]", WATER: "[0 0 0 0 0 0 0]"}
ZERO_VECTOR = "uniform (0 0 0)"


def _entry(field: str, patch: Patch, bc: Boundary, base) -> dict:
    """Boundary entry for U, p_rgh or the water fraction."""
    if bc.kind == "constraint":
        return {"type": patch.type}
    if bc.kind == "slip":
        return {"type": "slip"}
    if bc.kind == "freeOutflow":
        return {"type": "zeroGradient"}

    if bc.kind == "waterLevelOutlet":
        # ambient pressure measured from the tailwater level (see href_dict): hydrostatic below it
        if field == "U":
            return {"type": "pressureInletOutletVelocity", "value": ZERO_VECTOR}
        if field == "p_rgh":  # a level that changes in time is set in field_dicts (tailwater_pressure)
            return {"type": "totalPressure", "p0": "uniform 0"}
        return {"type": "zeroGradient"}
    if bc.kind in ("waveInlet", "waveOutlet"):
        if field == "U":
            return {"type": "waveVelocity", "value": ZERO_VECTOR}
        if field == "p_rgh":
            return {"type": "fixedFluxPressure", "value": "uniform 0"}
        return {"type": "waveAlpha", "value": "uniform 0"} if bc.kind == "waveInlet" else {"type": "zeroGradient"}

    if field == "U":
        if bc.kind in ("velocityInlet", "movingWall"):
            return {"type": "fixedValue", "value": base._vector(bc.velocity)}
        if bc.kind == "flowRateInlet":
            return inflow_velocity(bc)
        if bc.kind == "atmosphere":
            return {"type": "pressureInletOutletVelocity", "value": ZERO_VECTOR}
        if bc.kind == "pressureOutlet":
            return {"type": "inletOutlet", "inletValue": ZERO_VECTOR, "value": ZERO_VECTOR}
        return {"type": "noSlip"}

    if field == "p_rgh":
        if bc.kind == "atmosphere":
            return {"type": "totalPressure", "p0": "uniform 0"}
        if bc.kind == "pressureOutlet":
            return {"type": "fixedValue", "value": f"uniform {float(bc.pressure)!r}"}
        return {"type": "fixedFluxPressure", "value": "uniform 0"}

    # water fraction
    if bc.kind == "velocityInlet":
        return {"type": "fixedValue", "value": f"uniform {bc.water_fraction:g}"}
    if bc.kind == "flowRateInlet":
        return {"type": "variableHeightFlowRate", "lowerBound": 0, "upperBound": 1, "value": "uniform 0"}
    if bc.kind == "atmosphere":
        return {"type": "inletOutlet", "inletValue": "uniform 0", "value": "uniform 0"}
    if bc.kind in ("wall", "movingWall") and abs(bc.contact_angle - 90.0) > 1e-9:
        # the angle at which the water surface meets the wall (below 90: the water wets the wall)
        return {
            "type": "constantAlphaContactAngle",
            "theta0": float(bc.contact_angle),
            "limit": "gradient",
            "value": "uniform 0",
        }
    return {"type": "zeroGradient"}


def inflow_velocity(bc: Boundary) -> dict:
    """``U`` on an inlet that lets in a volume of water per second, spread over the wetted part of the inlet.

    Each face gets a speed in proportion to its water fraction a: U = -n Q a / sum(a² A). The water coming in,
    sum(a U.S), is then exactly Q however smeared the water surface is across the inlet. OpenFOAM's own
    variableHeightFlowRateInletVelocity sets the flow of the water-air mix instead, which fell up to 16 % short.
    """
    value: dict = {
        "type": "expression",
        # the water fraction kept within 0 and 1 (min and max reduce over the patch in expressions: use mag)
        "variables": [Q("b = 0.5*(alpha.water + mag(alpha.water))"), Q("a = 0.5*(b + 1 - mag(b - 1))")],
    }
    if bc.flow_series:
        value["functions<scalar>"] = {
            "inflow": {"type": "table", "values": [[float(t), float(q)] for t, q in sorted(bc.flow_series)]}
        }
        rate = "fn:inflow(time())"
    else:
        rate = f"({float(bc.flow_rate):.10g})"
    value["expression"] = Q(f"-normal()*{rate}*a/(weightSum(a*a) + 1e-15)")
    return {"type": "uniformFixedValue", "value": ZERO_VECTOR, "uniformValue": value}


def field_dicts(project: Project, patches: Sequence[Patch]) -> dict[str, tuple[str, dict]]:
    from easyfoam.casegen import setup as base

    boundaries = {p.name: project.boundary_for(p.name, p.type) for p in patches}
    internal = base._turbulence(project, base._reference_speed(project, boundaries))
    out: dict[str, tuple[str, dict]] = {}
    for name in ("U", "p_rgh", WATER):
        cls = "volVectorField" if name == "U" else "volScalarField"
        start = base._vector(project.physics.initial_velocity) if name == "U" else "uniform 0"
        out[name] = (
            cls,
            {
                "dimensions": DIMENSIONS[name],
                "internalField": start,
                "boundaryField": {p.name: _entry(name, p, boundaries[p.name], base) for p in patches},
            },
        )
    for name in turbulence_fields(project.physics.turbulence):
        start = "uniform 0" if name == "nut" else base._scalar(internal[name])
        out[name] = (
            "volScalarField",
            {
                "dimensions": base.DIMENSIONS[name],
                "internalField": start,
                "boundaryField": {
                    p.name: base._entry(name, p, boundaries[p.name], project, internal) for p in patches
                },
            },
        )
    from easyfoam.casegen import motion

    motion.apply_wall_velocity(project, patches, out)
    for patch in patches:
        bc = boundaries[patch.name]
        if bc.kind == "waterLevelOutlet" and bc.level_series:  # a tailwater that rises and falls
            out["p_rgh"][1]["boundaryField"][patch.name] = tailwater_pressure(project, patches, bc.level_series)
    out.update(base.tracer_fields(project, patches, boundaries))
    return out


def fv_schemes(project: Project) -> dict:
    accurate = project.physics.numerics == "accurate"
    div = {
        "default": "none",
        "div(rhoPhi,U)": "Gauss linearUpwind grad(U)",
        "div(phi,alpha)": "Gauss vanLeer",
        "div(phirb,alpha)": "Gauss linear",
        "div(((rho*nuEff)*dev2(T(grad(U)))))": "Gauss linear",
    }
    for name in turbulence_fields(project.physics.turbulence):
        if name != "nut":
            div[f"div(phi,{name})"] = f"Gauss {f'linearUpwind grad({name})' if accurate else 'upwind'}"
    correction = "corrected" if accurate else "limited corrected 0.5"
    return {
        "ddtSchemes": {"default": "Euler"},
        "gradSchemes": {"default": "Gauss linear"},
        "divSchemes": div,
        "laplacianSchemes": {"default": f"Gauss linear {correction}"},
        "interpolationSchemes": {"default": "linear"},
        "snGradSchemes": {"default": correction},
        "wallDist": {"method": "meshWave"},
    }


def fv_solution(project: Project) -> dict:
    from easyfoam.casegen.setup import TRANSPORTED

    pressure = {"solver": "PCG", "preconditioner": "DIC", "tolerance": 1e-07, "relTol": 0.05}
    transport = {"solver": "smoothSolver", "smoother": "symGaussSeidel", "tolerance": 1e-08, "relTol": 0.1}
    if project.physics.solver == "interIsoFoam":
        # geometric reconstruction of the water surface (isoAdvector): a sharper interface
        interface = {
            "isoFaceTol": 1e-06,
            "surfCellTol": 1e-06,
            "nAlphaBounds": 3,
            "snapTol": 1e-12,
            "clip": True,
            "reconstructionScheme": "isoAlpha",
            "nAlphaSubCycles": 1,
            "cAlpha": 1,
        }
    else:
        interface = {
            "nAlphaCorr": 2,
            "nAlphaSubCycles": 1,
            "cAlpha": 1,
            "MULESCorr": True,
            "nLimiterIter": 5,
            "solver": "smoothSolver",
            "smoother": "symGaussSeidel",
            "tolerance": 1e-08,
            "relTol": 0,
        }
    return {
        "solvers": {
            '"alpha.water.*"': interface,
            '"pcorr.*"': {"solver": "PCG", "preconditioner": "DIC", "tolerance": 1e-05, "relTol": 0},
            "p_rgh": pressure,
            "p_rghFinal": {**pressure, "relTol": 0},
            TRANSPORTED: transport,
            TRANSPORTED[:-1] + 'Final"': {**transport, "relTol": 0},
        },
        "PIMPLE": {
            "momentumPredictor": False,
            "nOuterCorrectors": 1,
            "nCorrectors": 3,
            "nNonOrthogonalCorrectors": 1,
        },
        "relaxationFactors": {"equations": {'".*"': 1}},
    }


def transport_properties(project: Project) -> dict:
    from easyfoam.casegen.setup import viscosity_entries

    ph = project.physics
    return {
        "phases": ["water", "air"],
        "water": {**viscosity_entries(project), "rho": ph.rho},
        "air": {"transportModel": "Newtonian", "nu": ph.air_nu, "rho": ph.air_rho},
        "sigma": ph.surface_tension,
    }


def gravity_dict(project: Project) -> dict:
    return {"dimensions": "[0 1 -2 0 0 0 0]", "value": [float(c) for c in project.physics.gravity]}


def _corner(values: Sequence[float]) -> str:
    return "(" + " ".join(f"{c:g}" for c in values) + ")"


def set_fields_dict(project: Project) -> dict:
    """Where the water is at the start: air everywhere, water in the listed boxes."""
    water = ["volScalarFieldValue", WATER, 1]
    regions = [
        Named("boxToCell", {"box": f"{_corner(box[:3])} {_corner(box[3:6])}", "fieldValues": list(water)})
        for box in project.physics.water_regions
    ]
    if project.channel is not None:  # a built channel starts filled to its initial water depth
        from easyfoam import channel

        regions += channel.water_regions(project.channel)
    return {"defaultFieldValues": ["volScalarFieldValue", WATER, 0], "regions": regions}


def up_direction(project: Project) -> list[float]:
    """Unit vector pointing up (against gravity)."""
    g = [float(c) for c in project.physics.gravity]
    size = sum(c * c for c in g) ** 0.5 or 1.0
    return [-c / size + 0.0 for c in g]


def href_dict(project: Project, patches: Sequence[Patch]) -> dict | None:
    """Reference height for the hydrostatic pressure: the tailwater level of a water-level outlet.

    With it, the fixed ambient pressure on that outlet is hydrostatic below the given level.
    """
    levels = [
        float(min(bc.level_series)[1]) if bc.level_series else bc.level  # the level at the start
        for bc in (project.boundary_for(p.name, p.type) for p in patches)
        if bc.kind == "waterLevelOutlet"
    ]
    if not levels:
        return None
    return {"dimensions": "[0 1 0 0 0 0 0]", "value": levels[0]}


def tailwater_pressure(project: Project, patches: Sequence[Patch], series) -> dict:
    """``p_rgh`` on an outlet whose tailwater level follows ``series`` ([[t, level], ...]).

    Fluid at rest below a level L has ``p_rgh = rho g (L - hRef)``, whatever it is. Taking ``rho`` from the cells
    next to each face gives water the tailwater's hydrostatic pressure, so the level inside follows, while air stays
    at ambient pressure: values fixed from the level alone pushed water pressure into air cells where the water
    had not yet risen, and drove the air at hundreds of metres a second.
    """
    reference = href_dict(project, patches)
    href = float(reference["value"]) if reference else 0.0
    g = sum(float(c) ** 2 for c in project.physics.gravity) ** 0.5
    table = [[float(t), float(level)] for t, level in sorted(series)]
    return {
        "type": "uniformFixedValue",
        "value": "uniform 0",
        "uniformValue": {
            "type": "expression",
            "functions<scalar>": {"tailwater": {"type": "table", "values": table}},
            "expression": Q(f"internalField(rho)*{g:.10g}*(fn:tailwater(time()) - ({href:.10g}))"),
        },
    }


def wave_properties(project: Project, patches: Sequence[Patch]) -> dict | None:
    """Settings of the wave maker and of absorbing boundaries, keyed by boundary name."""
    waves: dict = {}
    for patch in patches:
        bc = project.boundary_for(patch.name, patch.type)
        if bc.kind == "waveInlet":
            if bc.wave_model == "solitary":  # a single crest: no period, no ramp-up
                waves[patch.name] = {
                    "alpha": WATER,
                    "waveModel": "Boussinesq",
                    "nPaddle": 1,
                    "waveHeight": bc.wave_height,
                    "waveAngle": 0.0,
                    "activeAbsorption": True,
                    "wavePeriod": 0.0,
                }
            else:
                waves[patch.name] = {
                    "alpha": WATER,
                    "waveModel": bc.wave_model,
                    "nPaddle": 1,
                    "waveHeight": bc.wave_height,
                    "waveAngle": 0.0,
                    "rampTime": bc.wave_period,
                    "activeAbsorption": True,
                    "wavePeriod": bc.wave_period,
                }
        elif bc.kind == "waveOutlet":
            waves[patch.name] = {"alpha": WATER, "waveModel": "shallowWaterAbsorption", "nPaddle": 1}
    return waves or None


def dynamic_mesh_dict(project: Project) -> dict | None:
    """Refine the mesh where the water surface is, and coarsen it again where it has left."""
    levels = int(project.physics.adaptive_levels)
    if levels <= 0:
        return None
    return {
        "dynamicFvMesh": "dynamicRefineFvMesh",
        "dynamicRefineFvMeshCoeffs": {
            "refineInterval": 1,
            "field": WATER,
            "lowerRefineLevel": 0.001,
            "upperRefineLevel": 0.999,
            "unrefineLevel": 10,
            "nBufferLayers": 1,
            "maxRefinement": levels,
            "maxCells": 5000000,
            "correctFluxes": [
                ["phi", "none"], ["nHatf", "none"], ["rhoPhi", "none"],
                ["alphaPhi0.water", "none"], ["alphaPhi0", "none"], ["alphaPhiUn", "none"], ["ghf", "none"],
            ],  # fmt: skip
            "dumpLevel": True,
        },
    }
