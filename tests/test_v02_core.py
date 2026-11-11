"""v0.2: forces, more turbulence models, potential start, y+, internal flow, STL regions."""

import numpy as np
import pytest

from easyfoam.casegen.mesh import location_in_mesh, predicted_patches, snappy_dict
from easyfoam.casegen.setup import (
    control_dict,
    field_dicts,
    force_patches,
    fv_schemes,
    fv_solution,
    parse_yplus,
    post_steps,
    run_steps,
    turbulence_properties,
)
from easyfoam.foam.boundaryfile import Patch
from easyfoam.foam.coeffs import parse_coefficients, read_coefficients
from easyfoam.geometry import fit_base_mesh, import_stl, interior_point, stl_regions, stl_triangles
from easyfoam.model import Boundary, Project, Shape
from easyfoam.runtime import Step

PATCHES = [
    Patch("inlet", "patch", 100, 0),
    Patch("outlet", "patch", 100, 100),
    Patch("ground", "wall", 400, 200),
    Patch("body", "wall", 900, 600),
    Patch("pipe_rim", "wall", 9, 1500),
]


def tunnel(turbulence="kOmegaSST"):
    p = Project(name="t")
    p.physics.turbulence = turbulence
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[10.0, 0.0, 0.0])
    return p


# --- turbulence models -------------------------------------------------------


def test_spalart_allmaras_solves_nu_tilda_with_a_wall_function_that_needs_no_k():
    p = tunnel("SpalartAllmaras")
    f = field_dicts(p, PATCHES)
    assert list(f) == ["U", "p", "nuTilda", "nut"]
    assert f["nuTilda"][1]["dimensions"] == "[0 2 -1 0 0 0 0]"
    assert f["nuTilda"][1]["boundaryField"]["inlet"] == {"type": "fixedValue", "value": "uniform 4.5e-05"}
    assert f["nuTilda"][1]["boundaryField"]["body"] == {"type": "fixedValue", "value": "uniform 0"}
    assert f["nut"][1]["boundaryField"]["body"]["type"] == "nutUSpaldingWallFunction"
    assert "div(phi,nuTilda)" in fv_schemes(p)["divSchemes"]
    assert turbulence_properties(p)["RAS"]["RASModel"] == "SpalartAllmaras"


def test_realizable_k_epsilon_uses_the_k_epsilon_fields():
    p = tunnel("realizableKE")
    assert list(field_dicts(p, PATCHES)) == ["U", "p", "k", "epsilon", "nut"]
    assert turbulence_properties(p)["RAS"]["RASModel"] == "realizableKE"
    assert field_dicts(p, PATCHES)["nut"][1]["boundaryField"]["body"]["type"] == "nutkWallFunction"


# --- potential-flow start and convergence target -----------------------------


def test_potential_flow_start_runs_before_the_solver_and_has_its_settings():
    p = tunnel()
    p.physics.potential_init = True
    assert [(s.name, s.command) for s in run_steps(p)] == [
        ("potentialFoam", "potentialFoam"), ("simpleFoam", "simpleFoam"),
    ]  # fmt: skip
    p.run.processors = 4
    assert [(s.name, s.command) for s in run_steps(p)] == [
        ("decomposePar", "decomposePar -force"),
        ("potentialFoam", "mpirun -np 4 potentialFoam -parallel"),
        ("simpleFoam", "mpirun -np 4 simpleFoam -parallel"),
        ("reconstructPar", "reconstructPar"),
    ]
    solution = fv_solution(p)
    assert solution["solvers"]["Phi"]["solver"] == "GAMG"
    assert solution["potentialFlow"]["nNonOrthogonalCorrectors"] == 3


def test_potential_flow_settings_are_absent_unless_asked_for():
    assert "potentialFlow" not in fv_solution(tunnel())


def test_convergence_target_sets_the_residual_control_and_zero_switches_it_off():
    p = tunnel()
    p.run.residual_target = 1e-5
    assert fv_solution(p)["SIMPLE"]["residualControl"]["U"] == 1e-5
    p.run.residual_target = 0
    assert "residualControl" not in fv_solution(p)["SIMPLE"]


# --- force coefficients ------------------------------------------------------


def aero():
    p = tunnel()
    p.shapes.append(Shape("body", file="body.stl"))
    p.shapes.append(Shape("pipe", file="pipe.stl"))
    p.forces.enabled = True
    p.forces.ref_area, p.forces.ref_length = 2.0, 0.5
    return p


def test_forces_are_taken_on_the_walls_that_come_from_shapes_by_default():
    assert force_patches(aero(), PATCHES) == ["body", "pipe_rim"]  # not the ground of the base mesh


def test_force_patches_named_by_the_user_are_kept_only_if_they_exist():
    p = aero()
    p.forces.patches = ["ground", "ghost"]
    assert force_patches(p, PATCHES) == ["ground"]


def test_force_coefficient_function_uses_the_inlet_speed_and_reference_values():
    fc = control_dict(aero(), PATCHES)["functions"]["forceCoeffs"]
    assert fc["type"] == "forceCoeffs"
    assert fc["patches"] == ["body", "pipe_rim"]
    assert (fc["magUInf"], fc["rhoInf"], fc["Aref"], fc["lRef"]) == (10.0, 1.2, 2.0, 0.5)
    assert (fc["dragDir"], fc["liftDir"], fc["pitchAxis"]) == ([1, 0, 0], [0, 0, 1], [0, 1, 0])
    assert fc["writeControl"] == "timeStep" and fc["writeInterval"] == 1


def test_a_reference_speed_given_by_the_user_wins_over_the_inlet_speed():
    p = aero()
    p.forces.ref_velocity = 25.0
    assert control_dict(p, PATCHES)["functions"]["forceCoeffs"]["magUInf"] == 25.0


def test_no_force_function_when_disabled_or_when_nothing_matches():
    p = aero()
    assert "functions" not in control_dict(p)  # patches unknown (meshing stage)
    p.forces.enabled = False
    assert "functions" not in control_dict(p, PATCHES)
    q = tunnel()
    q.forces.enabled = True
    assert "functions" not in control_dict(q, [Patch("inlet", "patch", 1, 0)])


COEFFS = """\
# Force and moment coefficients
# dragDir     : (1 0 0)
# Time          	Cd            	Cd(f)         	Cd(r)         	Cl            	Cl(f)         	Cl(r)         	CmPitch       	CmRoll        	CmYaw         	Cs            	Cs(f)         	Cs(r)
1             	5.1e-01	2.5e-01	2.6e-01	1.0e-02	0.1	0.2	-3.0e-03	0	0	0	0	0
2             	4.0e-01	2.0e-01	2.0e-01	2.0e-02	0.1	0.2	-4.0e-03	0	0	0	0	0
"""


def test_coefficient_columns_are_found_by_their_header_names():
    data = parse_coefficients(COEFFS)
    assert data["Time"] == [1.0, 2.0]
    assert data["Cd"] == [0.51, 0.40]
    assert data["Cl"] == [0.01, 0.02]
    assert data["CmPitch"] == [-0.003, -0.004]


def test_a_half_written_last_line_is_ignored():
    assert parse_coefficients(COEFFS + "3             \t3.9e-01\t1.")["Time"] == [1.0, 2.0]


def test_coefficient_history_is_joined_across_restarts(tmp_path):
    for start, text in (("0", COEFFS), ("2", COEFFS.replace("\n1 ", "\n3 ").replace("\n2 ", "\n4 "))):
        folder = tmp_path / "postProcessing" / "forceCoeffs" / start
        folder.mkdir(parents=True)
        (folder / "coefficient.dat").write_text(text)
    assert read_coefficients(tmp_path)["Time"] == [1.0, 2.0, 3.0, 4.0]
    assert read_coefficients(tmp_path / "nowhere") == {}


# --- derived quantities ------------------------------------------------------


def test_derived_quantity_is_computed_by_the_solver_in_post_processing_mode():
    assert post_steps(tunnel(), "yPlus") == [Step("yPlus", "simpleFoam -postProcess -func yPlus -latestTime")]
    with pytest.raises(ValueError, match="notAFunction"):
        post_steps(tunnel(), "notAFunction")


def test_y_plus_report_is_read_per_patch():
    log = """\
yPlus yPlus write:
    writing field yPlus
    patch body y+ : min = 0.35, max = 121.5, average = 42.25
    patch ground y+ : min = 1e-05, max = 3, average = 1.5
"""
    assert parse_yplus(log) == {"body": (0.35, 121.5, 42.25), "ground": (1e-05, 3.0, 1.5)}


# --- mesh: distance refinement, regions, fluid inside ------------------------


def base_project(*shapes):
    p = Project(name="m")
    p.mesh.base.min, p.mesh.base.max, p.mesh.base.cells = [0, -1, -1], [4, 1, 1], [40, 20, 20]
    p.shapes.extend(shapes)
    return p


def test_cells_near_a_surface_can_be_refined_by_distance():
    d = snappy_dict(base_project(Shape("ball", kind="sphere", near_distance=0.3, near_level=2)))
    assert d["castellatedMeshControls"]["refinementRegions"] == {
        "ball": {"mode": "distance", "levels": [[0.3, 2]]}
    }


def test_each_stl_region_gets_its_own_patch_type():
    pipe = Shape("pipe", file="pipe.stl", level_min=1, level_max=2,
                 regions={"inlet": "patch", "outlet": "patch", "wall": "wall"})  # fmt: skip
    surfaces = snappy_dict(base_project(pipe), case_dir=None, location=[1, 0, 0])[
        "castellatedMeshControls"
    ]["refinementSurfaces"]
    assert surfaces["pipe"]["regions"] == {
        "inlet": {"level": [1, 2], "patchInfo": {"type": "patch"}},
        "outlet": {"level": [1, 2], "patchInfo": {"type": "patch"}},
        "wall": {"level": [1, 2], "patchInfo": {"type": "wall"}},
    }


def test_predicted_patches_list_each_region_of_a_multi_region_stl():
    pipe = Shape("pipe", file="pipe.stl", regions={"inlet": "patch", "wall": "wall"})
    names = [(p.name, p.type) for p in predicted_patches(base_project(pipe))]
    assert names[-2:] == [("pipe_inlet", "patch"), ("pipe_wall", "wall")]


def test_fluid_inside_a_cylinder_puts_the_point_near_its_axis_within_the_base_mesh():
    rod = Shape("tube", kind="cylinder", point1=[-1, 0, 0], point2=[9, 0, 0], radius=0.5)
    p = base_project(rod)
    p.mesh.fluid_inside = "tube"
    x, y, z = location_in_mesh(p)
    assert 0 < x < 4  # inside the base mesh although the cylinder sticks out of it
    assert (y * y + z * z) ** 0.5 < 0.25 and (y, z) != (0, 0)  # near the axis, not on a cell face


def test_fluid_inside_a_sphere_or_box_uses_a_point_near_the_centre():
    p = base_project(Shape("tank", kind="box", min=[1, -0.5, -0.5], max=[3, 0.5, 0.5]))
    p.mesh.fluid_inside = "tank"
    x, y, z = location_in_mesh(p)
    assert 1.5 < x < 2.5 and abs(y) < 0.3 and abs(z) < 0.3


def test_a_point_given_by_the_user_wins_and_unknown_shapes_are_reported():
    p = base_project(Shape("tank", kind="box"))
    p.mesh.fluid_inside = "tank"
    p.mesh.location_in_mesh = [0.5, 0.1, 0.2]
    assert location_in_mesh(p) == [0.5, 0.1, 0.2]
    p.mesh.location_in_mesh = None
    p.mesh.fluid_inside = "gone"
    with pytest.raises(ValueError, match="gone"):
        location_in_mesh(p)


# --- geometry: closed surfaces, regions --------------------------------------

CUBE_VERTICES = np.array(
    [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float
)
CUBE_FACES = [
    (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
    (3, 6, 2), (3, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
]  # fmt: skip


def cube(scale=(1, 1, 1), faces=CUBE_FACES):
    return np.array([[CUBE_VERTICES[i] * scale for i in face] for face in faces])


def ascii_stl(solids):
    lines = []
    for name, triangles in solids.items():
        lines.append(f"solid {name}")
        for tri in triangles:
            lines += ["facet normal 0 0 0", "outer loop"]
            lines += ["vertex " + " ".join(repr(float(c)) for c in v) for v in tri]
            lines += ["endloop", "endfacet"]
        lines.append(f"endsolid {name}")
    return "\n".join(lines) + "\n"


def test_interior_point_of_a_closed_surface_lies_inside_it():
    x, y, z = interior_point(cube(scale=(4, 0.2, 0.2)))
    assert 0 < x < 4 and 0 < y < 0.2 and 0 < z < 0.2


def test_interior_point_respects_the_allowed_box():
    x, _, _ = interior_point(cube(scale=(4, 0.2, 0.2)), lo=[3, -1, -1], hi=[5, 1, 1])
    assert 3 < x < 4


def test_an_open_surface_has_no_interior():
    with pytest.raises(ValueError, match="closed"):
        interior_point(cube(faces=CUBE_FACES[:2]))


def test_ascii_stl_solids_are_listed_as_regions(tmp_path):
    f = tmp_path / "pipe.stl"
    f.write_text(ascii_stl({"inlet": cube()[:2], "outer wall": cube()[2:]}))
    assert stl_regions(f) == ["inlet", "outer wall"]
    assert stl_triangles(f).shape == (12, 3, 3)


def test_import_renames_regions_safely_and_records_them_on_the_shape(tmp_path):
    src = tmp_path / "pipe.stl"
    src.write_text(ascii_stl({"inlet": cube()[:2], "outer wall": cube()[2:]}))
    shape = import_stl(tmp_path / "case", src)
    assert shape.regions == {"inlet": "wall", "outer_wall": "wall"}
    copied = tmp_path / "case" / "constant" / "triSurface" / "pipe.stl"
    assert stl_regions(copied) == ["inlet", "outer_wall"]
    assert "endsolid outer_wall" in copied.read_text()


def test_a_single_solid_stl_has_no_separate_regions(tmp_path):
    src = tmp_path / "one.stl"
    src.write_text(ascii_stl({"part": cube()}))
    assert import_stl(tmp_path / "case", src).regions == {}


def test_fit_base_mesh_hugs_the_geometry_when_the_fluid_is_inside_it(tmp_path):
    p = Project(name="x")
    p.shapes.append(Shape("tank", kind="box", min=[0, 0, 0], max=[2, 1, 1]))
    p.mesh.fluid_inside = "tank"
    fit_base_mesh(p, tmp_path)
    base = p.mesh.base
    assert -0.3 < base.min[0] < 0 and 2 < base.max[0] < 2.3  # a small margin, not a wind tunnel
    assert all(n >= 8 for n in base.cells)
