"""Geometry helpers: STL import, bounding boxes and sizing the base mesh."""

from __future__ import annotations

import math
import re
import shutil
import struct
from pathlib import Path

import numpy as np

from easyfoam.model import Project, Shape

_VERTEX = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")
_SOLID = re.compile(rb"^[ \t]*solid\b[ \t]*([^\r\n]*)", re.MULTILINE)
_SOLID_LINE = re.compile(rb"^[ \t]*(end)?solid\b[ \t]*([^\r\n]*)", re.MULTILINE)
_BINARY_RECORD = np.dtype([("normal", "<f4", 3), ("points", "<f4", (3, 3)), ("attr", "<u2")])


def _binary_count(data: bytes) -> int:
    """Number of triangles when the data is a binary STL, else 0."""
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if count > 0 and len(data) == 84 + 50 * count:  # exact size match: binary
            return count
    return 0


def stl_points(path: Path) -> np.ndarray:
    """All triangle corner points of an ASCII or binary STL as an (n, 3) array."""
    data = Path(path).read_bytes()
    count = _binary_count(data)
    if count:
        records = np.frombuffer(data, dtype=_BINARY_RECORD, count=count, offset=84)
        return records["points"].reshape(-1, 3).astype(float)
    points = np.array([[float(c) for c in m.groups()] for m in _VERTEX.finditer(data)], dtype=float)
    if points.size == 0 or len(points) % 3:
        raise ValueError(f"{Path(path).name} contains no triangles (is it a valid STL file?)")
    return points


def stl_triangles(path: Path) -> np.ndarray:
    """The triangles of an STL as an (n, 3, 3) array."""
    return stl_points(path).reshape(-1, 3, 3)


def stl_bounds(path: Path) -> tuple[list[float], list[float]]:
    points = stl_points(path)
    return points.min(axis=0).tolist(), points.max(axis=0).tolist()


def stl_regions(path: Path) -> list[str]:
    """Names of the solids of an ASCII STL, in file order (empty for binary files)."""
    data = Path(path).read_bytes()
    if _binary_count(data):
        return []
    return [m.group(1).decode("latin-1").strip() for m in _SOLID.finditer(data)]


def safe_name(text: str) -> str:
    """A name OpenFOAM accepts as a patch/surface name."""
    name = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    if not name or not name[0].isalpha():
        name = "s_" + name
    return name


def _rename_solids(data: bytes) -> tuple[bytes, list[str]]:
    """Give every solid of an ASCII STL a unique, OpenFOAM-safe name."""
    names: list[str] = []
    current = [""]

    def replace(match: re.Match) -> bytes:
        if match.group(1):  # endsolid
            return b"endsolid " + current[0].encode()
        wanted = safe_name(match.group(2).decode("latin-1").strip() or f"region{len(names)}")
        name, n = wanted, 2
        while name in names:
            name, n = f"{wanted}_{n}", n + 1
        names.append(name)
        current[0] = name
        return b"solid " + name.encode()

    return _SOLID_LINE.sub(replace, data), names


def import_stl(case_dir: Path, source: Path, name: str | None = None) -> Shape:
    """Copy an STL into ``constant/triSurface`` and return the shape describing it."""
    source = Path(source)
    stl_points(source)  # fail early on files that are not STL
    name = safe_name(name or source.stem)
    folder = Path(case_dir) / "constant" / "triSurface"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.stl"
    data = source.read_bytes()
    regions: list[str] = []
    if _binary_count(data):
        shutil.copyfile(source, target)
    else:
        data, regions = _rename_solids(data)
        target.write_bytes(data)
    shape = Shape(name=name, kind="stl", file=f"{name}.stl")
    if len(regions) > 1:
        shape.regions = {region: "wall" for region in regions}
    return shape


_RAYS = np.array([[0.5371, 0.2113, 0.8166], [-0.5371, -0.2113, -0.8166], [0.2673, -0.8018, 0.5345]])


def _crossings(point: np.ndarray, triangles: np.ndarray, direction: np.ndarray) -> int:
    """How many triangles a ray from the point hits (Moller-Trumbore, vectorised)."""
    v0 = triangles[:, 0]
    e1, e2 = triangles[:, 1] - v0, triangles[:, 2] - v0
    h = np.cross(direction, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > 1e-14
    f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    s = point - v0
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * (q @ direction)
    t = f * np.einsum("ij,ij->i", e2, q)
    return int(np.count_nonzero(ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-12)))


def _open_edges(triangles: np.ndarray) -> int:
    """Number of edges that do not belong to exactly two triangles."""
    scale = float(np.ptp(triangles.reshape(-1, 3), axis=0).max()) or 1.0
    keys = np.round(triangles.reshape(-1, 3) / (scale * 1e-7)).astype(np.int64)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    ids = ids.reshape(-1, 3)
    edges = np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]])
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int(np.count_nonzero(counts != 2))


def interior_point(triangles: np.ndarray, lo=None, hi=None) -> list[float]:
    """A point enclosed by a closed triangulated surface (optionally within the box lo-hi)."""
    triangles = np.asarray(triangles, dtype=float)
    open_edges = _open_edges(triangles)
    if open_edges:
        raise ValueError(
            f"the surface is not closed ({open_edges} open or shared edges), so it has no inside; "
            "close it (cap the openings) or set the point inside the fluid by hand"
        )
    points = triangles.reshape(-1, 3)
    diagonal = float(np.linalg.norm(np.ptp(points, axis=0)))
    low = np.array(lo, dtype=float) if lo is not None else points.min(axis=0) - 1.0
    high = np.array(hi, dtype=float) if hi is not None else points.max(axis=0) + 1.0
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    usable = np.nonzero(lengths > 0)[0]
    sample = usable[:: max(1, len(usable) // 300)]
    for step in (0.02, 0.005, 0.001):
        for index in sample:
            centroid = triangles[index].mean(axis=0)
            normal = normals[index] / lengths[index]
            for sign in (-1.0, 1.0):
                point = centroid + sign * step * diagonal * normal
                if np.any(point <= low) or np.any(point >= high):
                    continue
                if all(_crossings(point, triangles, ray) % 2 == 1 for ray in _RAYS):
                    return point.tolist()
    raise ValueError("no point inside the closed surface was found within the base mesh")


def shape_bounds(shape: Shape, case_dir: Path) -> tuple[list[float], list[float]]:
    if shape.kind == "stl":
        return stl_bounds(Path(case_dir) / "constant" / "triSurface" / shape.file)
    if shape.kind == "sphere":
        return [c - shape.radius for c in shape.centre], [c + shape.radius for c in shape.centre]
    if shape.kind == "cylinder":
        lo = [min(a, b) - shape.radius for a, b in zip(shape.point1, shape.point2)]
        hi = [max(a, b) + shape.radius for a, b in zip(shape.point1, shape.point2)]
        return lo, hi
    return list(shape.min), list(shape.max)


def geometry_bounds(project: Project, case_dir: Path) -> tuple[list[float], list[float]]:
    walls = [s for s in project.shapes if s.role == "wall"]
    if not walls:
        raise ValueError("there is no geometry to fit the base mesh around")
    boxes = [shape_bounds(s, case_dir) for s in walls]
    lo = [min(b[0][i] for b in boxes) for i in range(3)]
    hi = [max(b[1][i] for b in boxes) for i in range(3)]
    return lo, hi


def fit_base_mesh(
    project: Project,
    case_dir: Path,
    cell_size: float | None = None,
    upstream: float = 2.0,
    downstream: float = 5.0,
    lateral: float = 2.0,
) -> None:
    """Size the base mesh as a wind tunnel around the geometry (flow along +x).

    Margins are multiples of the geometry's largest dimension; cells are cubes.
    """
    inside = next((sh for sh in project.shapes if sh.name == project.mesh.fluid_inside), None)
    if inside is not None:  # internal flow: a snug box, one and a half cells of margin
        lo, hi = shape_bounds(inside, case_dir)
        cell = cell_size or min(h - low for low, h in zip(lo, hi)) / 10.0
        base = project.mesh.base
        base.min = [low - 1.5 * cell for low in lo]
        base.cells = [max(1, math.ceil((h + 1.5 * cell - a) / cell - 1e-9)) for a, h in zip(base.min, hi)]
        base.max = [a + n * cell for a, n in zip(base.min, base.cells)]
        return
    lo, hi = geometry_bounds(project, case_dir)
    size = max(h - low for low, h in zip(lo, hi)) or 1.0
    cell = cell_size or size / 4.0
    new_min = [lo[0] - upstream * size, lo[1] - lateral * size, lo[2] - lateral * size]
    wanted_max = [hi[0] + downstream * size, hi[1] + lateral * size, hi[2] + lateral * size]
    cells = [max(1, math.ceil((b - a) / cell - 1e-9)) for a, b in zip(new_min, wanted_max)]
    base = project.mesh.base
    base.min = new_min
    base.cells = cells
    base.max = [a + n * cell for a, n in zip(new_min, cells)]
