import json

from easyfoam.model import Boundary, Project, Shape, default_boundary


def test_new_project_has_a_usable_wind_tunnel_base_mesh():
    p = Project(name="demo")
    assert p.mesh.base.cells == [20, 20, 20]
    assert {f: (v.name, v.type) for f, v in p.mesh.base.faces.items()} == {
        "xMin": ("inlet", "patch"),
        "xMax": ("outlet", "patch"),
        "yMin": ("sides", "patch"),
        "yMax": ("sides", "patch"),
        "zMin": ("sides", "patch"),
        "zMax": ("sides", "patch"),
    }
    assert p.physics.solver == "simpleFoam"


def test_project_survives_a_save_and_load_round_trip(tmp_path):
    p = Project(name="car")
    p.shapes.append(Shape(name="body", kind="stl", file="body.stl", level_min=2, level_max=4, layers=3))
    p.shapes.append(Shape(name="wake", kind="box", role="refinement", min=[0, -1, 0], max=[5, 1, 2]))
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[30.0, 0.0, 0.0])
    p.physics.turbulence = "kEpsilon"
    p.run.processors = 8
    path = p.save(tmp_path)
    assert path == tmp_path / "easyfoam.json"
    assert Project.load(tmp_path) == p


def test_loading_ignores_keys_written_by_a_newer_version(tmp_path):
    data = Project(name="old").to_dict()
    data["somethingNew"] = 1
    data["physics"]["futureOption"] = "x"
    (tmp_path / "easyfoam.json").write_text(json.dumps(data), encoding="utf-8")
    assert Project.load(tmp_path).name == "old"


def test_default_boundary_follows_patch_type_and_common_names():
    assert default_boundary("inlet", "patch").kind == "velocityInlet"
    assert default_boundary("main_outlet", "patch").kind == "pressureOutlet"
    assert default_boundary("sides", "patch").kind == "slip"
    assert default_boundary("body", "wall").kind == "wall"
    assert default_boundary("mid", "symmetry").kind == "constraint"
    assert default_boundary("frontAndBack", "empty").kind == "constraint"


def test_boundary_for_returns_the_users_choice_or_the_default():
    p = Project(name="x")
    p.boundaries["inlet"] = Boundary(kind="velocityInlet", velocity=[5.0, 0.0, 0.0])
    assert p.boundary_for("inlet", "patch").velocity == [5.0, 0.0, 0.0]
    assert p.boundary_for("body", "wall").kind == "wall"


def test_a_user_boundary_that_does_not_fit_the_patch_type_falls_back_to_the_default():
    p = Project(name="x")
    p.boundaries["mid"] = Boundary(kind="velocityInlet")
    assert p.boundary_for("mid", "symmetry").kind == "constraint"
    p.boundaries["body"] = Boundary(kind="pressureOutlet")
    assert p.boundary_for("body", "wall").kind == "wall"
