import pytest

from easyfoam.casegen.setup import (
    control_dict,
    decompose_dict,
    field_dicts,
    fv_schemes,
    fv_solution,
    run_steps,
    transport_properties,
    turbulence_inlet_values,
    turbulence_properties,
)
from easyfoam.foam.boundaryfile import Patch
from easyfoam.model import Boundary, Project

PATCHES = [
    Patch("inlet", "patch", 100, 0),
    Patch("outlet", "patch", 100, 100),
    Patch("sides", "patch", 400, 200),
    Patch("body", "wall", 900, 600),
    Patch("mid", "symmetry", 50, 1500),
]


def tunnel(solver="simpleFoam", turbulence="kOmegaSST"):
    p = Project(name="t")
    p.physics.solver = solver
    p.physics.turbulence = turbulence
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[10.0, 0.0, 0.0])
    p.boundaries["outlet"] = Boundary(kind="pressureOutlet", pressure=0.0)
    return p


def test_turbulence_inlet_values_follow_intensity_and_length_scale():
    k, epsilon, omega = turbulence_inlet_values(speed=10.0, intensity=0.05, length=0.1)
    assert k == pytest.approx(0.375)
    assert epsilon == pytest.approx(0.09**0.75 * 0.375**1.5 / 0.1)
    assert omega == pytest.approx(0.375**0.5 / (0.09**0.25 * 0.1))


def test_turbulence_values_stay_positive_when_the_flow_starts_at_rest():
    k, epsilon, omega = turbulence_inlet_values(speed=0.0, intensity=0.05, length=0.1)
    assert k > 0 and epsilon > 0 and omega > 0


def test_fields_written_depend_on_the_turbulence_model():
    assert list(field_dicts(tunnel(turbulence="laminar"), PATCHES)) == ["U", "p"]
    assert list(field_dicts(tunnel(turbulence="kEpsilon"), PATCHES)) == ["U", "p", "k", "epsilon", "nut"]
    assert list(field_dicts(tunnel(turbulence="kOmegaSST"), PATCHES)) == ["U", "p", "k", "omega", "nut"]


def test_every_field_has_an_entry_for_every_patch():
    for name, (_cls, data) in field_dicts(tunnel(), PATCHES).items():
        assert list(data["boundaryField"]) == [p.name for p in PATCHES], name


def test_velocity_inlet_fixes_velocity_and_turbulence_and_leaves_pressure_free():
    f = field_dicts(tunnel(), PATCHES)
    assert f["U"][1]["boundaryField"]["inlet"] == {"type": "fixedValue", "value": "uniform (10.0 0.0 0.0)"}
    assert f["p"][1]["boundaryField"]["inlet"] == {"type": "zeroGradient"}
    assert f["k"][1]["boundaryField"]["inlet"] == {"type": "fixedValue", "value": "uniform 0.375"}
    assert f["nut"][1]["boundaryField"]["inlet"] == {"type": "calculated", "value": "uniform 0"}


def test_pressure_outlet_fixes_pressure_and_prevents_backflow_from_bringing_in_velocity():
    f = field_dicts(tunnel(), PATCHES)
    assert f["p"][1]["boundaryField"]["outlet"] == {"type": "fixedValue", "value": "uniform 0.0"}
    assert f["U"][1]["boundaryField"]["outlet"] == {
        "type": "inletOutlet",
        "inletValue": "uniform (0 0 0)",
        "value": "uniform (0 0 0)",
    }
    assert f["k"][1]["boundaryField"]["outlet"]["type"] == "inletOutlet"


def test_wall_is_no_slip_with_wall_functions():
    f = field_dicts(tunnel(), PATCHES)
    assert f["U"][1]["boundaryField"]["body"] == {"type": "noSlip"}
    assert f["p"][1]["boundaryField"]["body"] == {"type": "zeroGradient"}
    assert f["k"][1]["boundaryField"]["body"]["type"] == "kqRWallFunction"
    assert f["omega"][1]["boundaryField"]["body"]["type"] == "omegaWallFunction"
    assert f["nut"][1]["boundaryField"]["body"]["type"] == "nutkWallFunction"
    assert field_dicts(tunnel(turbulence="kEpsilon"), PATCHES)["epsilon"][1]["boundaryField"]["body"][
        "type"
    ] == "epsilonWallFunction"


def test_moving_wall_carries_its_velocity():
    p = tunnel()
    p.boundaries["body"] = Boundary(kind="movingWall", velocity=[1.0, 0.0, 0.0])
    u = field_dicts(p, PATCHES)["U"][1]["boundaryField"]["body"]
    assert u == {"type": "fixedValue", "value": "uniform (1.0 0.0 0.0)"}


def test_slip_and_constraint_patches_use_the_same_condition_for_every_field():
    f = field_dicts(tunnel(), PATCHES)
    for name in f:
        assert f[name][1]["boundaryField"]["sides"] == {"type": "slip"}, name
        assert f[name][1]["boundaryField"]["mid"] == {"type": "symmetry"}, name


def test_internal_fields_start_from_the_initial_velocity_and_matching_turbulence():
    p = tunnel()
    p.physics.initial_velocity = [10.0, 0.0, 0.0]
    f = field_dicts(p, PATCHES)
    assert f["U"][0] == "volVectorField"
    assert f["U"][1]["dimensions"] == "[0 1 -1 0 0 0 0]"
    assert f["U"][1]["internalField"] == "uniform (10.0 0.0 0.0)"
    assert f["k"][1]["internalField"] == "uniform 0.375"
    assert f["p"][1]["dimensions"] == "[0 2 -2 0 0 0 0]"


def test_turbulence_scale_falls_back_to_the_fastest_inlet_when_the_start_is_at_rest():
    f = field_dicts(tunnel(), PATCHES)  # initial velocity is zero, inlet is 10 m/s
    assert f["k"][1]["internalField"] == "uniform 0.375"


def test_steady_control_dict_counts_iterations():
    p = tunnel()
    p.run.end_time, p.run.write_interval = 300, 50
    d = control_dict(p)
    assert d["application"] == "simpleFoam"
    assert (d["endTime"], d["deltaT"], d["writeControl"], d["writeInterval"]) == (300, 1, "timeStep", 50)
    assert "adjustTimeStep" not in d


def test_transient_control_dict_uses_seconds_and_courant_limited_steps():
    p = tunnel("pimpleFoam")
    p.run.end_time, p.run.delta_t, p.run.write_interval, p.run.max_courant = 2.0, 0.001, 0.1, 0.8
    d = control_dict(p)
    assert d["application"] == "pimpleFoam"
    assert (d["endTime"], d["deltaT"], d["writeControl"], d["writeInterval"]) == (2.0, 0.001, "adjustable", 0.1)
    assert d["adjustTimeStep"] is True and d["maxCo"] == 0.8


def test_schemes_are_steady_or_time_accurate_to_match_the_solver():
    assert fv_schemes(tunnel())["ddtSchemes"]["default"] == "steadyState"
    assert fv_schemes(tunnel("pimpleFoam"))["ddtSchemes"]["default"] == "Euler"
    assert fv_schemes(tunnel())["divSchemes"]["div(phi,U)"].startswith("bounded Gauss")
    assert not fv_schemes(tunnel("pimpleFoam"))["divSchemes"]["div(phi,U)"].startswith("bounded")


def test_accurate_numerics_use_second_order_convection_for_turbulence():
    p = tunnel()
    assert "upwind" in fv_schemes(p)["divSchemes"]["div(phi,k)"]
    p.physics.numerics = "accurate"
    assert "linearUpwind" in fv_schemes(p)["divSchemes"]["div(phi,k)"]


def test_solution_dict_has_the_algorithm_block_of_the_solver():
    steady = fv_solution(tunnel())
    assert "SIMPLE" in steady and "PIMPLE" not in steady
    assert steady["SIMPLE"]["residualControl"]["p"] == 0.0001
    transient = fv_solution(tunnel("pimpleFoam"))
    assert "PIMPLE" in transient and "SIMPLE" not in transient
    assert "pFinal" in transient["solvers"]


def test_material_and_turbulence_dictionaries():
    p = tunnel()
    p.physics.nu = 1e-06
    assert transport_properties(p) == {"transportModel": "Newtonian", "nu": 1e-06}
    assert turbulence_properties(p) == {
        "simulationType": "RAS",
        "RAS": {"RASModel": "kOmegaSST", "turbulence": True, "printCoeffs": True},
    }
    assert turbulence_properties(tunnel(turbulence="laminar")) == {"simulationType": "laminar"}


def test_serial_run_is_just_the_solver():
    assert [(s.name, s.command) for s in run_steps(tunnel())] == [("simpleFoam", "simpleFoam")]


def test_parallel_run_decomposes_solves_with_mpi_and_reconstructs():
    p = tunnel()
    p.run.processors = 4
    assert decompose_dict(p) == {"numberOfSubdomains": 4, "method": "scotch"}
    assert [(s.name, s.command) for s in run_steps(p)] == [
        ("decomposePar", "decomposePar -force"),
        ("simpleFoam", "mpirun -np 4 simpleFoam -parallel"),
        ("reconstructPar", "reconstructPar"),
    ]


def test_unknown_solver_is_reported_by_name():
    with pytest.raises(ValueError, match="notAFoam"):
        control_dict(tunnel("notAFoam"))
