from easyfoam.cli import main
from easyfoam.model import Project


def test_new_creates_a_project_from_the_sphere_example(tmp_path, capsys):
    case = tmp_path / "demo"
    assert main(["new", str(case), "--example", "sphere"]) == 0
    project = Project.load(case)
    assert project.name == "demo"
    assert [(s.name, s.role) for s in project.shapes] == [("ball", "wall"), ("wake", "refinement")]
    assert "demo" in capsys.readouterr().out


def test_new_refuses_to_overwrite_an_existing_project(tmp_path, capsys):
    case = tmp_path / "demo"
    main(["new", str(case)])
    assert main(["new", str(case)]) == 2
    assert "already" in capsys.readouterr().err


def test_write_puts_the_meshing_dictionaries_on_disk_without_running_anything(tmp_path):
    case = tmp_path / "demo"
    main(["new", str(case), "--example", "sphere"])
    assert main(["write", str(case)]) == 0
    assert (case / "system" / "blockMeshDict").is_file()
    assert (case / "system" / "snappyHexMeshDict").is_file()


def test_commands_on_a_folder_without_a_project_fail_with_a_clear_message(tmp_path, capsys):
    assert main(["mesh", str(tmp_path)]) == 2
    assert "easyfoam.json" in capsys.readouterr().err


def test_import_stl_adds_the_shape_and_can_fit_the_base_mesh(tmp_path):
    stl = tmp_path / "wedge.stl"
    stl.write_text(
        "solid w\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 1 1\n"
        "endloop\nendfacet\nendsolid w\n"
    )
    case = tmp_path / "demo"
    main(["new", str(case)])
    assert main(["import-stl", str(case), str(stl), "--fit"]) == 0
    project = Project.load(case)
    assert [s.file for s in project.shapes] == ["wedge.stl"]
    assert project.mesh.base.min[0] < 0 and project.mesh.base.max[0] > 2
