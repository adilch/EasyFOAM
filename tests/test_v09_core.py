"""v0.9: hydraulic results (long section, jumps, control sections, pressures, loads, bed shear)."""

import math

import numpy as np
import pytest

from easyfoam import hydraulics as hy
from easyfoam.model import Project

pv = pytest.importorskip("pyvista")

RHO, G = 998.0, 9.81


def channel_project(cells=(50, 4, 40), size=(10.0, 1.0, 1.0)):
    p = Project(name="channel")
    p.physics.solver = "interFoam"
    p.physics.rho = RHO
    p.mesh.base.min, p.mesh.base.max, p.mesh.base.cells = [0, 0, 0], list(size), list(cells)
    return p


def channel_result(project, depth, q, href=0.0):
    """A result with the water surface at ``depth(x)``, discharge ``q`` per metre and hydrostatic pressure."""
    from easyfoam.results import CaseData

    base = project.mesh.base
    spacing = [(hi - lo) / n for lo, hi, n in zip(base.min, base.max, base.cells)]
    image = pv.ImageData(dimensions=[n + 1 for n in base.cells], spacing=spacing, origin=base.min)
    grid = image.cast_to_unstructured_grid()
    centres = np.asarray(grid.cell_centers().points)
    h = depth(centres[:, 0])
    dz = spacing[2]
    alpha = np.clip((h - (centres[:, 2] - dz / 2)) / dz, 0.0, 1.0)
    velocity = np.zeros((grid.n_cells, 3))
    velocity[:, 0] = np.where(alpha > 0, q / h, 0.0)
    grid.cell_data["alpha.water"] = alpha
    grid.cell_data["U"] = velocity
    # p_rgh as the solver defines it: static pressure plus the weight of the local mixture above hRef
    static = RHO * G * np.clip(h - centres[:, 2], 0.0, None)
    mixture = alpha * RHO + (1.0 - alpha) * project.physics.air_rho
    grid.cell_data["p_rgh"] = static + mixture * G * (centres[:, 2] - href)
    return CaseData(grid, {})


# --- the long section ---------------------------------------------------------------


def test_long_section_recovers_the_water_surface_discharge_froude_number_and_energy():
    p = channel_project()

    def depth(x):
        return 0.5 - 0.02 * x

    section = hy.long_section(channel_result(p, depth, q=0.2), p)
    x = section.chainage
    assert len(x) == 50 and x[0] == pytest.approx(0.1)  # one station per base cell, at its centre
    assert np.allclose(section.bed, 0.0)
    assert np.allclose(section.water_level, depth(x), atol=1e-9)
    assert np.allclose(section.discharge, 0.2, rtol=1e-9)  # 0.2 m²/s over the 1 m width
    assert np.allclose(section.top_width, 1.0) and np.allclose(section.unit_discharge, 0.2)
    v = 0.2 / depth(x)
    assert np.allclose(section.velocity, v)
    assert np.allclose(section.froude, v / np.sqrt(G * depth(x)))
    assert np.allclose(section.energy_level, depth(x) + v**2 / (2 * G))
    assert np.allclose(section.total_head, section.energy_level, atol=2e-3)  # hydrostatic, uniform velocity
    assert np.allclose(section.coriolis, 1.0)


def test_the_reference_level_of_a_tailwater_outlet_is_allowed_for_in_the_total_head(monkeypatch):
    p = channel_project()
    monkeypatch.setattr(hy, "reference_level", lambda project, case_dir: 0.3)
    section = hy.long_section(channel_result(p, lambda x: 0.4 + 0 * x, q=0.1, href=0.3), p)
    assert np.allclose(section.total_head, 0.4 + (0.1 / 0.4) ** 2 / (2 * G), atol=2e-3)


def test_a_slice_one_cell_wide_is_sampled_along_its_middle():
    p = channel_project(cells=(20, 1, 20), size=(4.0, 0.05, 1.0))
    section = hy.long_section(channel_result(p, lambda x: 0.3 + 0 * x, q=0.15), p)
    assert np.allclose(section.discharge, 0.15 * 0.05) and np.allclose(section.unit_discharge, 0.15)
    assert np.allclose(section.water_level, 0.3)


def test_a_long_section_needs_water_and_gravity_straight_down():
    p = channel_project()
    data = channel_result(p, lambda x: 0.3 + 0 * x, q=0.1)
    del data.internal.cell_data["alpha.water"]
    with pytest.raises(ValueError, match="free-surface"):
        hy.long_section(data, p)
    p.physics.gravity = [0.5, 0, -9.8]
    with pytest.raises(ValueError, match="gravity"):
        hy.gravity(p)


def test_a_long_section_is_saved_as_a_table_with_units(tmp_path):
    p = channel_project(cells=(10, 1, 10))
    section = hy.long_section(channel_result(p, lambda x: 0.4 + 0 * x, q=0.1), p)
    section.write_csv(tmp_path / "long.csv")
    lines = (tmp_path / "long.csv").read_text().splitlines()
    assert lines[0].startswith("chainage [m],x [m],y [m],bed level [m],water level [m]")
    assert len(lines) == 11 and "Froude number [-]" in lines[0]


# --- jumps and control sections -------------------------------------------------------


def synthetic(chainage, depth, q=0.2):
    v = q / depth
    nan = np.full_like(depth, np.nan)
    return hy.LongSection(
        chainage=chainage, x=chainage, y=0 * chainage, bed=0 * chainage, water_level=depth, depth=depth,
        hydraulic_depth=depth, area=depth, top_width=1 + 0 * depth, discharge=q + 0 * depth,
        unit_discharge=q + 0 * depth, velocity=v, froude=np.abs(v) / np.sqrt(G * depth),
        specific_energy=depth + v**2 / (2 * G), energy_level=depth + v**2 / (2 * G), total_head=nan, coriolis=nan,
    )  # fmt: skip


def test_belanger_and_the_energy_lost_in_a_jump():
    assert hy.sequent_depth(0.1, 1.0) == pytest.approx(0.1)
    assert hy.sequent_depth(0.05, 5.0) == pytest.approx(0.025 * (math.sqrt(201) - 1))
    assert hy.jump_loss(0.2, 0.2) == 0.0
    assert hy.jump_loss(0.05, 0.3) == pytest.approx(0.25**3 / 0.06)


def test_a_jump_is_found_with_its_toe_end_and_sequent_depth():
    s = np.linspace(0, 6, 121)
    y = np.interp(s, [0, 2.0, 3.5, 6], [0.05, 0.052, 0.30, 0.30])
    jumps = hy.find_jumps(synthetic(s, y))
    assert len(jumps) == 1
    jump = jumps[0]
    assert jump.toe == pytest.approx(2.0, abs=0.06) and jump.end == pytest.approx(3.5, abs=0.06)
    assert 0.05 <= jump.y1 <= 0.062 and jump.y2 == pytest.approx(0.30)  # within one station of the sharp toe
    assert jump.froude1 == pytest.approx(0.2 / jump.y1 / math.sqrt(G * jump.y1), rel=1e-6)
    assert jump.y2_theory == pytest.approx(hy.sequent_depth(jump.y1, jump.froude1))
    assert jump.kind == ("oscillating jump" if jump.froude1 < 4.5 else "steady jump") and jump.loss > 0
    assert "Bélanger" in " ".join(jump.lines())


def test_a_crest_is_found_as_a_control_section_at_critical_depth():
    s = np.linspace(0, 4, 81)
    y = np.interp(s, [0, 4], [0.30, 0.06])
    controls = hy.find_controls(synthetic(s, y))
    critical = (0.2**2 / G) ** (1 / 3)
    assert len(controls) == 1 and controls[0].critical_depth == pytest.approx(critical)
    assert controls[0].depth == pytest.approx(critical, rel=0.02)
    assert controls[0].chainage == pytest.approx(np.interp(critical, y[::-1], s[::-1]), abs=0.05)
    assert hy.find_jumps(synthetic(s, y)) == []


def test_flow_in_the_other_direction_is_read_from_downstream_to_upstream():
    s = np.linspace(0, 6, 121)
    y = np.interp(s, [0, 2.5, 4.0, 6], [0.30, 0.30, 0.052, 0.05])
    jumps = hy.find_jumps(synthetic(s, y, q=-0.2))
    assert len(jumps) == 1 and jumps[0].toe > jumps[0].end


def test_the_summary_names_the_discharge_levels_and_the_jump():
    s = np.linspace(0, 6, 121)
    lines = hy.summary(synthetic(s, np.interp(s, [0, 2.0, 3.5, 6], [0.05, 0.052, 0.30, 0.30])))
    text = "\n".join(lines)
    assert "Discharge 0.2 m³/s" in text and "Hydraulic jump" in text and "Energy line drops" in text


# --- structures ---------------------------------------------------------------------


def weir_faces(dz=0.01, crest=0.4, x0=2.0, x1=3.0, width=1.0):
    """Upstream face, crest and downstream face of a weir, oriented out of the water (into the weir)."""
    points, faces = [], []

    def quad(a, b, c, d):
        start = len(points)
        points.extend([a, b, c, d])
        faces.extend([4, start, start + 1, start + 2, start + 3])

    for z in np.arange(0, crest - 1e-9, dz):  # upstream face, normal +x
        quad((x0, 0, z), (x0, width, z), (x0, width, z + dz), (x0, 0, z + dz))
    for x in np.arange(x0, x1 - 1e-9, dz):  # crest, normal -z
        quad((x, 0, crest), (x, width, crest), (x + dz, width, crest), (x + dz, 0, crest))
    for z in np.arange(0, crest - 1e-9, dz):  # downstream face, normal -x
        quad((x1, 0, z), (x1, 0, z + dz), (x1, width, z + dz), (x1, width, z))
    return pv.PolyData(np.array(points, float), np.array(faces))


def hydrostatic(surface, upstream=0.5, downstream=0.2):
    """Still water against both faces of the weir; the crest itself stays dry."""
    centres = np.asarray(surface.cell_centers().points)
    level = np.where(centres[:, 0] < 2.0 + 1e-9, upstream, np.where(centres[:, 0] > 3.0 - 1e-9, downstream, 0.0))
    surface.cell_data["p"] = RHO * G * np.clip(level - centres[:, 2], 0, None)
    return surface


def test_area_vectors_point_out_of_the_water():
    centres, vectors = hy.area_vectors(weir_faces())
    assert np.allclose(vectors[0], [0.01, 0, 0])  # upstream face: towards +x
    assert vectors[:, 2].min() == pytest.approx(-0.01)  # the crest: downwards
    assert np.isclose(np.abs(vectors).sum(axis=1), 0.01).all()


def test_loads_on_a_weir_match_hand_calculated_hydrostatics():
    p = channel_project()
    surface = hydrostatic(weir_faces())
    loads = hy.structure_loads([surface], p)
    # upstream 0.5 m of water against 0.4 m of face, downstream 0.2 m: forces and moments per metre width
    fx = RHO * G * ((0.5 * 0.4 - 0.4**2 / 2) - (0.2 * 0.2 - 0.2**2 / 2))
    my = RHO * G * ((0.5 * 0.4**2 / 2 - 0.4**3 / 3) - (0.2 * 0.2**2 / 2 - 0.2**3 / 3))
    assert loads.force[0] == pytest.approx(fx, rel=1e-3)
    assert loads.force[2] == pytest.approx(0.0, abs=1e-6) and loads.force[1] == pytest.approx(0, abs=1e-6)
    assert list(loads.point) == pytest.approx([3.0, 0.5, 0.0])  # the downstream toe
    assert loads.moment[1] == pytest.approx(my, rel=2e-3)
    assert loads.width == pytest.approx(1.0)  # it spans the channel, so per-metre values are given
    assert "kN/m" in " ".join(loads.lines())


def test_a_structure_that_does_not_span_the_channel_has_no_per_metre_value():
    p = channel_project()
    pier = hydrostatic(weir_faces(width=0.3))
    assert hy.structure_loads([pier], p, point=[0, 0, 0]).width is None


def test_pressure_along_a_weir_runs_from_upstream_over_the_crest_to_downstream():
    p = channel_project()
    profile = hy.pressure_profile(hydrostatic(weir_faces()), p)
    assert profile.x[0] == pytest.approx(2.0) and profile.x[-1] == pytest.approx(3.0)
    assert np.all(np.diff(profile.distance) > 0)
    assert profile.distance[-1] == pytest.approx(0.4 + 1.0 + 0.4, rel=1e-6)
    assert profile.head[0] == pytest.approx(0.5, abs=0.01)  # foot of the upstream face
    crest = (profile.z > 0.399) & (profile.x > 2.1) & (profile.x < 2.4)
    assert np.allclose(profile.head[crest], 0.0, atol=1e-9)


def test_critical_shear_stress_of_sand_and_gravel():
    assert hy.critical_shear_stress(0.001) == pytest.approx(0.51, rel=0.05)
    assert hy.critical_shear_stress(0.010) == pytest.approx(9.0, rel=0.05)


def test_bed_shear_stress_and_sediment_mobility_are_added_to_a_wall():
    p = channel_project()
    surface = weir_faces()
    n = surface.n_cells
    shear = np.zeros((n, 3))
    shear[:, 0] = 0.002  # kinematic, m²/s²
    surface.cell_data["wallShearStress"] = shear
    surface.cell_data["alpha.water"] = np.r_[np.ones(n // 2), np.zeros(n - n // 2)]
    largest = hy.add_bed_shear(surface, p, critical=1.0)
    assert largest == pytest.approx(RHO * 0.002)
    assert surface.cell_data["bedShearStress"][0] == pytest.approx(RHO * 0.002)
    assert surface.cell_data["bedShearStress"][-1] == pytest.approx(p.physics.air_rho * 0.002)
    assert surface.cell_data["sedimentMobility"][0] == pytest.approx(RHO * 0.002)
    assert hy.add_bed_shear(weir_faces(), p, 1.0) is None  # no shear stress computed yet


def test_the_1d_backwater_profile_rises_upstream_as_friction_demands():
    s = np.linspace(0, 40, 401)
    flat = synthetic(s, 0.3 + 0 * s, q=0.3)
    levels = hy.backwater(flat, n=0.017)
    assert levels[-1] == pytest.approx(0.3) and np.all(np.diff(levels) < 0)  # an H2 curve: lower downstream
    # first step by hand: dh/ds = -Sf / (1 - Fr²) at the downstream depth
    sf = (0.017 * 1.0) ** 2 / 0.3 ** (4 / 3)
    fr2 = 1.0 / (G * 0.3)
    assert (levels[-2] - levels[-1]) / 0.1 == pytest.approx(sf / (1 - fr2), rel=0.02)
    assert hy.backwater(flat, n=0.0)[0] != hy.backwater(flat, n=0.0)[0]  # no roughness: nothing computed
