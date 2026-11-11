from easyfoam.casegen.mesh import (
    auto_location_in_mesh,
    block_mesh_dict,
    feature_extract_dict,
    mesh_steps,
    snappy_dict,
)
from easyfoam.foam.dictfmt import Named, Q
from easyfoam.model import BaseFace, Project, Shape


def project_with(*shapes):
    p = Project(name="t")
    p.mesh.base.min, p.mesh.base.max, p.mesh.base.cells = [0, 0, 0], [4, 2, 1], [40, 20, 10]
    p.shapes.extend(shapes)
    return p


def test_block_mesh_has_eight_corner_vertices_and_one_block():
    d = block_mesh_dict(project_with())
    assert d["vertices"] == [
        [0, 0, 0], [4, 0, 0], [4, 2, 0], [0, 2, 0],
        [0, 0, 1], [4, 0, 1], [4, 2, 1], [0, 2, 1],
    ]  # fmt: skip
    # blockMesh wants a flat token list: blocks ( hex (...) (...) simpleGrading (...) );
    assert d["blocks"] == ["hex", [0, 1, 2, 3, 4, 5, 6, 7], [40, 20, 10], "simpleGrading", [1, 1, 1]]


def test_block_mesh_groups_faces_that_share_a_name_into_one_patch():
    d = block_mesh_dict(project_with())
    assert d["boundary"] == [
        Named("inlet", {"type": "patch", "faces": [[0, 4, 7, 3]]}),
        Named("outlet", {"type": "patch", "faces": [[1, 2, 6, 5]]}),
        Named("sides", {"type": "patch", "faces": [[0, 1, 5, 4], [3, 7, 6, 2], [0, 3, 2, 1], [4, 5, 6, 7]]}),
    ]


def test_block_mesh_keeps_the_face_type_chosen_by_the_user():
    p = project_with()
    p.mesh.base.faces["zMin"] = BaseFace("ground", "wall")
    ground = [n for n in block_mesh_dict(p)["boundary"] if n.name == "ground"][0]
    assert ground.body == {"type": "wall", "faces": [[0, 3, 2, 1]]}


def test_stl_shape_becomes_a_refined_wall_surface_with_feature_edges():
    d = snappy_dict(project_with(Shape("body", kind="stl", file="body.stl", level_min=2, level_max=4)))
    assert d["geometry"] == {"body": {"type": "triSurfaceMesh", "file": Q("body.stl")}}
    c = d["castellatedMeshControls"]
    assert c["refinementSurfaces"] == {"body": {"level": [2, 4], "patchInfo": {"type": "wall"}}}
    assert c["features"] == [{"file": Q("body.eMesh"), "level": 2}]
    assert d["snapControls"]["explicitFeatureSnap"] is True
    assert d["snapControls"]["implicitFeatureSnap"] is False


def test_primitive_shapes_use_their_searchable_surface_types_and_implicit_snapping():
    d = snappy_dict(
        project_with(
            Shape("ball", kind="sphere", centre=[1, 1, 0.5], radius=0.2),
            Shape("rod", kind="cylinder", point1=[0, 0, 0], point2=[0, 0, 1], radius=0.1),
            Shape("brick", kind="box", min=[2, 0.5, 0], max=[3, 1.5, 0.5]),
        )
    )
    assert d["geometry"] == {
        "ball": {"type": "sphere", "origin": [1, 1, 0.5], "radius": 0.2},
        "rod": {"type": "cylinder", "point1": [0, 0, 0], "point2": [0, 0, 1], "radius": 0.1},
        "brick": {"type": "box", "min": [2, 0.5, 0], "max": [3, 1.5, 0.5]},
    }
    assert d["castellatedMeshControls"]["features"] == []
    assert d["snapControls"]["implicitFeatureSnap"] is True
    assert d["snapControls"]["explicitFeatureSnap"] is False


def test_refinement_shape_refines_a_region_but_creates_no_surface():
    d = snappy_dict(project_with(Shape("wake", kind="box", role="refinement", region_level=3)))
    c = d["castellatedMeshControls"]
    assert c["refinementSurfaces"] == {}
    assert c["refinementRegions"] == {"wake": {"mode": "inside", "levels": [[1e15, 3]]}}


def test_layers_are_added_only_for_surfaces_that_ask_for_them():
    with_layers = snappy_dict(
        project_with(Shape("body", file="b.stl", layers=3), Shape("mast", file="m.stl", layers=0))
    )
    assert with_layers["addLayers"] is True
    assert with_layers["addLayersControls"]["layers"] == {'"body.*"': {"nSurfaceLayers": 3}}
    assert snappy_dict(project_with(Shape("body", file="b.stl")))["addLayers"] is False


def test_layers_can_be_switched_off_globally():
    p = project_with(Shape("body", file="b.stl", layers=3))
    p.mesh.add_layers = False
    assert snappy_dict(p)["addLayers"] is False


def test_location_in_mesh_is_the_users_point_when_given():
    p = project_with(Shape("body", file="b.stl"))
    p.mesh.location_in_mesh = [0.1, 0.2, 0.3]
    assert snappy_dict(p)["castellatedMeshControls"]["locationInMesh"] == [0.1, 0.2, 0.3]


def test_automatic_location_is_strictly_inside_the_base_mesh_and_off_the_cell_faces():
    p = project_with()
    x, y, z = auto_location_in_mesh(p.mesh.base)
    assert 0 < x < 4 and 0 < y < 2 and 0 < z < 1
    for value, lo, hi, n in ((x, 0, 4, 40), (y, 0, 2, 20), (z, 0, 1, 10)):
        cell_coordinate = (value - lo) / (hi - lo) * n
        assert abs(cell_coordinate - round(cell_coordinate)) > 0.05


def test_feature_extraction_is_only_needed_for_stl_surfaces():
    assert feature_extract_dict(project_with(Shape("ball", kind="sphere"))) is None
    d = feature_extract_dict(project_with(Shape("body", file="body.stl")))
    assert list(d) == ["body.stl"]
    assert d["body.stl"]["extractionMethod"] == "extractFromSurface"


def test_mesh_steps_for_an_stl_case_run_the_full_snappy_pipeline():
    names = [s.name for s in mesh_steps(project_with(Shape("body", file="body.stl")))]
    assert names == ["blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "checkMesh"]
    commands = {s.name: s.command for s in mesh_steps(project_with(Shape("body", file="body.stl")))}
    assert commands["snappyHexMesh"] == "snappyHexMesh -overwrite"


def test_mesh_steps_skip_snappy_when_there_is_nothing_to_snap_to():
    assert [s.name for s in mesh_steps(project_with())] == ["blockMesh", "checkMesh"]
    p = project_with(Shape("ball", kind="sphere"))
    p.mesh.snappy = False
    assert [s.name for s in mesh_steps(p)] == ["blockMesh", "checkMesh"]
    assert [s.name for s in mesh_steps(project_with(Shape("ball", kind="sphere")))] == [
        "blockMesh", "snappyHexMesh", "checkMesh",
    ]  # fmt: skip


def test_patches_can_be_predicted_before_the_mesh_exists():
    from easyfoam.casegen.mesh import predicted_patches

    p = project_with(Shape("body", file="b.stl"), Shape("wake", kind="box", role="refinement"))
    p.mesh.base.faces["zMin"] = BaseFace("ground", "wall")
    assert [(x.name, x.type) for x in predicted_patches(p)] == [
        ("inlet", "patch"), ("outlet", "patch"), ("sides", "patch"), ("ground", "wall"), ("body", "wall"),
    ]  # fmt: skip


def test_predicted_patches_ignore_shapes_when_snappy_is_off():
    from easyfoam.casegen.mesh import predicted_patches

    p = project_with(Shape("body", file="b.stl"))
    p.mesh.snappy = False
    assert [x.name for x in predicted_patches(p)] == ["inlet", "outlet", "sides"]
