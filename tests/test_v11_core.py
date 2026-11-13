"""v0.11: tracer tests (residence time, T10, baffling factor), decaying tracers and water age."""

import math

import numpy as np
import pytest

from easyfoam import tracertest as tt
from easyfoam.casegen.setup import control_dict, field_dicts
from easyfoam.foam.boundaryfile import Patch
from easyfoam.model import Boundary, Project, Tracer

PATCHES = [Patch("inlet", "patch", 1, 0), Patch("outlet", "patch", 1, 1), Patch("walls", "wall", 1, 2)]


def tank(turbulence="kOmegaSST"):
    p = Project(name="tank")
    p.physics.turbulence = turbulence
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1.0e-06, 998.0
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[0.1, 0, 0], tracer_value=2.0)
    p.boundaries["outlet"] = Boundary(kind="pressureOutlet")
    p.flow_monitors = ["outlet"]
    return p


# --- tracers that decay, and the age of the water ---------------------------------------


def test_a_decaying_tracer_gets_a_first_order_sink():
    p = tank()
    p.tracers = [Tracer("chlorine", 1e-9, decay=0.5 / 3600)]
    function = control_dict(p, PATCHES)["functions"]["tracer_chlorine"]
    source = function["fvOptions"]["chlorineSource"]
    assert source["type"] == "scalarSemiImplicitSource" and source["volumeMode"] == "specific"
    assert source["sources"] == {"chlorine": [0, pytest.approx(-0.5 / 3600)]}
    assert function["alphaDt"] == pytest.approx(1 / 0.7)  # turbulent mixing
    inlet = field_dicts(p, PATCHES)["chlorine"][1]["boundaryField"]["inlet"]
    assert inlet == {"type": "fixedValue", "value": "uniform 2"}


def test_the_age_of_the_water_grows_one_second_per_second_and_enters_at_zero():
    p = tank()
    p.tracers = [Tracer("age", 1e-9, kind="age")]
    function = control_dict(p, PATCHES)["functions"]["tracer_age"]
    assert function["fvOptions"]["ageSource"]["sources"] == {"age": [1, 0]} and function["bounded01"] is False
    assert field_dicts(p, PATCHES)["age"][1]["boundaryField"]["inlet"]["value"] == "uniform 0"


def test_water_drawn_back_in_at_an_outlet_keeps_its_own_age_and_concentration():
    p = tank()
    p.tracers = [Tracer("age", 1e-9, kind="age"), Tracer("chlorine", 1e-9)]
    patches = [*PATCHES, Patch("top", "patch", 1, 3)]
    p.boundaries["top"] = Boundary(kind="atmosphere")
    for name in ("age", "chlorine"):
        fields = field_dicts(p, patches)[name][1]["boundaryField"]
        # a fixed 0 on backflow diluted the outflow: a tracer test never reached 1
        assert fields["outlet"] == {"type": "zeroGradient"}
        assert fields["top"]["type"] == "inletOutlet"  # air coming in from above carries none


@pytest.mark.parametrize(
    ("solver", "scheme"),
    [("simpleFoam", "bounded Gauss upwind"), ("pimpleFoam", "Gauss limitedLinear 1"), ("interFoam", "Gauss limitedLinear 1")],
)
def test_tracers_are_never_relaxed_and_are_solved_in_full(solver, scheme):
    from easyfoam.casegen.setup import fv_schemes, fv_solution

    p = tank()
    p.physics.solver = solver
    p.tracers = [Tracer("age", 1e-9, kind="age"), Tracer("dye", 1e-9)]
    solution, schemes = fv_solution(p), fv_schemes(p)
    for name in ("age", "dye"):
        # 0 skips OpenFOAM's relaxation; even 1 adds a lagged correction that biased the age by 8 %
        assert solution["relaxationFactors"]["equations"][name] == 0
        assert solution["solvers"][name]["relTol"] == 0 and solution["solvers"][name]["tolerance"] <= 1e-9
        # a steady solve settles only with a linear scheme; a transient one keeps the sharper limitedLinear
        assert schemes["divSchemes"][f"div(phi,{name})"] == scheme
    assert solution["relaxationFactors"]["equations"]['".*"'] > 0  # the flow itself is still relaxed


def test_a_decaying_tracer_is_relaxed_in_steady_runs_only_and_more_for_a_fast_decay():
    from easyfoam.casegen.setup import fv_solution

    p = tank()
    p.tracers = [Tracer("chlorine", 1e-9, decay=0.3 / 3600), Tracer("fast", 1e-9, decay=0.01), Tracer("dye", 1e-9)]
    p.physics.solver = "simpleFoam"
    factors = fv_solution(p)["relaxationFactors"]["equations"]
    # OpenFOAM applies a decay explicitly: unrelaxed, a steady run blew up in the dead zones of a tank
    assert factors["chlorine"] == pytest.approx(0.9) and factors["fast"] == pytest.approx(1 / 11)
    assert factors["dye"] == 0
    p.physics.solver = "pimpleFoam"  # each time step is short against the decay
    assert all(fv_solution(p)["relaxationFactors"]["equations"][t.name] == 0 for t in p.tracers)


def test_each_tracer_can_enter_with_its_own_concentration_and_is_recorded_at_the_outlet():
    p = tank(turbulence="laminar")
    p.tracers = [Tracer("chlorine", 1e-9), Tracer("dye", 1e-9)]
    p.boundaries["inlet"].tracer_values = {"dye": 5.0}
    fields = field_dicts(p, PATCHES)
    assert fields["chlorine"][1]["boundaryField"]["inlet"]["value"] == "uniform 2"  # the common value
    assert fields["dye"][1]["boundaryField"]["inlet"]["value"] == "uniform 5"
    functions = control_dict(p, PATCHES)["functions"]
    assert functions["tracer_dye"]["D"] == 1e-9  # laminar: molecular diffusion only
    out = functions["tracerOut_outlet"]
    assert out["operation"] == "weightedAverage" and out["weightFields"] == ["phi"]
    assert out["fields"] == ["chlorine", "dye"]


def test_outlet_concentrations_are_read_back(tmp_path):
    from easyfoam.foam.monitors import read_outlet_tracers

    folder = tmp_path / "postProcessing" / "tracerOut_outlet" / "0"
    folder.mkdir(parents=True)
    (folder / "surfaceFieldValue.dat").write_text("# Time weightedAverage(chlorine) weightedAverage(dye)\n"
                                                  "1 0.5 0.1\n2 0.6 0.2\n")  # fmt: skip
    assert read_outlet_tracers(tmp_path) == {"outlet": ([1.0, 2.0], [[0.5, 0.6], [0.1, 0.2]])}


# --- residence-time distributions --------------------------------------------------------


def test_a_perfectly_mixed_tank_has_a_baffling_factor_of_about_a_tenth():
    tau = 400.0
    t = np.linspace(0, 8 * tau, 4001)
    result = tt.residence_times(t, 1 - np.exp(-t / tau), "step", tau)
    assert result.t10 == pytest.approx(-tau * math.log(0.9), rel=1e-3)
    assert result.baffling_factor == pytest.approx(0.105, abs=0.002)
    assert result.mean == pytest.approx(tau, rel=0.01) and result.complete > 0.99
    assert result.morrill == pytest.approx(math.log(0.1) / math.log(0.9), rel=0.01)
    assert "unbaffled" in " ".join(result.lines())


def test_plug_flow_has_a_baffling_factor_close_to_one():
    tau = 100.0
    t = np.linspace(0, 300, 3001)
    f = 0.5 * (1 + np.tanh((t - tau) / 3.0))  # a sharp front, slightly spread
    result = tt.residence_times(t, f, "step", tau)
    assert result.baffling_factor == pytest.approx(0.94, abs=0.03) and result.morrill < 1.2
    assert "near plug flow" in " ".join(result.lines())


def test_a_pulse_test_recovers_the_dose_and_the_mean_residence_time():
    tau, width = 400.0, 8.0
    t = np.linspace(0, 10 * tau, 8001)
    c = width * np.exp(-np.clip(t - width / 2, 0, None) / tau) / tau  # mixed tank, dose = width
    result = tt.residence_times(t, c, "pulse", tau, pulse=width)
    assert result.complete == pytest.approx(1.0, abs=0.01)
    assert result.mean == pytest.approx(tau, rel=0.02)
    assert result.t10 == pytest.approx(-tau * math.log(0.9), rel=0.1)  # a mixed tank answers at once


def test_a_test_stopped_too_early_says_so():
    tau = 400.0
    t = np.linspace(0, tau, 401)
    result = tt.residence_times(t, 1 - np.exp(-t / tau), "step", tau)
    assert "washout still to come" in " ".join(result.lines())
    assert result.mean == pytest.approx(tau, rel=0.01)  # the exponential tail is added


def test_the_test_tells_how_much_of_a_decaying_substance_is_left_at_the_outlet():
    tau, k = 400.0, 1 / 800.0
    mixed = tt.residence_times(np.linspace(0, 3 * tau, 3001), 1 - np.exp(-np.linspace(0, 3 * tau, 3001) / tau), "step", tau)
    assert mixed.remaining(k) == pytest.approx(1 / (1 + k * tau), rel=0.005)  # stopped at 95 %: the tail counts
    assert mixed.remaining(0) == 1.0
    t = np.linspace(0, 300, 3001)
    plug = tt.residence_times(t, 0.5 * (1 + np.tanh((t - 100) / 3.0)), "step", 100)
    assert plug.remaining(k) == pytest.approx(math.exp(-k * 100), rel=0.005)
    width = 8.0
    t = np.linspace(0, 10 * tau, 8001)
    inside = np.where(t < width, 1 - np.exp(-t / tau), (math.exp(width / tau) - 1) * np.exp(-t / tau))
    pulse = tt.residence_times(t, inside, "pulse", tau, pulse=width)  # the exact answer of a mixed tank to a dose
    assert pulse.remaining(k) == pytest.approx(1 / (1 + k * tau), rel=0.005)


def test_the_share_left_is_reported_for_each_decaying_tracer():
    p = tank()
    p.tracers = [Tracer("age", 1e-9, kind="age"), Tracer("chlorine", 1e-9, decay=0.3 / 3600)]
    tau = 3600.0
    t = np.linspace(0, 8 * tau, 4001)
    result = tt.residence_times(t, 1 - np.exp(-t / tau), "step", tau)
    (line,) = tt.decay_lines(result, p, "inlet")
    share = 1 / (1 + 0.3)
    assert line.startswith("chlorine, decaying at 0.3 per hour") and f"{100 * share:.1f} %" in line
    assert f"({2 * share:.3g} of the 2 dosed)" in line  # the inlet doses 2 mg/L


def test_inlet_doses_for_step_and_pulse():
    assert tt.inlet_dose("step", 5) == "table ((0 1) (1e9 1))"
    assert tt.inlet_dose("pulse", 8) == "table ((0 1) (8 1) (8.008 0))"


# --- the tracer-test case ----------------------------------------------------------------


def finished_steady_case(root):
    """The folders a finished steady run leaves behind, without running it."""
    p = tank()
    p.save(root)
    (root / "constant" / "polyMesh").mkdir(parents=True)
    (root / "constant" / "polyMesh" / "boundary").write_text(
        "FoamFile { version 2.0; format ascii; class polyBoundaryMesh; object boundary; }\n3\n(\n"
        "inlet { type patch; nFaces 4; startFace 10; }\n"
        "outlet { type patch; nFaces 4; startFace 14; }\n"
        "walls { type wall; inGroups 1(wall); nFaces 20; startFace 18; }\n)\n"
    )
    (root / "constant" / "transportProperties").write_text("nu 1e-06;\n")
    for time in ("500", "1000"):
        (root / time).mkdir()
        for name in ("U", "p", "phi", "nut", "k", "omega", "wallShearStress"):
            (root / time / name).write_text(f"// {name} at {time}\n")
    return p


def test_the_tracer_test_freezes_the_steady_flow_in_a_case_of_its_own(tmp_path):
    p = finished_steady_case(tmp_path)
    test = tt.TestSettings(inlet="inlet", outlet="outlet", kind="step")
    target, steps = tt.prepare(tmp_path, p, test, residence_time=400.0)
    assert target == tmp_path / "tracer-test" and [s.name for s in steps] == ["pimpleFoam"]
    assert (target / "0" / "U").read_text() == "// U at 1000\n"  # the latest steady result
    assert not (target / "0" / "wallShearStress").exists()  # only what the flow needs
    control = (target / "system" / "controlDict").read_text()
    assert "pimpleFoam" in control and "endTime         1200" in control  # three residence times
    assert "tracerOut_outlet" in control and "weightedAverage" in control
    solution = (target / "system" / "fvSolution").read_text()
    assert "nCorrectors     0" in solution and "momentumPredictor false" in solution
    assert "turbulence      false" in (target / "constant" / "turbulenceProperties").read_text()
    tracer = (target / "0" / "rtd").read_text()
    assert "uniformFixedValue" in tracer and "table ((0 1) (1e9 1))" in tracer
    assert (tmp_path / "1000" / "U").exists()  # the steady results are left alone
    # the settings are kept beside the results, so they can be shown after the project is reopened
    settings, theoretical, pulse = tt.load_test(tmp_path)
    assert (settings.inlet, settings.outlet, settings.kind, theoretical) == ("inlet", "outlet", "step", 400.0)
    assert pulse == pytest.approx(8.0)  # a fiftieth of V/Q
    assert tt.load_test(tmp_path / "elsewhere") is None


def test_the_volume_and_inflow_of_a_tank_are_measured_from_the_result():
    pv = pytest.importorskip("pyvista")
    from easyfoam.results import CaseData

    grid = pv.ImageData(dimensions=(11, 5, 3), spacing=(0.5, 0.5, 0.5)).cast_to_unstructured_grid()  # 5 x 2 x 1 m
    inlet = pv.PolyData(np.array([[0, 0, 0], [0, 0, 1.0], [0, 2.0, 1.0], [0, 2.0, 0]], float), np.array([4, 0, 1, 2, 3]))
    inlet.cell_data["U"] = np.array([[0.05, 0.0, 0.0]])
    volume, flow = tt.volume_and_flow(CaseData(grid, {"inlet": inlet}), tank(), ["inlet"])
    assert volume == pytest.approx(10.0) and flow == pytest.approx(0.05 * 2.0)  # the face points out of the tank (-x)
