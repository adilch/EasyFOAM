"""v0.4: free-surface (water and air) flow with interFoam, for weirs, spillways and dam breaks."""

from easyfoam import casegen
from easyfoam.casegen.setup import (
    control_dict,
    field_dicts,
    fv_schemes,
    fv_solution,
    gravity_dict,
    run_steps,
    set_fields_dict,
    transport_properties,
)
from easyfoam.checks import project_issues, step_states
from easyfoam.examples import EXAMPLES
from easyfoam.foam.boundaryfile import Patch
from easyfoam.foam.dictfmt import Named, dumps
from easyfoam.foam.logparser import LogParser
from easyfoam.model import KINDS_FOR_TYPE, Boundary, Project, default_boundary
from easyfoam.solvers import SOLVERS

PATCHES = [
    Patch("inlet", "patch", 10, 0),
    Patch("outlet", "patch", 10, 10),
    Patch("atmosphere", "patch", 40, 20),
    Patch("bed", "wall", 40, 60),
    Patch("sides", "patch", 80, 100),
    Patch("mid", "symmetry", 5, 180),
]


def flume(turbulence="kOmegaSST"):
    p = Project(name="flume")
    p.physics.solver = "interFoam"
    p.physics.turbulence = turbulence
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1e-06, 998.0
    p.physics.water_regions = [[0, 0, 0, 2.5, 0.5, 0.5]]
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.05)
    p.boundaries["outlet"] = Boundary(kind="freeOutflow")
    p.run.end_time, p.run.delta_t, p.run.write_interval, p.run.max_courant = 10, 0.001, 0.5, 0.6
    return p


def fields(project=None):
    return {name: data for name, (_cls, data) in field_dicts(project or flume(), PATCHES).items()}


# --- solver and fields -------------------------------------------------------


def test_free_surface_solver_is_offered_as_transient_two_phase():
    spec = SOLVERS["interFoam"]
    assert spec.steady is False and spec.multiphase is True
    assert SOLVERS["simpleFoam"].multiphase is False


def test_free_surface_fields_use_water_fraction_and_pressure_without_hydrostatic_part():
    f = fields()
    assert list(f) == ["U", "p_rgh", "alpha.water", "k", "omega", "nut"]
    assert f["p_rgh"]["dimensions"] == "[1 -1 -2 0 0 0 0]"
    assert f["alpha.water"]["dimensions"] == "[0 0 0 0 0 0 0]"
    assert f["alpha.water"]["internalField"] == "uniform 0"
    assert list(fields(flume("laminar"))) == ["U", "p_rgh", "alpha.water"]


def test_water_inlet_by_flow_rate_follows_the_water_level():
    f = fields()
    assert f["U"]["boundaryField"]["inlet"] == {
        "type": "variableHeightFlowRateInletVelocity",
        "flowRate": 0.05,
        "alpha": "alpha.water",
        "value": "uniform (0 0 0)",
    }
    assert f["alpha.water"]["boundaryField"]["inlet"] == {
        "type": "variableHeightFlowRate", "lowerBound": 0, "upperBound": 1, "value": "uniform 0",
    }  # fmt: skip
    assert f["p_rgh"]["boundaryField"]["inlet"]["type"] == "fixedFluxPressure"
    assert f["k"]["boundaryField"]["inlet"]["type"] == "fixedValue"


def test_atmosphere_lets_air_in_and_out_at_ambient_pressure():
    f = fields()
    assert f["p_rgh"]["boundaryField"]["atmosphere"] == {"type": "totalPressure", "p0": "uniform 0"}
    assert f["U"]["boundaryField"]["atmosphere"] == {"type": "pressureInletOutletVelocity", "value": "uniform (0 0 0)"}
    assert f["alpha.water"]["boundaryField"]["atmosphere"] == {
        "type": "inletOutlet", "inletValue": "uniform 0", "value": "uniform 0",
    }  # fmt: skip
    assert f["k"]["boundaryField"]["atmosphere"]["type"] == "inletOutlet"


def test_free_outflow_lets_everything_leave_undisturbed():
    f = fields()
    for name in ("U", "p_rgh", "alpha.water"):
        assert f[name]["boundaryField"]["outlet"] == {"type": "zeroGradient"}, name


def test_walls_hold_water_and_balance_gravity_in_the_pressure():
    f = fields()
    assert f["U"]["boundaryField"]["bed"] == {"type": "noSlip"}
    assert f["alpha.water"]["boundaryField"]["bed"] == {"type": "zeroGradient"}
    assert f["p_rgh"]["boundaryField"]["bed"] == {"type": "fixedFluxPressure", "value": "uniform 0"}
    assert f["omega"]["boundaryField"]["bed"]["type"] == "omegaWallFunction"


def test_a_velocity_inlet_says_how_much_of_the_inflow_is_water():
    p = flume()
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[2.0, 0.0, 0.0], water_fraction=1.0)
    f = fields(p)
    assert f["U"]["boundaryField"]["inlet"] == {"type": "fixedValue", "value": "uniform (2.0 0.0 0.0)"}
    assert f["alpha.water"]["boundaryField"]["inlet"] == {"type": "fixedValue", "value": "uniform 1"}


def test_slip_and_symmetry_apply_to_the_new_fields_too():
    f = fields()
    for name in f:
        assert f[name]["boundaryField"]["sides"] == {"type": "slip"}, name
        assert f[name]["boundaryField"]["mid"] == {"type": "symmetry"}, name


# --- properties, gravity, initial water --------------------------------------


def test_both_fluids_and_the_surface_tension_are_written():
    p = flume()
    assert transport_properties(p) == {
        "phases": ["water", "air"],
        "water": {"transportModel": "Newtonian", "nu": 1e-06, "rho": 998.0},
        "air": {"transportModel": "Newtonian", "nu": 1.48e-05, "rho": 1.2},
        "sigma": 0.07,
    }


def test_gravity_points_down_by_default():
    assert gravity_dict(flume()) == {"dimensions": "[0 1 -2 0 0 0 0]", "value": [0.0, 0.0, -9.81]}


def test_initial_water_regions_become_boxes_filled_with_water():
    p = flume()
    p.physics.water_regions.append([3, 0, 0, 6, 0.5, 0.2])
    d = set_fields_dict(p)
    assert d["defaultFieldValues"] == ["volScalarFieldValue", "alpha.water", 0]
    assert d["regions"] == [
        Named("boxToCell", {"box": "(0 0 0) (2.5 0.5 0.5)", "fieldValues": ["volScalarFieldValue", "alpha.water", 1]}),
        Named("boxToCell", {"box": "(3 0 0) (6 0.5 0.2)", "fieldValues": ["volScalarFieldValue", "alpha.water", 1]}),
    ]
    text = dumps(d)
    assert "defaultFieldValues (volScalarFieldValue alpha.water 0);" in text
    assert "        box             (0 0 0) (2.5 0.5 0.5);" in text


# --- numerics and run --------------------------------------------------------


def test_time_stepping_is_limited_by_the_flow_and_by_the_interface():
    d = control_dict(flume())
    assert d["application"] == "interFoam"
    assert (d["adjustTimeStep"], d["maxCo"], d["maxAlphaCo"]) == (True, 0.6, 0.6)
    assert d["maxDeltaT"] == 0.5 and d["writeControl"] == "adjustable"


def test_schemes_and_solver_settings_cover_the_interface_equation():
    p = flume()
    div = fv_schemes(p)["divSchemes"]
    assert div["div(phi,alpha)"] == "Gauss vanLeer" and "div(phirb,alpha)" in div
    assert "div(rhoPhi,U)" in div and "div(((rho*nuEff)*dev2(T(grad(U)))))" in div
    solution = fv_solution(p)
    assert solution["solvers"]['"alpha.water.*"']["nAlphaCorr"] == 2
    assert {"p_rgh", "p_rghFinal", '"pcorr.*"'} <= set(solution["solvers"])
    assert solution["PIMPLE"]["momentumPredictor"] is False
    assert "SIMPLE" not in solution


def test_the_water_is_placed_before_the_solver_starts_but_not_when_continuing():
    p = flume()
    assert [s.command for s in run_steps(p)] == ["setFields", "interFoam"]
    p.run.processors = 4
    assert [s.name for s in run_steps(p)] == ["setFields", "decomposePar", "interFoam", "reconstructPar"]
    assert [s.name for s in run_steps(p, resume=True, decomposed=True)] == ["interFoam", "reconstructPar"]


def test_case_files_for_a_free_surface_run():
    files = casegen.setup_files(flume(), PATCHES)
    assert {"0/alpha.water", "0/p_rgh", "0/U", "constant/g", "system/setFieldsDict"} <= set(files)
    assert "0/p" not in files
    assert "class           uniformDimensionedVectorField;" in files["constant/g"]
    assert "value           (0.0 0.0 -9.81);" in files["constant/g"]


def test_monitors_adapt_to_two_phase_flow():
    p = flume()
    p.forces.enabled = True  # air-based coefficients make no sense here
    p.probes = [[1.0, 0.25, 0.3]]
    p.run.end_time, p.run.write_interval = 10.2, 0.5
    functions = control_dict(p, PATCHES)["functions"]
    assert "forceCoeffs" not in functions
    assert functions["probes"]["fields"] == ["p_rgh", "U", "alpha.water"]
    assert functions["saveAtEnd"]["objects"] == ["U", "p_rgh", "alpha.water", "k", "omega", "nut", "phi"]


# --- the new boundary kinds in single-phase flow ------------------------------


def test_flow_rate_inlet_and_open_boundary_also_work_without_a_free_surface():
    p = Project(name="duct")
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.2)
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    p.boundaries["outlet"] = Boundary(kind="freeOutflow")
    f = fields(p)
    assert f["U"]["boundaryField"]["inlet"] == {
        "type": "flowRateInletVelocity", "volumetricFlowRate": 0.2, "value": "uniform (0 0 0)",
    }  # fmt: skip
    assert f["p"]["boundaryField"]["atmosphere"] == {"type": "totalPressure", "p0": "uniform 0"}
    assert f["U"]["boundaryField"]["atmosphere"]["type"] == "pressureInletOutletVelocity"
    assert f["p"]["boundaryField"]["outlet"]["type"] == "fixedValue"


def test_new_kinds_are_offered_for_open_boundaries_and_guessed_from_names():
    assert {"flowRateInlet", "atmosphere", "freeOutflow"} <= set(KINDS_FOR_TYPE["patch"])
    assert default_boundary("atmosphere", "patch").kind == "atmosphere"


# --- checks ------------------------------------------------------------------


def found(project):
    return [(i.step, i.level) for i in project_issues(project, PATCHES, True)]


def test_a_complete_flume_passes_the_checks():
    assert found(flume()) == []
    assert step_states(flume(), PATCHES, True, 1000, [])["Physics"].detail == "Free surface, k-omega SST"


def test_a_free_surface_case_without_any_water_gets_a_warning():
    p = flume()
    p.physics.water_regions = []
    p.boundaries["inlet"] = Boundary(kind="slip")
    assert ("Physics", "warning") in found(p)


def test_gravity_is_required_for_a_free_surface():
    p = flume()
    p.physics.gravity = [0.0, 0.0, 0.0]
    assert ("Physics", "error") in found(p)


def test_still_water_under_gravity_does_not_count_as_nothing_driving_the_flow():
    p = flume()
    p.boundaries["inlet"] = Boundary(kind="wall")
    p.boundaries["outlet"] = Boundary(kind="wall")
    assert found(p) == []  # a dam break has no inlet at all


# --- log and examples --------------------------------------------------------


def test_the_share_of_water_in_the_domain_is_read_from_the_log():
    parser = LogParser()
    for line in (
        "Courant Number mean: 0.01 max: 0.3",
        "Interface Courant Number mean: 0.001 max: 0.2",
        "Time = 0.05",
        "Phase-1 volume fraction = 0.130194  Min(alpha.water) = 0  Max(alpha.water) = 1",
        "Phase-1 volume fraction = 0.130195  Min(alpha.water) = 0  Max(alpha.water) = 1",
        "DICPCG:  Solving for p_rgh, Initial residual = 0.5, Final residual = 0.01, No Iterations 3",
        "Time = 0.1",
        "Phase-1 volume fraction = 0.1302  Min(alpha.water) = -1e-9  Max(alpha.water) = 1",
    ):
        parser.feed(line)
    assert parser.water_fraction == [(0.05, 0.130194), (0.1, 0.1302)]
    assert parser.residuals["p_rgh"] == [(0.05, 0.5)]
    assert parser.courant == [(0.01, 0.3)]  # the interface Courant line is not mistaken for it


def test_hydraulic_examples_are_ready_to_run():
    for key in ("dambreak", "weir"):
        p = EXAMPLES[key](key)
        assert p.physics.solver == "interFoam" and p.physics.water_regions
        assert p.physics.rho > 900
    weir = EXAMPLES["weir"]("weir")
    assert [s.name for s in weir.shapes if s.role == "wall"] == ["weir"]
    kinds = {name: b.kind for name, b in weir.boundaries.items()}
    assert kinds["inlet"] == "flowRateInlet" and kinds["outlet"] == "freeOutflow"
