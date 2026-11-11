from easyfoam.foam.dictfmt import Named, Q, dumps, foam_file


def test_scalar_entries_end_with_semicolon_and_keep_order():
    text = dumps({"application": "simpleFoam", "deltaT": 1, "endTime": 0.5})
    assert text.splitlines() == [
        "application     simpleFoam;",
        "deltaT          1;",
        "endTime         0.5;",
    ]


def test_booleans_are_written_as_true_false():
    assert dumps({"runTimeModifiable": True, "implicitFeatureSnap": False}).splitlines() == [
        "runTimeModifiable true;",
        "implicitFeatureSnap false;",
    ]


def test_nested_dictionary_is_a_braced_indented_block():
    text = dumps({"SIMPLE": {"nNonOrthogonalCorrectors": 0, "residualControl": {"p": 1e-4}}})
    assert text.splitlines() == [
        "SIMPLE",
        "{",
        "    nNonOrthogonalCorrectors 0;",
        "    residualControl",
        "    {",
        "        p               0.0001;",
        "    }",
        "}",
    ]


def test_flat_list_is_inline():
    assert dumps({"value": "uniform", "n": [10, 20, 30]}).splitlines()[1] == "n               (10 20 30);"


def test_mixed_token_list_stays_inline():
    blocks = ["hex", [0, 1, 2, 3, 4, 5, 6, 7], [10, 10, 10], "simpleGrading", [1, 1, 1]]
    assert dumps({"blocks": [blocks]}).splitlines() == [
        "blocks",
        "(",
        "    (hex (0 1 2 3 4 5 6 7) (10 10 10) simpleGrading (1 1 1))",
        ");",
    ]


def test_list_of_vectors_is_one_per_line():
    assert dumps({"vertices": [[0, 0, 0], [1, 0, 0.5]]}).splitlines() == [
        "vertices",
        "(",
        "    (0 0 0)",
        "    (1 0 0.5)",
        ");",
    ]


def test_named_blocks_inside_a_list():
    data = {"boundary": [Named("inlet", {"type": "patch", "faces": [[0, 4, 7, 3]]})]}
    assert dumps(data).splitlines() == [
        "boundary",
        "(",
        "    inlet",
        "    {",
        "        type            patch;",
        "        faces",
        "        (",
        "            (0 4 7 3)",
        "        );",
        "    }",
        ");",
    ]


def test_anonymous_dictionaries_inside_a_list():
    data = {"features": [{"file": Q("body.eMesh"), "level": 2}]}
    assert dumps(data).splitlines() == [
        "features",
        "(",
        "    {",
        '        file            "body.eMesh";',
        "        level           2;",
        "    }",
        ");",
    ]


def test_empty_list_and_empty_dict():
    assert dumps({"features": [], "layers": {}}).splitlines() == [
        "features        ();",
        "layers",
        "{",
        "}",
    ]


def test_directive_keys_have_no_semicolon():
    text = dumps({"#includeEtc": Q("caseDicts/setConstraintTypes"), "inlet": {"type": "zeroGradient"}})
    assert text.splitlines()[0] == '#includeEtc "caseDicts/setConstraintTypes"'


def test_quoted_string_escapes_embedded_quotes():
    assert dumps({"note": Q('say "hi"')}) == 'note            "say \\"hi\\"";\n'


def test_foam_file_has_header_with_class_object_and_location():
    text = foam_file("volVectorField", "U", {"internalField": "uniform (0 0 0)"}, location="0")
    lines = text.splitlines()
    assert lines[0].startswith("/*") and "EasyFOAM" in text.split("FoamFile")[0]
    start = lines.index("FoamFile")
    assert lines[start : start + 8] == [
        "FoamFile",
        "{",
        "    version         2.0;",
        "    format          ascii;",
        "    class           volVectorField;",
        '    location        "0";',
        "    object          U;",
        "}",
    ]
    assert "internalField   uniform (0 0 0);" in lines
    assert text.endswith("\n")


def test_unsupported_value_type_is_rejected_with_the_key_name():
    import pytest

    with pytest.raises(TypeError, match="badKey"):
        dumps({"badKey": object()})
