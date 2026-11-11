import sys
import threading
from pathlib import PureWindowsPath

from easyfoam.runtime import (
    Runtime,
    Step,
    parse_wsl_distros,
    render_script,
    runtimes_from_bashrc_paths,
    stream_process,
    windows_to_wsl_path,
)


def test_drive_path_maps_to_mnt():
    assert windows_to_wsl_path(PureWindowsPath(r"C:\EasyFOAM\runs\My Case")) == "/mnt/c/EasyFOAM/runs/My Case"


def test_wsl_unc_path_maps_to_linux_path_of_that_distro():
    p = PureWindowsPath(r"\\wsl.localhost\Ubuntu-24.04\home\me\case")
    assert windows_to_wsl_path(p) == "/home/me/case"


def test_wsl_distro_list_is_decoded_from_utf16_and_blank_lines_dropped():
    raw = "Ubuntu-24.04\r\n\r\ndocker-desktop\r\n".encode("utf-16-le")
    assert parse_wsl_distros(raw) == ["Ubuntu-24.04", "docker-desktop"]


def test_runtime_is_built_from_each_bashrc_path_with_a_readable_label():
    found = runtimes_from_bashrc_paths(
        "wsl",
        ["/usr/lib/openfoam/openfoam2506/etc/bashrc", "/opt/openfoam12/etc/bashrc", ""],
        distro="Ubuntu-24.04",
    )
    assert found == [
        Runtime("wsl", "openfoam2506 (WSL: Ubuntu-24.04)", "/usr/lib/openfoam/openfoam2506/etc/bashrc", "Ubuntu-24.04"),
        Runtime("wsl", "openfoam12 (WSL: Ubuntu-24.04)", "/opt/openfoam12/etc/bashrc", "Ubuntu-24.04"),
    ]


def test_wsl_runtime_runs_a_script_through_wsl_exe_with_translated_path():
    rt = Runtime("wsl", "x", "/opt/of/etc/bashrc", "Ubuntu-24.04")
    argv = rt.argv(PureWindowsPath(r"C:\cases\a\.easyfoam\mesh.sh"))
    assert argv == [
        "wsl.exe", "-d", "Ubuntu-24.04", "--",
        "setsid", "-w", "bash", "/mnt/c/cases/a/.easyfoam/mesh.sh",
    ]  # fmt: skip


def test_wsl_runtime_kills_the_whole_session_of_a_running_script():
    rt = Runtime("wsl", "x", "/opt/of/etc/bashrc", "Ubuntu-24.04")
    assert rt.kill_argv(4321) == ["wsl.exe", "-d", "Ubuntu-24.04", "--", "pkill", "-KILL", "-s", "4321"]


def test_script_announces_its_process_id_first_so_it_can_be_stopped():
    text = render_script("/opt/of/etc/bashrc", "/c", [Step("a", "true")])
    assert text.splitlines()[1] == 'echo "@@EASYFOAM pid $$"'


def test_script_sources_environment_enters_case_and_stops_at_first_failing_step():
    text = render_script(
        "/opt/of/etc/bashrc",
        "/mnt/c/cases/My Case",
        [Step("blockMesh", "blockMesh"), Step("solve", "mpirun -np 4 simpleFoam -parallel")],
    )
    assert "\r" not in text
    lines = text.splitlines()
    assert lines[0] == "#!/bin/bash"
    assert "source /opt/of/etc/bashrc" in lines
    assert 'cd "/mnt/c/cases/My Case" || exit 97' in lines
    i = lines.index('echo "@@EASYFOAM step blockMesh"')
    assert lines[i + 1] == "blockMesh 2>&1 | tee log.blockMesh"
    assert lines[i + 2] == 'rc=${PIPESTATUS[0]}; if [ "$rc" -ne 0 ]; then echo "@@EASYFOAM failed blockMesh $rc"; exit "$rc"; fi'
    assert "mpirun -np 4 simpleFoam -parallel 2>&1 | tee log.solve" in lines
    assert lines[-1] == 'echo "@@EASYFOAM done"'


def test_stream_process_delivers_lines_in_order_and_returns_exit_code():
    got = []
    code = stream_process(
        [sys.executable, "-c", "print('one'); print('two'); raise SystemExit(3)"], got.append
    )
    assert got == ["one", "two"]
    assert code == 3


def test_stream_process_can_be_stopped_from_another_thread():
    stop = threading.Event()
    got = []

    def on_line(line):
        got.append(line)
        stop.set()

    code = stream_process(
        [sys.executable, "-u", "-c", "import time; print('started', flush=True); time.sleep(60)"],
        on_line,
        stop_event=stop,
    )
    assert got == ["started"]
    assert code != 0
