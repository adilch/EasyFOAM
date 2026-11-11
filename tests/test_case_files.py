import struct

import pytest

from easyfoam.casegen import clean_mesh, clean_results, mesh_files, setup_files, write_files
from easyfoam.foam.boundaryfile import Patch
from easyfoam.geometry import fit_base_mesh, import_stl, stl_bounds
from easyfoam.model import Project, Shape

ASCII_STL = """solid tri
 facet normal 0 0 1
  outer loop
   vertex 0 0 0
   vertex 2 0 0
   vertex 0 1.5 -0.5
  endloop
 endfacet
endsolid tri
"""


def binary_stl(triangles):
    data = b"binary stl".ljust(80, b" ") + struct.pack("<I", len(triangles))
    for tri in triangles:
        data += struct.pack("<3f", 0, 0, 1)
        for vertex in tri:
            data += struct.pack("<3f", *vertex)
        data += b"\0\0"
    return data


def test_mesh_files_for_a_base_mesh_only_case():
    files = mesh_files(Project(name="duct"))
    assert sorted(files) == [
        "duct.foam",
        "system/blockMeshDict",
        "system/controlDict",
        "system/fvSchemes",
        "system/fvSolution",
    ]
    assert "object          blockMeshDict;" in files["system/blockMeshDict"]


def test_mesh_files_add_snappy_and_feature_dictionaries_when_needed():
    p = Project(name="car")
    p.shapes.append(Shape("body", file="body.stl"))
    files = mesh_files(p)
    assert "system/snappyHexMeshDict" in files
    assert "system/surfaceFeatureExtractDict" in files
    p.shapes[0] = Shape("ball", kind="sphere")
    assert "system/surfaceFeatureExtractDict" not in mesh_files(p)


def test_setup_files_cover_fields_properties_and_system_dictionaries():
    p = Project(name="duct")
    p.run.processors = 2
    files = setup_files(p, [Patch("inlet", "patch", 1, 0), Patch("walls", "wall", 1, 1)])
    assert sorted(files) == [
        "0/U", "0/k", "0/nut", "0/omega", "0/p",
        "constant/transportProperties", "constant/turbulenceProperties",
        "duct.foam",
        "system/controlDict", "system/decomposeParDict", "system/fvSchemes", "system/fvSolution",
    ]  # fmt: skip
    assert "class           volVectorField;" in files["0/U"]
    assert 'location        "0";' in files["0/U"]


def test_write_files_creates_folders_and_uses_unix_line_endings(tmp_path):
    written = write_files(tmp_path, {"system/controlDict": "a\nb\n", "0/U": "x\n"})
    assert (tmp_path / "system" / "controlDict").read_bytes() == b"a\nb\n"
    assert written == [tmp_path / "system" / "controlDict", tmp_path / "0" / "U"]


def make_case(tmp_path):
    for rel in ("constant/polyMesh/boundary", "constant/triSurface/a.stl", "0/U", "100/U",
                "0.25/p", "processor0/0/U", "postProcessing/x/0/y.dat", "system/controlDict",
                "log.simpleFoam", "easyfoam.json"):  # fmt: skip
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    return tmp_path


def test_clean_results_removes_computed_times_but_keeps_setup_and_mesh(tmp_path):
    case = make_case(tmp_path)
    clean_results(case)
    left = sorted(p.relative_to(case).as_posix() for p in case.rglob("*") if p.is_file())
    assert left == [
        "0/U", "constant/polyMesh/boundary", "constant/triSurface/a.stl",
        "easyfoam.json", "log.simpleFoam", "system/controlDict",
    ]  # fmt: skip


def test_clean_mesh_also_removes_the_mesh_and_initial_fields_but_keeps_geometry(tmp_path):
    case = make_case(tmp_path)
    clean_mesh(case)
    left = sorted(p.relative_to(case).as_posix() for p in case.rglob("*") if p.is_file())
    assert left == ["constant/triSurface/a.stl", "easyfoam.json", "log.simpleFoam", "system/controlDict"]


def test_bounds_of_an_ascii_stl(tmp_path):
    f = tmp_path / "a.stl"
    f.write_text(ASCII_STL)
    assert stl_bounds(f) == ([0.0, 0.0, -0.5], [2.0, 1.5, 0.0])


def test_bounds_of_a_binary_stl(tmp_path):
    f = tmp_path / "b.stl"
    f.write_bytes(binary_stl([[(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 2), (-3, 0, 0), (0, 1, 0)]]))
    assert stl_bounds(f) == ([-3.0, 0.0, 0.0], [1.0, 1.0, 2.0])


def test_binary_stl_whose_header_starts_with_the_word_solid_is_still_read(tmp_path):
    data = bytearray(binary_stl([[(0, 0, 0), (1, 0, 0), (0, 1, 0)]]))
    data[:5] = b"solid"
    f = tmp_path / "c.stl"
    f.write_bytes(bytes(data))
    assert stl_bounds(f) == ([0.0, 0.0, 0.0], [1.0, 1.0, 0.0])


def test_stl_without_triangles_is_rejected(tmp_path):
    f = tmp_path / "empty.stl"
    f.write_text("solid nothing\nendsolid nothing\n")
    with pytest.raises(ValueError, match="no triangles"):
        stl_bounds(f)


def test_import_copies_the_stl_into_the_case_and_returns_a_shape(tmp_path):
    src = tmp_path / "My Part (v2).STL"
    src.write_text(ASCII_STL)
    case = tmp_path / "case"
    shape = import_stl(case, src)
    assert (shape.name, shape.kind, shape.file) == ("My_Part_v2", "stl", "My_Part_v2.stl")
    assert (case / "constant" / "triSurface" / "My_Part_v2.stl").read_text() == ASCII_STL


def test_fit_base_mesh_surrounds_the_geometry_with_margins_and_roughly_cubic_cells(tmp_path):
    p = Project(name="x")
    p.shapes.append(Shape("ball", kind="sphere", centre=[0, 0, 0], radius=0.5))
    fit_base_mesh(p, tmp_path, cell_size=0.25)
    base = p.mesh.base
    assert base.min[0] < -0.5 and base.max[0] > 0.5
    assert base.max[0] - 0.5 > 0.5 - base.min[0]  # more room downstream (+x) than upstream
    sizes = [(hi - lo) / n for lo, hi, n in zip(base.min, base.max, base.cells)]
    assert all(s == pytest.approx(0.25) for s in sizes)


def test_fit_base_mesh_needs_some_geometry(tmp_path):
    with pytest.raises(ValueError, match="no geometry"):
        fit_base_mesh(Project(name="x"), tmp_path)
