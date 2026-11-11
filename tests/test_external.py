from easyfoam.external import find_paraview


def test_newest_paraview_under_program_files_is_preferred(tmp_path):
    for version in ("5.12.0", "6.1.0", "5.9.1"):
        exe = tmp_path / f"ParaView {version}" / "bin" / "paraview.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
    found = find_paraview(search_roots=[tmp_path], on_path=lambda name: None)
    assert found == tmp_path / "ParaView 6.1.0" / "bin" / "paraview.exe"


def test_paraview_on_the_path_is_used_when_no_install_folder_matches(tmp_path):
    exe = tmp_path / "paraview"
    exe.write_text("")
    assert find_paraview(search_roots=[tmp_path / "none"], on_path=lambda name: str(exe)) == exe


def test_missing_paraview_gives_none(tmp_path):
    assert find_paraview(search_roots=[tmp_path], on_path=lambda name: None) is None
