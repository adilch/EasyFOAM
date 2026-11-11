"""v0.6: more turbulence models, non-Newtonian fluids, tracer, limiter, contact angle, wave theories,
adaptive refinement at the water surface and the cavitation index."""

import numpy as np
import pytest

from easyfoam import casegen
from easyfoam.casegen.setup import (
    control_dict,
    dynamic_mesh_dict,
    field_dicts,
    fv_options,
    fv_schemes,
    fv_solution,
    transport_properties,
    wave_properties,
)
from easyfoam.checks import project_issues, step_states
from easyfoam.foam.boundaryfile import Patch
from easyfoam.model import Boundary, Project, Tracer
from easyfoam.results import cavitation_index

PATCHES = [
    Patch("inlet", "patch", 10, 0),
    Patch("outlet", "patch", 10, 10),
    Patch("atmosphere", "patch", 40, 20),
    Patch("bed", "wall", 40, 60),
]


def single(turbulence="kOmegaSST"):
    p = Project(name="s")
    p.physics.turbulence = turbulence
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[10.0, 0.0, 0.0])
    return p


def water():
    p = Project(name="w")
    p.physics.solver, p.physics.turbulence = "interFoam", "laminar"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1e-06, 998.0
    p.physics.water_regions = [[0, 0, 0, 1, 1, 0.4]]
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.01)
    p.boundaries["outlet"] = Boundary(kind="freeOutflow")
    return p


def boundary(project, field, patch="bed"):
    return field_dicts(project, PATCHES)[field][1]["boundaryField"][patch]


# --- turbulence --------------------------------------------------------------


def test_rng_k_epsilon_and_standard_k_omega_reuse_the_two_equation_fields():
    assert list(field_dicts(single("RNGkEpsilon"), PATCHES)) == ["U", "p", "k", "epsilon", "nut"]
    assert list(field_dicts(single("kOmega"), PATCHES)) == ["U", "p", "k", "omega", "nut"]
    assert step_states(single("RNGkEpsilon"), PATCHES, True, 1, [])["Physics"].detail == "Steady, RNG k-epsilon"


def test_transition_model_solves_laminar_and_turbulent_kinetic_energy_down_to_the_wall():
    p = single("kkLOmega")
    assert list(field_dicts(p, PATCHES)) == ["U", "p", "kt", "kl", "omega", "nut"]
    assert boundary(p, "kt") == {"type": "fixedValue", "value": "uniform 0"}
    assert boundary(p, "kl") == {"type": "fixedValue", "value": "uniform 0"}
    assert boundary(p, "omega") == {"type": "zeroGradient"}
    assert boundary(p, "kt", "inlet")["value"] == "uniform 0.375"  # the free-stream turbulence
    assert boundary(p, "kl", "inlet") == {"type": "fixedValue", "value": "uniform 0"}
    assert {"div(phi,kt)", "div(phi,kl)"} <= set(fv_schemes(p)["divSchemes"])


def test_resolving_the_boundary_layer_swaps_the_wall_functions():
    p = single()
    assert boundary(p, "nut")["type"] == "nutkWallFunction"
    p.physics.wall_treatment = "lowRe"
    assert boundary(p, "nut")["type"] == "nutLowReWallFunction"
    assert boundary(p, "k")["type"] == "kLowReWallFunction"
    assert boundary(p, "omega")["type"] == "omegaWallFunction"


# --- fluids ------------------------------------------------------------------


def test_non_newtonian_fluid_writes_its_model_and_coefficients():
    p = single("laminar")
    p.physics.viscosity_model = "CrossPowerLaw"
    p.physics.viscosity_coeffs = {"nu0": 0.01, "nuInf": 1e-05, "m": 0.4, "n": 3.0}
    assert transport_properties(p) == {
        "transportModel": "CrossPowerLaw",
        "CrossPowerLawCoeffs": {"nu0": 0.01, "nuInf": 1e-05, "m": 0.4, "n": 3.0},
    }
    assert transport_properties(single()) == {"transportModel": "Newtonian", "nu": 1.5e-05}


def test_non_newtonian_water_phase_in_free_surface_flow():
    p = water()
    p.physics.viscosity_model = "HerschelBulkley"
    p.physics.viscosity_coeffs = {"k": 0.1, "n": 0.6, "tau0": 0.5, "nu0": 1.0}
    phase = transport_properties(p)["water"]
    assert phase["transportModel"] == "HerschelBulkley" and phase["rho"] == 998.0
    assert phase["HerschelBulkleyCoeffs"]["tau0"] == 0.5


# --- limiter, contact angle, waves --------------------------------------------


def test_velocity_limiter_is_written_only_when_a_limit_is_set():
    p = water()
    assert fv_options(p) is None
    assert "constant/fvOptions" not in casegen.setup_files(p, PATCHES)
    p.physics.max_velocity = 20.0
    assert fv_options(p) == {
        "limitVelocity": {"type": "limitVelocity", "active": True, "selectionMode": "all", "max": 20.0}
    }
    assert "max             20.0;" in casegen.setup_files(p, PATCHES)["constant/fvOptions"]


def test_contact_angle_on_a_wall_shapes_the_water_surface_there():
    p = water()
    assert boundary(p, "alpha.water") == {"type": "zeroGradient"}  # 90 degrees: neutral
    p.boundaries["bed"] = Boundary(kind="wall", contact_angle=45.0)
    assert boundary(p, "alpha.water") == {
        "type": "constantAlphaContactAngle", "theta0": 45.0, "limit": "gradient", "value": "uniform 0",
    }  # fmt: skip


def test_more_wave_theories():
    p = water()
    p.boundaries["inlet"] = Boundary(kind="waveInlet", wave_height=0.1, wave_period=4.0, wave_model="cnoidal")
    assert wave_properties(p, PATCHES)["inlet"]["waveModel"] == "cnoidal"
    p.boundaries["inlet"].wave_model = "StokesV"
    assert wave_properties(p, PATCHES)["inlet"]["wavePeriod"] == 4.0
    p.boundaries["inlet"].wave_model = "solitary"
    wave = wave_properties(p, PATCHES)["inlet"]
    assert wave["waveModel"] == "Boussinesq" and wave["wavePeriod"] == 0.0 and "rampTime" not in wave


# --- tracer ------------------------------------------------------------------


def traced(project):
    project.tracers = [Tracer("dye", 2e-09)]
    project.boundaries["inlet"].tracer_value = 1.0
    return project


def test_a_tracer_is_carried_with_the_flow():
    p = traced(single())
    function = control_dict(p, PATCHES)["functions"]["tracer_dye"]
    assert function["type"] == "scalarTransport" and function["field"] == "dye" and function["D"] == 2e-09
    cls, data = field_dicts(p, PATCHES)["dye"]
    assert cls == "volScalarField" and data["dimensions"] == "[0 0 0 0 0 0 0]"
    assert data["boundaryField"]["inlet"] == {"type": "fixedValue", "value": "uniform 1"}
    assert data["boundaryField"]["bed"] == {"type": "zeroGradient"}
    assert data["boundaryField"]["outlet"]["type"] == "inletOutlet"
    assert "div(phi,dye)" in fv_schemes(p)["divSchemes"] and "dye" in fv_solution(p)["solvers"]


def test_a_tracer_works_in_free_surface_flow_too():
    p = traced(water())
    assert "dye" in field_dicts(p, PATCHES) and "tracer_dye" in control_dict(p, PATCHES)["functions"]
    assert "div(phi,dye)" in fv_schemes(p)["divSchemes"] and "dye" in fv_solution(p)["solvers"]


# --- adaptive refinement ------------------------------------------------------


def test_adaptive_refinement_follows_the_water_surface():
    p = water()
    assert dynamic_mesh_dict(p) is None
    p.physics.adaptive_levels = 2
    d = dynamic_mesh_dict(p)
    assert d["dynamicFvMesh"] == "dynamicRefineFvMesh"
    coeffs = d["dynamicRefineFvMeshCoeffs"]
    assert (coeffs["field"], coeffs["maxRefinement"]) == ("alpha.water", 2)
    assert (coeffs["lowerRefineLevel"], coeffs["upperRefineLevel"]) == (0.001, 0.999)
    assert "constant/dynamicMeshDict" in casegen.setup_files(p, PATCHES)
    single_fluid = single()
    single_fluid.physics.adaptive_levels = 2
    assert dynamic_mesh_dict(single_fluid) is None


def test_adaptive_refinement_needs_a_fully_three_dimensional_mesh():
    p = water()
    p.physics.adaptive_levels = 1
    flat = [*PATCHES, Patch("frontAndBack", "empty", 10, 100)]
    assert ("Physics", "error") in [(i.step, i.level) for i in project_issues(p, flat, True)]
    assert ("Physics", "error") not in [(i.step, i.level) for i in project_issues(p, PATCHES, True)]


# --- cavitation index ---------------------------------------------------------


def test_cavitation_index_compares_pressure_margin_with_dynamic_pressure():
    sigma = cavitation_index(
        pressure=np.array([0.0, -50000.0]), speed=np.array([20.0, 20.0]), rho=998.0,
        ambient=101325.0, vapour=2339.0,
    )  # fmt: skip
    assert sigma[0] == pytest.approx((101325.0 - 2339.0) / (0.5 * 998.0 * 400.0))
    assert sigma[1] == pytest.approx((101325.0 - 50000.0 - 2339.0) / (0.5 * 998.0 * 400.0))


def test_cavitation_index_is_capped_where_the_water_hardly_moves_or_is_absent():
    sigma = cavitation_index(np.array([0.0, 0.0]), np.array([0.0, 30.0]), 998.0, 101325.0, 2339.0,
                             water=np.array([1.0, 0.1]), cap=5.0)  # fmt: skip
    assert list(sigma) == [5.0, 5.0]  # still water, and a cell that is mostly air


def test_parallel_runs_with_a_changing_mesh_are_stitched_with_the_mesh_aware_tool():
    from easyfoam.casegen.setup import run_steps

    p = water()
    p.run.processors = 4
    assert run_steps(p)[-1].command == "reconstructPar"
    p.physics.adaptive_levels = 1
    assert [s.command for s in run_steps(p)][-2:] == ["reconstructParMesh", "reconstructPar"]
    assert [s.command for s in run_steps(p, resume=True, decomposed=True)][-2:] == [
        "reconstructParMesh", "reconstructPar -newTimes",
    ]  # fmt: skip


def test_cavitation_index_on_a_result_grid_reports_the_lowest_value_in_the_water():
    pv = pytest.importorskip("pyvista")
    from easyfoam.results import add_cavitation_index

    grid = pv.ImageData(dimensions=(4, 2, 2)).cast_to_unstructured_grid()  # three cells in a row
    grid.cell_data["p"] = np.array([0.0, 0.0, 0.0])
    grid.cell_data["U"] = np.array([[30.0, 0, 0], [2.0, 0, 0], [60.0, 0, 0]])
    grid.cell_data["alpha.water"] = np.array([1.0, 1.0, 0.0])  # the fastest cell is air
    lowest = add_cavitation_index(grid, 998.0, 101325.0, 2339.0)
    assert lowest == pytest.approx((101325.0 - 2339.0) / (0.5 * 998.0 * 900.0))
    assert list(grid.cell_data["cavitationIndex"]) == pytest.approx([lowest, 20.0, 20.0])
    assert add_cavitation_index(pv.ImageData(dimensions=(2, 2, 2)).cast_to_unstructured_grid(), 998.0, 1e5, 2e3) is None
