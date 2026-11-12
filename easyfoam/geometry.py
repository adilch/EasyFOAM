"""Geometry helpers: STL import, bounding boxes and sizing the base mesh."""

from __future__ import annotations

import math
import re
import struct
import tempfile
from pathlib import Path

import numpy as np

from easyfoam import drawn
from easyfoam.model import Project, Shape

_VERTEX = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")
_SOLID = re.compile(rb"^[ \t]*solid\b[ \t]*([^\r\n]*)", re.MULTILINE)
_SOLID_LINE = re.compile(rb"^[ \t]*(end)?solid\b[ \t]*([^\r\n]*)", re.MULTILINE)
#: length units a geometry file may be in -> factor to metres
UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254}
CAD_SUFFIXES = (".step", ".stp", ".iges", ".igs", ".brep")
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


def _scale_stl(data: bytes, factor: float) -> bytes:
    """Multiply every coordinate of an ASCII or binary STL by a factor."""
    count = _binary_count(data)
    if count:
        records = np.frombuffer(data, dtype=_BINARY_RECORD, count=count, offset=84).copy()
        records["points"] *= factor
        return data[:84] + records.tobytes()

    def scaled(match: re.Match) -> bytes:
        return b"vertex " + b" ".join(repr(float(g) * factor).encode() for g in match.groups())

    return _VERTEX.sub(scaled, data)


def import_stl(case_dir: Path, source: Path, name: str | None = None, scale: float = 1.0) -> Shape:
    """Copy an STL into ``constant/triSurface`` (converted to metres) and return its shape.

    ``scale`` is the size of the file's length unit in metres (see :data:`UNITS`).
    """
    source = Path(source)
    stl_points(source)  # fail early on files that are not STL
    name = safe_name(name or source.stem)
    folder = Path(case_dir) / "constant" / "triSurface"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.stl"
    data = source.read_bytes()
    regions: list[str] = []
    if not _binary_count(data):
        data, regions = _rename_solids(data)
    if scale != 1.0:
        data = _scale_stl(data, scale)
    target.write_bytes(data)
    shape = Shape(name=name, kind="stl", file=f"{name}.stl")
    if len(regions) > 1:
        shape.regions = {region: "wall" for region in regions}
    return shape


def import_cad(
    case_dir: Path,
    source: Path,
    name: str | None = None,
    scale: float = 1.0,
    faces_as_regions: bool = False,
) -> Shape:
    """Import a STEP, IGES or BREP file by turning its faces into a triangulated surface.

    With ``faces_as_regions`` every CAD face becomes its own region, so single faces can be
    made inlets or outlets. Needs the optional ``gmsh`` package.
    """
    try:
        import gmsh
    except ImportError as exc:
        raise RuntimeError(
            "Reading STEP / IGES files needs the optional gmsh package. Install it with:  pip install gmsh"
        ) from exc
    source = Path(source)
    name = safe_name(name or source.stem)
    with tempfile.TemporaryDirectory() as folder:
        surface = Path(folder) / f"{name}.stl"
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.open(str(source))
            x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(-1, -1)
            diagonal = math.dist((x0, y0, z0), (x1, y1, z1)) or 1.0
            gmsh.option.setNumber("Mesh.MeshSizeMax", diagonal / 15.0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)  # triangles around a full circle
            gmsh.option.setNumber("Mesh.Binary", 0)
            gmsh.option.setNumber("Mesh.StlOneSolidPerSurface", 1 if faces_as_regions else 0)
            gmsh.model.mesh.generate(2)
            gmsh.write(str(surface))
        except Exception as exc:
            raise ValueError(f"{source.name} could not be read as a CAD file: {exc}") from exc
        finally:
            gmsh.finalize()
        return import_stl(case_dir, surface, name, scale)


def import_geometry(case_dir: Path, source: Path, name: str | None = None, unit: str = "m", **options) -> Shape:
    """Import an STL or CAD file given in the named length unit."""
    source = Path(source)
    if source.suffix.lower() in CAD_SUFFIXES:
        return import_cad(case_dir, source, name, UNITS[unit], **options)
    return import_stl(case_dir, source, name, UNITS[unit])


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


def is_surface(shape: Shape) -> bool:
    """Does the shape reach the mesher as a surface file (imported, or written from a drawn shape)?"""
    return shape.kind == "stl" or drawn.is_drawn(shape)


def surface_file(shape: Shape) -> str:
    """Name of the shape's file in ``constant/triSurface``."""
    return f"{shape.name}.stl" if drawn.is_drawn(shape) else shape.file


def surface_triangles(shape: Shape, case_dir: Path | None) -> np.ndarray:
    """The triangles of an imported or drawn shape."""
    if drawn.is_drawn(shape):
        return drawn.triangulate(shape)
    if case_dir is None:
        raise ValueError(f"the case folder is needed to read the surface of '{shape.name}'")
    return stl_triangles(Path(case_dir) / "constant" / "triSurface" / shape.file)


def drawn_files(project: Project) -> dict[str, str]:
    """The surface files of the drawn shapes, as ``{relative path: text}``."""
    return {
        f"constant/triSurface/{surface_file(s)}": drawn.ascii_stl(s.name, drawn.triangulate(s))
        for s in project.shapes
        if drawn.is_drawn(s)
    }


def new_shape(kind: str, name: str, project: Project) -> Shape:
    """A new shape of a sensible size in the middle of the base mesh, ready to be adjusted."""
    lo, hi = project.mesh.base.min, project.mesh.base.max
    cx, cy, cz = ((a + b) / 2 for a, b in zip(lo, hi))
    size = 0.4 * min(b - a for a, b in zip(lo, hi))
    half = size / 2
    shape = Shape(name=name, kind=kind)
    if kind in ("box", "wedge"):
        shape.min, shape.max = [cx - half, cy - half, cz - half], [cx + half, cy + half, cz + half]
    elif kind == "sphere":
        shape.centre, shape.radius = [cx, cy, cz], half
    elif kind == "cylinder":
        shape.point1, shape.point2, shape.radius = [cx - half, cy, cz], [cx + half, cy, cz], half / 2
    elif kind == "cone":
        shape.point1, shape.point2 = [cx, cy, cz - half], [cx, cy, cz + half]
        shape.radius, shape.radius2 = half, half / 2
    elif kind == "profile":  # a small weir on the bed, right across the base mesh
        height, width = hi[2] - lo[2], hi[1] - lo[1]
        bottom, top = lo[2] - 0.25 * height, lo[2] + 0.35 * height
        shape.points = [[cx - 1.5 * size, bottom], [cx + 1.5 * size, bottom], [cx + half, top], [cx - half, top]]
        shape.plane, shape.extent = "xz", [lo[1] - 0.5 * width, hi[1] + 0.5 * width]
    return shape


shape_problem = drawn.problem
triangulate = drawn.triangulate


def shape_bounds(shape: Shape, case_dir: Path | None) -> tuple[list[float], list[float]]:
    if drawn.is_drawn(shape):
        points = drawn.triangulate(shape).reshape(-1, 3)
        return points.min(axis=0).tolist(), points.max(axis=0).tolist()
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


def _unit(vector) -> np.ndarray:
    v = np.asarray(vector, dtype=float)
    length = float(np.linalg.norm(v))
    if length == 0:
        raise ValueError("the direction must not be zero")
    return v / length


def frontal_area(project: Project, case_dir: Path, direction) -> float:
    """Area of the solid shapes as seen along a direction (their silhouette), in m2.

    Exact for convex bodies; for hollow or overlapping shapes it is an upper estimate.
    """
    d = _unit(direction)
    total = 0.0
    for shape in project.shapes:
        if shape.role != "wall":
            continue
        if shape.kind == "sphere":
            total += math.pi * shape.radius**2
        elif shape.kind == "box":
            sx, sy, sz = (hi - lo for lo, hi in zip(shape.min, shape.max))
            total += abs(d[0]) * sy * sz + abs(d[1]) * sx * sz + abs(d[2]) * sx * sy
        elif shape.kind == "cylinder":
            axis = np.asarray(shape.point2, float) - np.asarray(shape.point1, float)
            length = float(np.linalg.norm(axis))
            along = abs(float(d @ axis)) / length if length else 1.0
            total += along * math.pi * shape.radius**2
            total += math.sqrt(max(0.0, 1.0 - along**2)) * 2.0 * shape.radius * length
        else:
            triangles = surface_triangles(shape, case_dir)
            normals = 0.5 * np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            total += 0.5 * float(np.abs(normals @ d).sum())
    return total


def rename_shape(project: Project, old: str, new: str) -> str:
    """Rename a shape and everything that refers to it; returns the name actually used."""
    new = safe_name(new)
    shape = next((s for s in project.shapes if s.name == old), None)
    if shape is None:
        raise ValueError(f"there is no shape named '{old}'")
    if new == old:
        return new
    if any(s.name == new for s in project.shapes):
        raise ValueError(f"a shape named '{new}' already exists")

    def moved(name: str) -> str:
        return new + name[len(old):] if name == old or name.startswith(old + "_") else name

    shape.name = new
    if project.mesh.fluid_inside == old:
        project.mesh.fluid_inside = new
    project.boundaries = {moved(name): value for name, value in project.boundaries.items()}
    project.forces.patches = [moved(name) for name in project.forces.patches]
    return new


def mass_properties(shape: Shape, case_dir: Path, density: float) -> tuple[float, list[float], list[float]]:
    """Mass, centre of mass and moments of inertia (about the x, y, z axes through the centre) of a solid shape."""
    if shape.kind == "box":
        a, b, c = (hi - lo for lo, hi in zip(shape.min, shape.max))
        mass = density * a * b * c
        centre = [(lo + hi) / 2 for lo, hi in zip(shape.min, shape.max)]
        return mass, centre, [mass / 12 * (b * b + c * c), mass / 12 * (a * a + c * c), mass / 12 * (a * a + b * b)]
    if shape.kind == "sphere":
        mass = density * 4.0 / 3.0 * math.pi * shape.radius**3
        return mass, list(shape.centre), [0.4 * mass * shape.radius**2] * 3
    if shape.kind == "cylinder":
        p1, p2 = np.asarray(shape.point1, float), np.asarray(shape.point2, float)
        length = float(np.linalg.norm(p2 - p1))
        axis = (p2 - p1) / length
        mass = density * math.pi * shape.radius**2 * length
        along = 0.5 * mass * shape.radius**2
        across = mass / 12 * (3 * shape.radius**2 + length**2)
        inertia = [across * (1 - a * a) + along * a * a for a in axis]
        return mass, ((p1 + p2) / 2).tolist(), [float(i) for i in inertia]

    triangles = surface_triangles(shape, case_dir)
    if _open_edges(triangles):
        raise ValueError(f"'{shape.name}' is not a closed surface, so its mass cannot be worked out")
    origin = triangles.reshape(-1, 3).mean(axis=0)
    a, b, c = (triangles[:, i] - origin for i in range(3))
    volumes = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0  # signed tetrahedra to the origin
    volume = float(volumes.sum())
    sign = 1.0 if volume > 0 else -1.0
    volume, volumes = abs(volume), volumes * sign
    centroid = ((a + b + c) / 4.0 * volumes[:, None]).sum(axis=0) / volume
    total = a + b + c
    second = sum(np.einsum("n,ni,nj->ij", volumes, v, v) for v in (a, b, c)) + np.einsum("n,ni,nj->ij", volumes, total, total)
    second = second / 20.0 - volume * np.outer(centroid, centroid)  # about the centroid
    xx, yy, zz = second[0, 0], second[1, 1], second[2, 2]
    inertia = [density * (yy + zz), density * (xx + zz), density * (xx + yy)]
    return density * volume, (origin + centroid).tolist(), [float(i) for i in inertia]
