"""v0.8 end-to-end: drawn shapes (cone, wedge, sketched outline) with a real OpenFOAM."""

import pytest

from easyfoam.examples import weir
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.model import Project, Shape
from easyfoam.pipeline import Job, prepare_mesh, prepare_run
from easyfoam.runtime import detect_runtimes

pytestmark = pytest.mark.openfoam


@pytest.fixture(scope="module")
def runtime():
    found = detect_runtimes()
    if not found:
        pytest.skip("no OpenFOAM runtime found on this machine")
    return found[0]


def do(case, runtime, name, steps, parse=None):
    lines = []
    result = Job(case, runtime, name, steps, on_line=lines.append, parse_step=parse).run()
    assert result.ok, f"{name} failed in {result.failed_step}:\n" + "\n".join(lines[-40:])
    return lines


def cells(lines) -> int:
    counts = [int(line.split()[-1]) for line in lines if line.strip().startswith("cells:")]
    assert counts, "checkMesh did not report the number of cells"
    return counts[-1]


def test_cone_wedge_and_sketched_outline_are_cut_out_of_the_mesh(tmp_path, runtime):
    p = Project(name="drawn")
    base = p.mesh.base
    base.min, base.max, base.cells = [0, 0, 0], [4, 1, 1], [40, 10, 10]
    p.shapes += [
        Shape("cone", kind="cone", point1=[0.8, 0.5, 0.2], point2=[0.8, 0.5, 0.8], radius=0.25, radius2=0.1),
        Shape("ramp", kind="wedge", min=[1.6, -1, -1], max=[2.2, 2, 0.4], rise="+x"),
        Shape("sill", kind="profile", points=[[2.9, -1], [3.5, -1], [3.3, 0.3], [3.1, 0.3]], plane="xz", extent=[-1, 2]),
    ]
    case = tmp_path / "drawn"
    p.save(case)
    lines = do(case, runtime, "mesh", prepare_mesh(case, p))
    assert any("Mesh OK" in line for line in lines)
    faces = {patch.name: patch.n_faces for patch in read_boundary(case)}
    assert all(faces.get(name, 0) > 20 for name in ("cone", "ramp", "sill")), faces
    assert (case / "constant" / "triSurface" / "sill.stl").is_file()  # written with the case, like an imported file
    assert cells(lines) > 4000  # the 4,000 base cells, less the bodies, plus the finer cells on their surfaces


def test_a_weir_drawn_as_an_outline_meshes_and_runs_like_the_same_weir_as_a_box(tmp_path, runtime):
    counts = {}
    for label in ("box", "outline"):
        p = weir("weir")
        if label == "outline":
            box = p.shapes[0]
            p.shapes[0] = Shape(
                "weir", kind="profile", level_min=box.level_min, level_max=box.level_max, plane="xz",
                points=[[box.min[0], box.min[2]], [box.max[0], box.min[2]], [box.max[0], box.max[2]], [box.min[0], box.max[2]]],
                extent=[box.min[1], box.max[1]],
            )  # fmt: skip
        case = tmp_path / label
        p.save(case)
        counts[label] = cells(do(case, runtime, "mesh", prepare_mesh(case, p)))
        if label == "outline":
            p.run.end_time, p.run.write_interval, p.run.processors = 0.3, 0.3, 2
            p.save(case)
            do(case, runtime, "run", prepare_run(case, p), parse="interFoam")
    assert counts["outline"] == pytest.approx(counts["box"], rel=0.03)
