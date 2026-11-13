"""Solver set-up dictionaries: fields with boundary conditions, numerics, run control."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from easyfoam.casegen import freesurface, motion
from easyfoam.foam.boundaryfile import Patch
from easyfoam.model import SCHMIDT_TURBULENT, Boundary, Project, roughness_height, series_entry
from easyfoam.runtime import Step
from easyfoam.solvers import POST_FUNCTIONS, solver_spec, turbulence_fields

C_MU = 0.09
#: kinds that behave like a pressure outlet in single-fluid flow
OUTLET_LIKE = ("pressureOutlet", "freeOutflow", "waterLevelOutlet", "waveOutlet")
MIN_SPEED = 0.1  # m/s, keeps turbulence quantities positive for a flow starting at rest
TRANSPORTED = '"(U|k|epsilon|omega|nuTilda|kt|kl)"'

DIMENSIONS = {
    "U": "[0 1 -1 0 0 0 0]",
    "p": "[0 2 -2 0 0 0 0]",
    "k": "[0 2 -2 0 0 0 0]",
    "epsilon": "[0 2 -3 0 0 0 0]",
    "omega": "[0 0 -1 0 0 0 0]",
    "nuTilda": "[0 2 -1 0 0 0 0]",
    "kt": "[0 2 -2 0 0 0 0]",
    "kl": "[0 2 -2 0 0 0 0]",
    "nut": "[0 2 -1 0 0 0 0]",
}
WALL_FUNCTIONS = {
    "k": "kqRWallFunction",
    "epsilon": "epsilonWallFunction",
    "omega": "omegaWallFunction",
}
_YPLUS = re.compile(
    r"patch (\S+) y\+ : min = (\S+), max = (\S+), average = (\S+)"
)


def _vector(v: Sequence[float]) -> str:
    return "uniform (" + " ".join(repr(float(c)) for c in v) + ")"


def _scalar(v: float) -> str:
    return f"uniform {v:.6g}"


def _speed(v: Sequence[float]) -> float:
    return math.sqrt(sum(c * c for c in v))


def turbulence_inlet_values(speed: float, intensity: float, length: float) -> tuple[float, float, float]:
    """k, epsilon and omega for a stream of the given speed, intensity and length scale."""
    speed = max(speed, MIN_SPEED)
    k = 1.5 * (intensity * speed) ** 2
    epsilon = C_MU**0.75 * k**1.5 / length
    omega = math.sqrt(k) / (C_MU**0.25 * length)
    return k, epsilon, omega


def _turbulence(project: Project, speed: float) -> dict[str, float]:
    k, epsilon, omega = turbulence_inlet_values(
        speed, project.physics.turbulence_intensity, project.physics.turbulence_length
    )
    return {
        "k": k, "epsilon": epsilon, "omega": omega, "nuTilda": 3.0 * project.physics.nu, "nut": 0.0,
        "kt": k, "kl": 0.0,  # transition model: turbulent and laminar kinetic energy
    }  # fmt: skip


def _boundaries(project: Project, patches: Sequence[Patch]) -> dict[str, Boundary]:
    return {p.name: project.boundary_for(p.name, p.type) for p in patches}


def _reference_speed(project: Project, boundaries: dict[str, Boundary]) -> float:
    start = _speed(project.physics.initial_velocity)
    if start > 0:
        return start
    inlets = [_speed(b.velocity) for b in boundaries.values() if b.kind == "velocityInlet"]
    return max(inlets, default=0.0)


def _entry(field: str, patch: Patch, bc: Boundary, project: Project, internal: dict[str, float]) -> dict:
    if bc.kind == "constraint":
        return {"type": patch.type}
    if bc.kind == "slip":
        return {"type": "slip"}
    is_wall = bc.kind in ("wall", "movingWall")

    if field == "U":
        if bc.kind in ("velocityInlet", "movingWall"):
            return {"type": "fixedValue", "value": _vector(bc.velocity)}
        if bc.kind == "flowRateInlet":
            rate = series_entry(bc.flow_series) if bc.flow_series else bc.flow_rate
            return {"type": "flowRateInletVelocity", "volumetricFlowRate": rate, "value": "uniform (0 0 0)"}
        if bc.kind == "atmosphere":
            return {"type": "pressureInletOutletVelocity", "value": "uniform (0 0 0)"}
        if bc.kind in OUTLET_LIKE:
            zero = "uniform (0 0 0)"
            return {"type": "inletOutlet", "inletValue": zero, "value": zero}
        return {"type": "noSlip"}
    if field == "p":
        if bc.kind == "atmosphere":
            return {"type": "totalPressure", "p0": "uniform 0"}
        if bc.kind in OUTLET_LIKE:
            return {"type": "fixedValue", "value": f"uniform {float(bc.pressure)!r}"}
        return {"type": "zeroGradient"}

    # turbulence fields
    model = project.physics.turbulence
    transition = model == "kkLOmega"  # always resolved down to the wall
    low_re = project.physics.wall_treatment == "lowRe"
    if field == "nut":
        if not is_wall or transition:
            return {"type": "calculated", "value": "uniform 0"}
        if low_re:
            return {"type": "nutLowReWallFunction", "value": "uniform 0"}
        needs_k = "k" in turbulence_fields(model)
        ks = roughness_height(bc)
        if ks > 0:  # a rough wall: the wall function shifts the log law by the roughness
            if needs_k:
                return {"type": "nutkRoughWallFunction", "Ks": f"uniform {ks:g}", "Cs": "uniform 0.5",
                        "value": "uniform 0"}  # fmt: skip
            return {"type": "nutURoughWallFunction", "roughnessHeight": ks, "roughnessConstant": 0.5,
                    "roughnessFactor": 1, "value": "uniform 0"}  # fmt: skip
        function = "nutkWallFunction" if needs_k else "nutUSpaldingWallFunction"
        return {"type": function, "value": "uniform 0"}
    if is_wall:
        if field in ("nuTilda", "kt", "kl"):
            return {"type": "fixedValue", "value": "uniform 0"}
        if transition and field == "omega":
            return {"type": "zeroGradient"}
        if low_re and field == "k":
            return {"type": "kLowReWallFunction", "value": _scalar(internal[field])}
        return {"type": WALL_FUNCTIONS[field], "value": _scalar(internal[field])}
    if bc.kind == "flowRateInlet":
        return {"type": "fixedValue", "value": _scalar(internal[field])}
    if bc.kind == "velocityInlet":
        return {"type": "fixedValue", "value": _scalar(_turbulence(project, _speed(bc.velocity))[field])}
    value = _scalar(internal[field])
    return {"type": "inletOutlet", "inletValue": value, "value": value}


def field_dicts(project: Project, patches: Sequence[Patch]) -> dict[str, tuple[str, dict]]:
    """``{field name: (class, dictionary)}`` for the files of the ``0`` folder."""
    if solver_spec(project.physics.solver).multiphase:
        return freesurface.field_dicts(project, patches)
    names = ["U", "p", *turbulence_fields(project.physics.turbulence)]
    boundaries = _boundaries(project, patches)
    internal = _turbulence(project, _reference_speed(project, boundaries))

    out: dict[str, tuple[str, dict]] = {}
    for name in names:
        if name == "U":
            cls, start = "volVectorField", _vector(project.physics.initial_velocity)
        elif name in ("p", "nut"):
            cls, start = "volScalarField", "uniform 0"
        else:
            cls, start = "volScalarField", _scalar(internal[name])
        out[name] = (
            cls,
            {
                "dimensions": DIMENSIONS[name],
                "internalField": start,
                "boundaryField": {
                    p.name: _entry(name, p, boundaries[p.name], project, internal) for p in patches
                },
            },
        )
    motion.apply_wall_velocity(project, patches, out)
    out.update(tracer_fields(project, patches, boundaries))
    return out


#: boundary kinds where the water leaves the domain
OUTLET_KINDS = ("pressureOutlet", "freeOutflow", "waterLevelOutlet", "waveOutlet")


def tracer_fields(project: Project, patches: Sequence[Patch], boundaries: dict[str, Boundary]) -> dict:
    """Field files of the tracers: they enter through inlets with the given concentration."""
    out: dict[str, tuple[str, dict]] = {}
    for tracer in project.tracers:
        entries = {}
        for patch in patches:
            bc = boundaries[patch.name]
            if bc.kind == "constraint":
                entries[patch.name] = {"type": patch.type}
            elif bc.kind == "slip":
                entries[patch.name] = {"type": "slip"}
            elif bc.kind in ("velocityInlet", "flowRateInlet", "waveInlet"):
                value = 0.0 if tracer.kind == "age" else bc.tracer_values.get(tracer.name, bc.tracer_value)
                entries[patch.name] = {"type": "fixedValue", "value": f"uniform {value:g}"}
            elif bc.kind in ("wall", "movingWall"):
                entries[patch.name] = {"type": "zeroGradient"}
            elif bc.kind in OUTLET_KINDS:
                # Water drawn back in by an eddy at an outlet is water that has just left: it keeps its own
                # concentration and age. A fixed 0 there diluted the outflow and let tracer diffuse out unseen,
                # so a tracer test never reached 1 and its residence times came out too long.
                entries[patch.name] = {"type": "zeroGradient"}
            else:
                entries[patch.name] = {"type": "inletOutlet", "inletValue": "uniform 0", "value": "uniform 0"}
        out[tracer.name] = (
            "volScalarField",
            {"dimensions": "[0 0 0 0 0 0 0]", "internalField": "uniform 0", "boundaryField": entries},
        )
    return out


def tracer_function(project: Project, tracer) -> dict:
    """The scalarTransport function object that carries a tracer, with its decay or ageing."""
    entry = {
        "type": "scalarTransport",
        "libs": ["solverFunctionObjects"],
        "field": tracer.name,
        "resetOnStartUp": False,
        "writeControl": "writeTime",
    }
    if project.physics.turbulence == "laminar":
        entry["D"] = tracer.diffusivity
    else:  # molecular plus turbulent mixing: D = alphaD nu + alphaDt nut
        entry["alphaD"] = tracer.diffusivity / max(float(project.physics.nu), 1e-30)
        entry["alphaDt"] = 1.0 / SCHMIDT_TURBULENT
    source = None
    if tracer.kind == "age":
        source = [1, 0]  # each second in the domain adds a second of age
        entry["bounded01"] = False
    elif tracer.decay > 0:
        source = [0, -float(tracer.decay)]  # implicit: -decay * C
    if source is not None:
        entry["fvOptions"] = {
            f"{tracer.name}Source": {
                "type": "scalarSemiImplicitSource",
                "selectionMode": "all",
                "volumeMode": "specific",
                "sources": {tracer.name: source},
            }
        }
    return entry


def _tidy(x: float) -> float | int:
    return int(x) if float(x).is_integer() else x


def force_patches(project: Project, patches: Sequence[Patch]) -> list[str]:
    """The patches forces are summed over."""
    existing = [p.name for p in patches]
    if project.forces.patches:
        return [name for name in project.forces.patches if name in existing]
    shapes = [s.name for s in project.shapes if s.role == "wall"]
    return [
        p.name
        for p in patches
        if p.type == "wall" and any(p.name == s or p.name.startswith(s + "_") for s in shapes)
    ]


def _cross(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def reference_speed(project: Project, patches: Sequence[Patch]) -> float:
    """The speed coefficients are based on: the user's value, else the inlet / initial speed."""
    if project.forces.ref_velocity > 0:
        return project.forces.ref_velocity
    return max(_reference_speed(project, _boundaries(project, patches)), MIN_SPEED)


def _functions(project: Project, patches: Sequence[Patch]) -> dict:
    monitor = project.forces
    multiphase = solver_spec(project.physics.solver).multiphase
    # force coefficients are based on one density and speed: not meaningful with water and air
    on = force_patches(project, patches) if monitor.enabled and not multiphase else []
    functions: dict = {}
    run = project.run
    saves = run.end_time / run.write_interval if run.write_interval > 0 else 0.5
    if abs(saves - round(saves)) > 1e-9:
        # OpenFOAM only saves at regular save points; make sure the final state is kept too
        pressure = ["p_rgh", freesurface.WATER] if multiphase else ["p"]
        fields = ["U", *pressure, *turbulence_fields(project.physics.turbulence), "phi"]
        functions["saveAtEnd"] = {
            "type": "writeObjects",
            "libs": ["utilityFunctionObjects"],
            "objects": fields,
            "writeOption": "anyWrite",
            "writeControl": "onEnd",
        }
    if project.probes:
        functions["probes"] = {
            "type": "probes",
            "libs": ["sampling"],
            "writeControl": "timeStep",
            "writeInterval": 1,
            "fields": ["p_rgh", "U", freesurface.WATER] if multiphase else ["p", "U"],
            "probeLocations": [list(point) for point in project.probes],
        }
        if multiphase:
            # the same points also report the water level above the bed
            functions["waterLevel"] = {
                "type": "interfaceHeight",
                "libs": ["fieldFunctionObjects"],
                "writeControl": "timeStep",
                "writeInterval": 1,
                "log": False,
                "alpha": freesurface.WATER,
                "locations": [list(point) for point in project.probes],
            }
    for tracer in project.tracers:
        functions[f"tracer_{tracer.name}"] = tracer_function(project, tracer)
    existing = {p.name for p in patches}
    for name in project.flow_monitors:
        if name in existing:
            functions[f"flow_{name}"] = {
                "type": "surfaceFieldValue",
                "libs": ["fieldFunctionObjects"],
                "writeControl": "timeStep",
                "writeInterval": 1,
                "log": False,
                "writeFields": False,
                "regionType": "patch",
                "name": name,
                # the volume flux, counting only the water where there is a free surface
                "operation": "weightedSum" if multiphase else "sum",
                **({"weightField": freesurface.WATER} if multiphase else {}),
                "fields": ["phi"],
            }
            concentrations = [t.name for t in project.tracers]
            if concentrations:
                # flow-weighted mean concentration (or age) of what leaves through this boundary
                functions[f"tracerOut_{name}"] = {
                    "type": "surfaceFieldValue",
                    "libs": ["fieldFunctionObjects"],
                    "writeControl": "timeStep",
                    "writeInterval": 1,
                    "log": False,
                    "writeFields": False,
                    "regionType": "patch",
                    "name": name,
                    "operation": "weightedAverage",
                    "weightFields": ["phi", freesurface.WATER] if multiphase else ["phi"],
                    "fields": concentrations,
                }
    if on:
        functions["forceCoeffs"] = {
            "type": "forceCoeffs",
            "libs": ["forces"],
            "writeControl": "timeStep",
            "writeInterval": 1,
            "log": False,
            "patches": on,
            "rho": "rhoInf",
            "rhoInf": project.physics.rho,
            "CofR": list(monitor.centre),
            "dragDir": list(monitor.drag_dir),
            "liftDir": list(monitor.lift_dir),
            "pitchAxis": _cross(monitor.lift_dir, monitor.drag_dir),
            "magUInf": reference_speed(project, patches),
            "lRef": monitor.ref_length,
            "Aref": monitor.ref_area,
        }
    return functions


def control_dict(project: Project, patches: Sequence[Patch] | None = None) -> dict:
    spec = solver_spec(project.physics.solver)
    run = project.run
    d: dict = {
        "application": project.physics.solver,
        "startFrom": "latestTime",
        "startTime": 0,
        "stopAt": "endTime",
        "endTime": _tidy(run.end_time),
    }
    if spec.steady:
        d |= {"deltaT": 1, "writeControl": "timeStep", "writeInterval": max(1, int(run.write_interval))}
    else:
        d |= {
            "deltaT": run.delta_t,
            "writeControl": "adjustable" if run.adjust_time_step else "runTime",
            "writeInterval": run.write_interval,
        }
    d |= {
        "purgeWrite": run.purge_write,
        "writeFormat": "ascii",
        "writePrecision": 8,
        "writeCompression": False,
        "timeFormat": "general",
        "timePrecision": 6,
        "runTimeModifiable": True,
    }
    if not spec.steady and run.adjust_time_step:
        d |= {"adjustTimeStep": True, "maxCo": run.max_courant}
    if spec.multiphase:
        # the time step always follows the flow and the moving water surface
        d |= {
            "writeControl": "adjustable",
            "adjustTimeStep": True,
            "maxCo": run.max_courant,
            "maxAlphaCo": run.max_courant,
            "maxDeltaT": run.write_interval,
        }
    functions = _functions(project, patches) if patches else {}
    if functions:
        d["functions"] = functions
    return d


def fv_schemes(project: Project) -> dict:
    if solver_spec(project.physics.solver).multiphase:
        schemes = freesurface.fv_schemes(project)
        for tracer in project.tracers:
            schemes["divSchemes"][f"div(phi,{tracer.name})"] = "Gauss limitedLinear 1"
        return schemes
    steady = solver_spec(project.physics.solver).steady
    accurate = project.physics.numerics == "accurate"
    bounded = "bounded " if steady else ""
    div = {
        "default": "none",
        "div(phi,U)": f"{bounded}Gauss linearUpwind grad(U)",
        "div((nuEff*dev2(T(grad(U)))))": "Gauss linear",
    }
    for name in turbulence_fields(project.physics.turbulence):
        if name != "nut":
            scheme = f"linearUpwind grad({name})" if accurate else "upwind"
            div[f"div(phi,{name})"] = f"{bounded}Gauss {scheme}"
    for tracer in project.tracers:
        # Steady runs carry tracers with upwind: the equation is then linear, settles in one solve once the flow has,
        # and balances exactly. limitedLinear never settles there: its limiter flips from one iteration to the next,
        # which biased the age of the water by 8 % and made a decaying tracer blow up.
        div[f"div(phi,{tracer.name})"] = "bounded Gauss upwind" if steady else "Gauss limitedLinear 1"
    correction = "corrected" if accurate else "limited corrected 0.5"
    return {
        "ddtSchemes": {"default": "steadyState" if steady else "Euler"},
        "gradSchemes": {"default": "cellLimited Gauss linear 1"},
        "divSchemes": div,
        "laplacianSchemes": {"default": f"Gauss linear {correction}"},
        "interpolationSchemes": {"default": "linear"},
        "snGradSchemes": {"default": correction},
        "wallDist": {"method": "meshWave"},
    }


# a tracer is solved in full every time step or iteration: the amount carried in and out must balance
TRACER_SOLVER = {"solver": "PBiCGStab", "preconditioner": "DILU", "tolerance": 1e-09, "relTol": 0, "maxIter": 2000}


def tracer_relaxation(tracer, steady: bool) -> float:
    """The equation relaxation factor of a tracer; 0 means none.

    OpenFOAM relaxes an equation only when its factor is above 0, and any factor, even 1, forces the matrix to be
    diagonally dominant through a correction that lags one iteration behind: that left the age of the water in a
    contact tank 8 % too high. So tracers are not relaxed, except a decaying one in a steady run. OpenFOAM applies a
    decay explicitly (a negative semi-implicit coefficient goes to the source side), and unrelaxed iterations blow
    up once the decay is faster than the water is renewed in dead zones. 1/(1 + k * 1000 s) keeps cells whose water
    stays up to about half an hour stable; the converged answer does not depend on it.
    """
    if not steady or tracer.kind == "age" or tracer.decay <= 0:
        return 0
    return min(0.9, 1.0 / (1.0 + float(tracer.decay) * 1000.0))


def _fv_solution(project: Project) -> dict:
    solution = _flow_solution(project)
    steady = solver_spec(project.physics.solver).steady
    for tracer in project.tracers:
        solution["solvers"][tracer.name] = dict(TRACER_SOLVER)
        factors = solution.setdefault("relaxationFactors", {}).setdefault("equations", {})
        factors[tracer.name] = tracer_relaxation(tracer, steady)
    return solution


def _flow_solution(project: Project) -> dict:
    if solver_spec(project.physics.solver).multiphase:
        return freesurface.fv_solution(project)
    steady = solver_spec(project.physics.solver).steady
    accurate = project.physics.numerics == "accurate"
    pressure = {"solver": "GAMG", "smoother": "GaussSeidel", "tolerance": 1e-06, "relTol": 0.05}
    transport = {"solver": "smoothSolver", "smoother": "symGaussSeidel", "tolerance": 1e-08, "relTol": 0.1}
    solvers: dict = {"p": pressure, TRANSPORTED: transport}
    extra: dict = {}
    if project.physics.potential_init:
        solvers["Phi"] = {**pressure, "relTol": 0.01}
        extra["potentialFlow"] = {"nNonOrthogonalCorrectors": 3, "PhiRefCell": 0, "PhiRefValue": 0}
    if steady:
        simplec = accurate
        factors: dict = {"equations": {"U": 0.9, '".*"': 0.9}} if simplec else {
            "fields": {"p": 0.3},
            "equations": {"U": 0.7, '".*"': 0.7},
        }
        simple: dict = {
            "nNonOrthogonalCorrectors": 1,
            "consistent": simplec,
            "pRefCell": 0,
            "pRefValue": 0,
        }
        target = project.run.residual_target
        if target > 0:
            simple["residualControl"] = {"p": target, "U": target, '"(k|epsilon|omega|nuTilda)"': target}
        return {"solvers": solvers, "SIMPLE": simple, **extra, "relaxationFactors": factors}
    solvers["pFinal"] = {**pressure, "relTol": 0}
    solvers[TRANSPORTED[:-1] + 'Final"'] = {**transport, "relTol": 0}
    return {
        "solvers": solvers,
        "PIMPLE": {
            "nOuterCorrectors": 1,
            "nCorrectors": 2,
            "nNonOrthogonalCorrectors": 1,
            "pRefCell": 0,
            "pRefValue": 0,
        },
        **extra,
        "relaxationFactors": {"equations": {'".*"': 1}},
    }


def transport_properties(project: Project) -> dict:
    if solver_spec(project.physics.solver).multiphase:
        return freesurface.transport_properties(project)
    return viscosity_entries(project)


def viscosity_entries(project: Project) -> dict:
    """The viscosity model of the main fluid: constant, or a non-Newtonian law with its coefficients."""
    model = project.physics.viscosity_model
    if model == "Newtonian":
        return {"transportModel": "Newtonian", "nu": project.physics.nu}
    return {"transportModel": model, f"{model}Coeffs": dict(project.physics.viscosity_coeffs)}


def fv_options(project: Project) -> dict | None:
    """Optional constraints on the solution; currently a cap on the velocity."""
    if project.physics.max_velocity <= 0:
        return None
    return {
        "limitVelocity": {
            "type": "limitVelocity",
            "active": True,
            "selectionMode": "all",
            "max": float(project.physics.max_velocity),
        }
    }


def fv_solution(project: Project) -> dict:
    return motion.extend_solution(project, _fv_solution(project))


def dynamic_mesh_dict(project: Project, patches: Sequence[Patch] = (), case_dir=None) -> dict | None:
    """Settings for a mesh that changes during the run: moving shapes, or refinement at the water surface."""
    moving = motion.dynamic_mesh_dict(project, patches, case_dir)
    if moving is not None:
        return moving
    if not solver_spec(project.physics.solver).multiphase:
        return None
    return freesurface.dynamic_mesh_dict(project)


def gravity_dict(project: Project) -> dict:
    return freesurface.gravity_dict(project)


def set_fields_dict(project: Project) -> dict:
    return freesurface.set_fields_dict(project)


def href_dict(project: Project, patches: Sequence[Patch]) -> dict | None:
    return freesurface.href_dict(project, patches)


def wave_properties(project: Project, patches: Sequence[Patch]) -> dict | None:
    return freesurface.wave_properties(project, patches)


def turbulence_properties(project: Project) -> dict:
    model = project.physics.turbulence
    turbulence_fields(model)
    if model == "laminar":
        return {"simulationType": "laminar"}
    return {"simulationType": "RAS", "RAS": {"RASModel": model, "turbulence": True, "printCoeffs": True}}


def decompose_dict(project: Project) -> dict:
    return {"numberOfSubdomains": max(1, project.run.processors), "method": "scotch"}


def _stitch(project: Project, usual: str) -> list[Step]:
    """The steps that put the processors' results back together."""
    if solver_spec(project.physics.solver).multiphase and project.physics.adaptive_levels > 0:
        # the mesh changed during the run: it has to be rebuilt together with the fields
        return [Step("reconstructParMesh", "reconstructParMesh"), Step("reconstructPar", usual)]
    return [Step("reconstructPar", usual)]


def run_steps(project: Project, resume: bool = False, decomposed: bool = False) -> list[Step]:
    """Steps of a run; ``resume`` continues from the latest saved result."""
    solver = project.physics.solver
    solver_spec(solver)
    n = project.run.processors
    multiphase = solver_spec(solver).multiphase
    potential = project.physics.potential_init and not resume and not multiphase
    place_water = [Step("setFields", "setFields")] if multiphase and not resume else []
    if resume and n > 1:
        first = [] if decomposed else [Step("decomposePar", "decomposePar -force")]
        return [
            *first,
            Step(solver, f"mpirun -np {n} {solver} -parallel"),
            *_stitch(project, "reconstructPar -newTimes"),
        ]
    if n <= 1:
        first = [Step("potentialFoam", "potentialFoam")] if potential else []
        return [*place_water, *first, Step(solver, solver)]
    steps = [*place_water, Step("decomposePar", "decomposePar -force")]
    if potential:
        steps.append(Step("potentialFoam", f"mpirun -np {n} potentialFoam -parallel"))
    steps.append(Step(solver, f"mpirun -np {n} {solver} -parallel"))
    steps.extend(_stitch(project, "reconstructPar"))
    return steps


def post_steps(project: Project, function: str) -> list[Step]:
    """Compute a derived quantity (y+, wall shear stress, …) for the latest saved time."""
    if function not in POST_FUNCTIONS:
        raise ValueError(f"'{function}' is not a known quantity; known: {', '.join(POST_FUNCTIONS)}")
    solver = project.physics.solver
    solver_spec(solver)
    return [Step(function, f"{solver} -postProcess -func {function} -latestTime")]


def parse_yplus(text: str) -> dict[str, tuple[float, float, float]]:
    """``{patch: (min, max, average)}`` from the output of the yPlus function."""
    found = {}
    for m in _YPLUS.finditer(text):
        found[m.group(1)] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))
    return found
