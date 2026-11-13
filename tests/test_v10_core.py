"""v0.10: bed roughness (Manning's n or sand-grain height), hydrographs and rating curves."""

import pytest

from easyfoam.casegen.setup import field_dicts
from easyfoam.checks import project_issues
from easyfoam.foam.boundaryfile import Patch
from easyfoam.model import Boundary, Project, ks_from_manning, manning_from_ks, roughness_height

PATCHES = [Patch("inlet", "patch", 1, 0), Patch("outlet", "patch", 1, 1), Patch("bed", "wall", 1, 2),
           Patch("atmosphere", "patch", 1, 3)]  # fmt: skip


def channel(turbulence="kOmegaSST", solver="interFoam"):
    p = Project(name="channel")
    p.physics.solver, p.physics.turbulence = solver, turbulence
    p.physics.material, p.physics.nu, p.physics.rho = "water", 1.0e-06, 998.0
    p.boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=0.01)
    p.boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=0.3)
    p.boundaries["atmosphere"] = Boundary(kind="atmosphere")
    p.boundaries["bed"] = Boundary(kind="wall", roughness="manning", manning=0.017)
    return p


def test_manning_n_and_sand_grain_height_convert_both_ways_with_strickler():
    assert ks_from_manning(0.013) == pytest.approx((8.25 * 9.81**0.5 * 0.013) ** 6)
    assert ks_from_manning(0.013) * 1000 == pytest.approx(1.4, abs=0.1)  # finished concrete: about 1.4 mm
    assert manning_from_ks(ks_from_manning(0.03)) == pytest.approx(0.03)
    assert ks_from_manning(0) == 0 and manning_from_ks(0) == 0


def test_the_roughness_height_of_a_boundary_follows_the_chosen_way_of_giving_it():
    assert roughness_height(Boundary(kind="wall")) == 0.0
    assert roughness_height(Boundary(kind="wall", roughness="ks", ks=0.002)) == 0.002
    assert roughness_height(Boundary(kind="wall", roughness="manning", manning=0.017)) == pytest.approx(
        ks_from_manning(0.017)
    )
    assert roughness_height(Boundary(kind="slip", roughness="ks", ks=0.002)) == 0.0  # only walls are rough


def test_a_rough_bed_gets_the_rough_wall_function_and_a_smooth_wall_keeps_the_usual_one():
    p = channel()
    nut = field_dicts(p, PATCHES)["nut"][1]["boundaryField"]
    ks = ks_from_manning(0.017)
    assert nut["bed"]["type"] == "nutkRoughWallFunction"
    assert nut["bed"]["Ks"] == f"uniform {ks:g}" and nut["bed"]["Cs"] == "uniform 0.5"
    p.boundaries["bed"].roughness = "smooth"
    assert field_dicts(p, PATCHES)["nut"][1]["boundaryField"]["bed"]["type"] == "nutkWallFunction"


def test_spalart_allmaras_uses_the_velocity_based_rough_wall_function():
    p = channel(turbulence="SpalartAllmaras", solver="simpleFoam")
    entry = field_dicts(p, PATCHES)["nut"][1]["boundaryField"]["bed"]
    assert entry["type"] == "nutURoughWallFunction"
    assert entry["roughnessHeight"] == pytest.approx(ks_from_manning(0.017))


def test_roughness_without_wall_functions_is_reported_as_ignored():
    def warnings(project):
        return [i.text for i in project_issues(project, PATCHES, True) if i.level == "warning"]

    assert not any("Roughness" in w for w in warnings(channel()))
    assert any("Roughness on bed" in w for w in warnings(channel(turbulence="laminar")))
    lowre = channel()
    lowre.physics.wall_treatment = "lowRe"
    assert any("Roughness on bed" in w for w in warnings(lowre))


def test_roughness_is_saved_with_the_project(tmp_path):
    p = channel()
    p.save(tmp_path)
    bed = Project.load(tmp_path).boundaries["bed"]
    assert (bed.roughness, bed.manning) == ("manning", 0.017)


# --- hydrographs and a tailwater that changes in time ---------------------------------


def test_a_time_series_becomes_an_openfoam_table_and_can_be_read_back():
    from easyfoam.model import series_entry, series_value

    series = [[0, 0.01], [10, 0.05], [30, 0.02]]
    assert series_entry(series) == "table ((0 0.01) (10 0.05) (30 0.02))"
    assert series_value(series, -1) == 0.01 and series_value(series, 5) == pytest.approx(0.03)
    assert series_value(series, 20) == pytest.approx(0.035) and series_value(series, 99) == 0.02


def test_an_inflow_hydrograph_drives_the_flow_rate_inlet():
    p = channel()
    p.boundaries["inlet"].flow_series = [[0, 0.01], [60, 0.04]]
    u = field_dicts(p, PATCHES)["U"][1]["boundaryField"]["inlet"]
    value = u["uniformValue"]
    assert value["functions<scalar>"]["inflow"] == {"type": "table", "values": [[0.0, 0.01], [60.0, 0.04]]}
    assert "fn:inflow(time())" in str(value["expression"])
    single = channel(solver="simpleFoam")
    single.boundaries["inlet"].flow_series = [[0, 0.01], [60, 0.04]]
    entry = field_dicts(single, PATCHES)["U"][1]["boundaryField"]["inlet"]
    assert entry["volumetricFlowRate"] == "table ((0 0.01) (60 0.04))"


def test_a_tailwater_that_changes_in_time_follows_the_density_next_to_each_face():
    p = channel()
    p.boundaries["outlet"].level_series = [[20, 0.40], [0, 0.30]]
    fields = field_dicts(p, PATCHES)
    entry = fields["p_rgh"][1]["boundaryField"]["outlet"]
    assert entry["type"] == "uniformFixedValue" and entry["value"] == "uniform 0"
    value = entry["uniformValue"]
    assert value["type"] == "expression"
    assert value["functions<scalar>"]["tailwater"] == {"type": "table", "values": [[0.0, 0.3], [20.0, 0.4]]}
    # rho g (L - hRef), with rho of the cell beside each face: water feels the tailwater, air stays at ambient
    assert str(value["expression"]) == '"internalField(rho)*9.81*(fn:tailwater(time()) - (0.3))"'
    from easyfoam.casegen.freesurface import href_dict

    assert href_dict(p, PATCHES)["value"] == 0.30  # measured from the first level
    assert fields["alpha.water"][1]["boundaryField"]["outlet"] == {"type": "zeroGradient"}
    p.boundaries["outlet"].level_series = []  # a fixed level keeps its plain ambient pressure
    assert field_dicts(p, PATCHES)["p_rgh"][1]["boundaryField"]["outlet"] == {"type": "totalPressure", "p0": "uniform 0"}


# --- rating curves ----------------------------------------------------------------------


def test_a_rating_run_holds_each_discharge_with_short_ramps_between():
    from easyfoam.model import staircase

    assert staircase([0.02, 0.04, 0.06], hold=10, ramp=1) == [
        [0.0, 0.02], [10, 0.02], [11, 0.04], [20, 0.04], [21, 0.06],
    ]  # fmt: skip


def test_the_rating_curve_recovers_the_weir_coefficient_and_flags_levels_that_have_not_settled():
    import numpy as np

    from easyfoam.hydraulics import rating_points

    crest, width, c = 0.5, 0.5, 1.7
    discharges = [0.02, 0.04, 0.06]
    t = np.linspace(0, 30, 301)
    k = np.minimum((t // 10).astype(int), 2)
    level = crest + (np.array(discharges)[k] / (c * width)) ** (2 / 3)
    level[t > 25] += 0.01 * (t[t > 25] - 25)  # the last level is still rising
    points = rating_points(t, level, discharges, hold=10, crest=crest, width=width,
                           out_times=t, outflow=np.array(discharges)[k])  # fmt: skip
    assert [p.discharge for p in points] == discharges
    assert points[0].coefficient == pytest.approx(c, rel=1e-6) and points[1].coefficient == pytest.approx(c, rel=1e-6)
    assert points[0].discharge_coefficient == pytest.approx(c / (2 / 3 * (2 * 9.81) ** 0.5))
    assert points[0].steady and points[1].steady and not points[2].steady


def test_the_crest_is_the_top_of_the_highest_structure_unless_set():
    from easyfoam.examples import weir
    from easyfoam.hydraulics import crest_level

    p = weir("weir")
    assert crest_level(p, None) == pytest.approx(0.51)
    p.rating.crest = 0.6
    assert crest_level(p, None) == 0.6


def test_the_level_elevation_at_a_gauge_is_the_gauge_point_plus_the_height_above_it(tmp_path):
    from easyfoam.foam.monitors import read_level_elevations

    folder = tmp_path / "postProcessing" / "waterLevel" / "0"
    folder.mkdir(parents=True)
    (folder / "height.dat").write_text("# Time hB hL\n0 0.6 0.3 0.2 0.0\n1 0.62 0.32 0.21 0.01\n")
    times, levels = read_level_elevations(tmp_path, [[1, 0, 0.3], [5, 0, 0.2]])
    assert times == [0.0, 1.0] and levels[0] == pytest.approx([0.6, 0.62]) and levels[1] == pytest.approx([0.2, 0.21])
