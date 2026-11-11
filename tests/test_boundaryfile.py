from easyfoam.foam.boundaryfile import Patch, parse_boundary

BOUNDARY = """\
/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       polyBoundaryMesh;
    location    "constant/polyMesh";
    object      boundary;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

3
(
    inlet
    {
        type            patch;
        nFaces          400;
        startFace       23600;
    }
    body_wing  // trailing comment
    {
        type            wall;
        inGroups        1(wall);
        nFaces          1600;
        startFace       24000;
    }
    frontAndBack
    {
        type            empty;
        inGroups        1(empty);
        nFaces          0;
        startFace       25600;
    }
)

// ************************************************************************* //
"""


def test_patches_are_returned_in_file_order_with_type_and_face_counts():
    assert parse_boundary(BOUNDARY) == [
        Patch("inlet", "patch", 400, 23600),
        Patch("body_wing", "wall", 1600, 24000),
        Patch("frontAndBack", "empty", 0, 25600),
    ]


def test_header_block_is_not_mistaken_for_a_patch():
    assert "FoamFile" not in [p.name for p in parse_boundary(BOUNDARY)]


def test_empty_boundary_list():
    assert parse_boundary("FoamFile\n{\n    object boundary;\n}\n0\n(\n)\n") == []
