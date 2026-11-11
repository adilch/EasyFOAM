"""v0.5: tailwater outlet, waves, discharge and water-level monitors, interIsoFoam, units and CAD import."""

import struct

import pytest

from easyfoam import casegen
from easyfoam.casegen.setup import control_dict, field_dicts, fv_solution, href_dict, wave_properties
from easyfoam.checks import project_issues
from easyfoam.foam.boundaryfile import Patch
from easyfoam.geometry import UNITS, import_stl, stl_bounds, stl_regions
from easyfoam.model import KINDS_FOR_TYPE, Boundary, Project
from easyfoam.solvers import SOLVERS
from tests.test_v02_core import ascii_stl, cube

PATCHES = [
    Patch("inlet", "patch", 10, 0),
    Patch("outlet", "patch", 10, 10),
    Patch("atmosphere", "patch", 40, 20),
    Patch("bed", "wall", 40, 60),
]


def channel(**outlet):
    p = Project(name="channel")
    p.physics.solver = "interFoam"
    p.physics.turbulence = "laminar"
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1e-06, 998.0
    p.physics.water_regions = [[0, 0, 0, 4, 0.1, 0.4]]
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.01)
    p.boundaries["outlet"] = Boundary(**(outlet or {"kind": "freeOutflow"}))
    return p


def fields(project):
    return {name: data["boundaryField"] for name, (_cls, data) in field_dicts(project, PATCHES).items()}


# --- tailwater outlet --------------------------------------------------------


def test_water_level_outlet_holds_ambient_pressure_relative_to_its_level():
    p = channel(kind="waterLevelOutlet", level=0.4)
    f = fields(p)
    assert f["p_rgh"]["outlet"] == {"type": "totalPressure", "p0": "uniform 0"}
    assert f["U"]["outlet"] == {"type": "pressureInletOutletVelocity", "value": "uniform (0 0 0)"}
    assert f["alpha.water"]["outlet"] == {"type": "zeroGradient"}
    # the hydrostatic reference height is what makes the pressure vanish at the tailwater level
    assert href_dict(p, PATCHES) == {"dimensions": "[0 1 0 0 0 0 0]", "value": 0.4}


def test_reference_height_is_only_written_when_a_level_outlet_exists():
    assert href_dict(channel(), PATCHES) is None
    files = casegen.setup_files(channel(), PATCHES)
    assert "constant/hRef" not in files and "constant/waveProperties" not in files
    files = casegen.setup_files(channel(kind="waterLevelOutlet", level=0.4), PATCHES)
    assert "class           uniformDimensionedScalarField;" in files["constant/hRef"]
    assert "value           0.4;" in files["constant/hRef"]


# --- waves -------------------------------------------------------------------


def waves():
    p = channel(kind="waveOutlet")
    p.boundaries["inlet"] = Boundary(kind="waveInlet", wave_height=0.05, wave_period=3.0, wave_model="StokesII")
    return p


def test_wave_maker_and_absorbing_boundary_use_the_wave_conditions():
    f = fields(waves())
    assert f["U"]["inlet"] == {"type": "waveVelocity", "value": "uniform (0 0 0)"}
    assert f["alpha.water"]["inlet"] == {"type": "waveAlpha", "value": "uniform 0"}
    assert f["p_rgh"]["inlet"] == {"type": "fixedFluxPressure", "value": "uniform 0"}
    assert f["U"]["outlet"] == {"type": "waveVelocity", "value": "uniform (0 0 0)"}
    assert f["alpha.water"]["outlet"] == {"type": "zeroGradient"}


def test_wave_properties_describe_each_wave_boundary():
    assert wave_properties(waves(), PATCHES) == {
        "inlet": {
            "alpha": "alpha.water",
            "waveModel": "StokesII",
            "nPaddle": 1,
            "waveHeight": 0.05,
            "waveAngle": 0.0,
            "rampTime": 3.0,
            "activeAbsorption": True,
            "wavePeriod": 3.0,
        },
        "outlet": {"alpha": "alpha.water", "waveModel": "shallowWaterAbsorption", "nPaddle": 1},
    }
    assert wave_properties(channel(), PATCHES) is None
    assert "constant/waveProperties" in casegen.setup_files(waves(), PATCHES)


def test_hydraulic_only_conditions_are_flagged_in_single_fluid_flow():
    p = Project(name="x")
    p.boundaries["inlet"] = Boundary(kind="waveInlet")
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=1.0)
    issues = [(i.step, i.level) for i in project_issues(p, PATCHES, True)]
    assert issues.count(("Boundaries", "error")) == 2
    assert {"waterLevelOutlet", "waveInlet", "waveOutlet"} <= set(KINDS_FOR_TYPE["patch"])
    field_dicts(p, PATCHES)  # the files can still be written


# --- monitors ----------------------------------------------------------------


def test_discharge_monitor_sums_the_water_flux_through_a_boundary():
    p = channel()
    p.flow_monitors = ["outlet", "ghost"]
    functions = control_dict(p, PATCHES)["functions"]
    assert "flow_ghost" not in functions
    assert functions["flow_outlet"] == {
        "type": "surfaceFieldValue",
        "libs": ["fieldFunctionObjects"],
        "writeControl": "timeStep",
        "writeInterval": 1,
        "log": False,
        "writeFields": False,
        "regionType": "patch",
        "name": "outlet",
        "operation": "weightedSum",
        "weightField": "alpha.water",
        "fields": ["phi"],
    }


def test_discharge_monitor_in_single_fluid_flow_is_a_plain_sum():
    p = Project(name="x")
    p.flow_monitors = ["outlet"]
    function = control_dict(p, PATCHES)["functions"]["flow_outlet"]
    assert function["operation"] == "sum" and "weightField" not in function


def test_probe_points_double_as_water_level_gauges_in_free_surface_runs():
    p = channel()
    p.probes = [[1.0, 0.05, 0.2], [3.0, 0.05, 0.2]]
    gauge = control_dict(p, PATCHES)["functions"]["waterLevel"]
    assert gauge["type"] == "interfaceHeight" and gauge["alpha"] == "alpha.water"
    assert gauge["locations"] == [[1.0, 0.05, 0.2], [3.0, 0.05, 0.2]]
    assert "direction" not in gauge  # measured along gravity, which is the default
    single = Project(name="x")
    single.probes = [[1.0, 0.0, 0.0]]
    assert "waterLevel" not in control_dict(single, PATCHES)["functions"]


# --- sharp interface ---------------------------------------------------------


def test_sharp_interface_solver_uses_geometric_interface_advection():
    assert SOLVERS["interIsoFoam"].multiphase and not SOLVERS["interIsoFoam"].steady
    p = channel()
    p.physics.solver = "interIsoFoam"
    alpha = fv_solution(p)["solvers"]['"alpha.water.*"']
    assert alpha["reconstructionScheme"] == "isoAlpha" and alpha["nAlphaBounds"] == 3
    assert "MULESCorr" not in alpha
    assert control_dict(p)["application"] == "interIsoFoam"
    assert list(field_dicts(p, PATCHES))[:3] == ["U", "p_rgh", "alpha.water"]


# --- units on import ---------------------------------------------------------


def test_units_are_scale_factors_to_metres():
    assert UNITS == {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254}


def test_an_ascii_stl_is_scaled_on_import_and_keeps_its_regions(tmp_path):
    src = tmp_path / "part.stl"
    src.write_text(ascii_stl({"inlet": cube(scale=(1000, 200, 200))[:2], "wall": cube(scale=(1000, 200, 200))[2:]}))
    shape = import_stl(tmp_path / "case", src, scale=UNITS["mm"])
    copied = tmp_path / "case" / "constant" / "triSurface" / "part.stl"
    assert sum(stl_bounds(copied), []) == pytest.approx([0, 0, 0, 1.0, 0.2, 0.2])
    assert stl_regions(copied) == ["inlet", "wall"] and shape.regions == {"inlet": "wall", "wall": "wall"}


def test_a_binary_stl_is_scaled_on_import(tmp_path):
    data = b"binary".ljust(80, b" ") + struct.pack("<I", 1) + struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 25.4, 0, 0, 0, 50.8, 0, 0)
    src = tmp_path / "b.stl"
    src.write_bytes(data)
    import_stl(tmp_path / "case", src, scale=UNITS["mm"])  # 25.4 mm is one inch
    lo, hi = stl_bounds(tmp_path / "case" / "constant" / "triSurface" / "b.stl")
    assert hi == pytest.approx([0.0254, 0.0508, 0.0], abs=1e-7)


# --- CAD import (needs the optional gmsh package) ------------------------------


def step_box(path, size=(2.0, 1.0, 0.5)):
    gmsh = pytest.importorskip("gmsh")
    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.addBox(0, 0, 0, *size)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()


def test_a_step_file_becomes_a_closed_surface(tmp_path):
    from easyfoam.geometry import import_cad, interior_point, stl_triangles

    step_box(tmp_path / "block.step")
    shape = import_cad(tmp_path / "case", tmp_path / "block.step")
    stl = tmp_path / "case" / "constant" / "triSurface" / shape.file
    assert (shape.name, shape.kind) == ("block", "stl")
    assert sum(stl_bounds(stl), []) == pytest.approx([0, 0, 0, 2.0, 1.0, 0.5], abs=1e-6)
    x, y, z = interior_point(stl_triangles(stl))  # raises if the surface is not watertight
    assert 0 < x < 2 and 0 < y < 1 and 0 < z < 0.5


def test_a_step_file_in_millimetres_and_with_one_region_per_face(tmp_path):
    from easyfoam.geometry import import_cad

    step_box(tmp_path / "block.step", size=(2000, 1000, 500))
    shape = import_cad(tmp_path / "case", tmp_path / "block.step", scale=UNITS["mm"], faces_as_regions=True)
    stl = tmp_path / "case" / "constant" / "triSurface" / shape.file
    assert sum(stl_bounds(stl), []) == pytest.approx([0, 0, 0, 2.0, 1.0, 0.5], abs=1e-6)
    assert len(shape.regions) == 6 and set(shape.regions.values()) == {"wall"}


def test_cad_import_without_the_cad_package_explains_what_to_install(tmp_path, monkeypatch):
    import builtins

    from easyfoam.geometry import import_cad

    real_import = builtins.__import__

    def no_gmsh(name, *args, **kwargs):
        if name == "gmsh":
            raise ImportError("no gmsh")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_gmsh)
    (tmp_path / "x.step").write_text("ISO-10303-21;")
    with pytest.raises(RuntimeError, match="gmsh"):
        import_cad(tmp_path / "case", tmp_path / "x.step")


# --- reading the monitor files (formats as written by OpenFOAM v2506) ---------

DISCHARGE = (
    "# Region type : patch outlet\n# Faces         : 20\n# Weight field  : alpha.water\n"
    "# Time          \tweightedSum(phi)\n"
    "0.00119976      \t-5.09049651e-10\n5.97124         \t1.19138313e-02\n6               \t1.16762407e-02\n"
)
HEIGHT = (
    "# Location 0    : (1.00000000e+00 5.00000000e-02 2.00000000e-01)\n"
    "# hB            : Interface height above the boundary\n"
    "# Location      0                                 1                                 \n"
    "# Time          hB               hL               hB               hL               \n"
    "0.00119976\t4.00000000e-01   -4.00000000e-01  4.00000000e-01   -4.00000000e-01  \n"
    "6\t3.66173151e-01   -4.33826849e-01  3.92632556e-01   -4.07367444e-01  \n"
)


def test_discharge_history_is_read_per_boundary(tmp_path):
    from easyfoam.foam.monitors import read_discharge

    for patch, sign in (("outlet", 1.0), ("inlet", -1.0)):
        folder = tmp_path / "postProcessing" / f"flow_{patch}" / "0"
        folder.mkdir(parents=True)
        (folder / "surfaceFieldValue.dat").write_text(DISCHARGE if sign > 0 else DISCHARGE.replace("\t1.", "\t-1."))
    data = read_discharge(tmp_path)
    assert set(data) == {"outlet", "inlet"}
    times, values = data["outlet"]
    assert times == [0.00119976, 5.97124, 6.0]
    assert values[-1] == pytest.approx(0.0116762407)
    assert data["inlet"][1][-1] == pytest.approx(-0.0116762407)  # negative: into the domain
    assert read_discharge(tmp_path / "nowhere") == {}


def test_water_depth_history_is_read_per_gauge(tmp_path):
    from easyfoam.foam.monitors import read_water_levels

    folder = tmp_path / "postProcessing" / "waterLevel" / "0"
    folder.mkdir(parents=True)
    (folder / "height.dat").write_text(HEIGHT)
    times, depths = read_water_levels(tmp_path)
    assert times == [0.00119976, 6.0]
    assert depths == [[0.4, 0.366173151], [0.4, 0.392632556]]  # depth above the bed, not the offset columns
    assert read_water_levels(tmp_path / "nowhere") == ([], [])
