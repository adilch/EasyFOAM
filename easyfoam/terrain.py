"""Ground surfaces from survey data: a river reach or a floodplain to run free-surface flow over.

Reads XYZ point clouds, ESRI ASCII grids (.asc), GeoTIFF elevation rasters and LandXML TIN surfaces. The
ground is resampled on a regular grid in local coordinates, shifted so the numbers stay small (survey
coordinates run into millions of metres) and turned so the river runs along x, then closed into a solid:
the ground surface on top, walls down its edges and a flat bottom. snappyHexMesh cuts that solid out of the
base mesh, leaving the water and the air above the ground.
"""

from __future__ import annotations

import math
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: what can be read, by file name ending
FORMATS = {
    ".xyz": "XYZ points", ".txt": "XYZ points", ".csv": "XYZ points", ".pts": "XYZ points",
    ".asc": "ESRI ASCII grid", ".tif": "GeoTIFF", ".tiff": "GeoTIFF", ".xml": "LandXML", ".landxml": "LandXML",
}  # fmt: skip
NAME = "terrain"  # the shape, its STL file and its boundary
MAX_NODES = 1_500_000  # nodes of the regular grid at most: about three million triangles


@dataclass
class Survey:
    """Elevations as read from a file, in the file's own coordinates."""

    points: np.ndarray  # (n, 3): x, y, z of every point with data
    triangles: np.ndarray | None = None  # (m, 3) indices into points: a TIN (LandXML)
    grid: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None  # x (nx), y (ny), z (ny, nx); NaN = no data
    kind: str = ""

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.points.min(axis=0), self.points.max(axis=0)

    def spacing(self) -> float:
        """The distance between survey points, roughly."""
        if self.grid is not None:
            x, y, _ = self.grid
            return float(min(abs(x[1] - x[0]) if len(x) > 1 else 1.0, abs(y[1] - y[0]) if len(y) > 1 else 1.0))
        lo, hi = self.bounds()
        area = max((hi[0] - lo[0]) * (hi[1] - lo[1]), 1e-9)
        return float(math.sqrt(area / max(len(self.points), 1)))


@dataclass
class Ground:
    """The ground on a regular grid in local coordinates."""

    x: np.ndarray  # (nx,)
    y: np.ndarray  # (ny,)
    z: np.ndarray  # (ny, nx)
    origin: tuple[float, float] = (0.0, 0.0)  # survey coordinates of the local (0, 0)
    angle: float = 0.0  # degrees the survey was turned clockwise so that the river runs along +x

    @property
    def spacing(self) -> float:
        return float(self.x[1] - self.x[0]) if len(self.x) > 1 else 1.0


# --- reading -----------------------------------------------------------------------------------------------------


def read_survey(path: Path) -> Survey:
    """Read a survey file; the kind is told by its ending (see FORMATS)."""
    path = Path(path)
    kind = FORMATS.get(path.suffix.lower())
    if kind is None:
        raise ValueError(f"cannot read '{path.name}': use one of " + ", ".join(sorted(FORMATS)))
    reader = {"XYZ points": read_xyz, "ESRI ASCII grid": read_ascii_grid, "GeoTIFF": read_geotiff,
              "LandXML": read_landxml}[kind]  # fmt: skip
    survey = reader(path)
    if len(survey.points) < 3:
        raise ValueError(f"'{path.name}' holds fewer than three points with an elevation")
    survey.kind = kind
    return survey


_NUMBER_LINE = re.compile(r"^\s*[-+0-9.]")


def read_xyz(path: Path) -> Survey:
    """Lines of x, y, z separated by spaces, tabs, commas or semicolons; other lines (headers) are skipped."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not _NUMBER_LINE.match(line):
                continue
            parts = re.split(r"[\s,;]+", line.strip())
            try:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except (ValueError, IndexError):
                continue
    points = np.asarray(rows, float).reshape(-1, 3)
    return Survey(points[np.all(np.isfinite(points), axis=1)])


def _grid_survey(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> Survey:
    """A raster with rows running north to south; y is returned increasing."""
    if len(y) > 1 and y[1] < y[0]:
        y, z = y[::-1], z[::-1]
    gx, gy = np.meshgrid(x, y)
    keep = np.isfinite(z)
    points = np.column_stack([gx[keep], gy[keep], z[keep]])
    return Survey(points, grid=(np.asarray(x, float), np.asarray(y, float), z))


def read_ascii_grid(path: Path) -> Survey:
    """An ESRI ASCII grid: a header (ncols, nrows, xllcorner or xllcenter, ..., cellsize, NODATA_value) then rows."""
    header: dict[str, float] = {}
    values: list[float] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if parts[0][0].isalpha() and len(parts) >= 2 and not values:
                header[parts[0].lower()] = float(parts[1])
            else:
                values.extend(float(v) for v in parts)
    try:
        nx, ny, size = int(header["ncols"]), int(header["nrows"]), header["cellsize"]
    except KeyError as exc:
        raise ValueError(f"'{Path(path).name}' is not an ESRI ASCII grid: no {exc.args[0]} in its header") from exc
    if len(values) < nx * ny:
        raise ValueError(f"'{Path(path).name}' has {len(values)} values for a grid of {nx} x {ny}")
    z = np.asarray(values[: nx * ny], float).reshape(ny, nx)
    if "nodata_value" in header:
        z[z == header["nodata_value"]] = np.nan
    x0 = header["xllcenter"] if "xllcenter" in header else header["xllcorner"] + size / 2
    y0 = header["yllcenter"] if "yllcenter" in header else header["yllcorner"] + size / 2
    x = x0 + size * np.arange(nx)
    y = y0 + size * np.arange(ny)[::-1]  # the first row is the northernmost
    return _grid_survey(x, y, z)


def read_geotiff(path: Path) -> Survey:
    """A single-band GeoTIFF of elevations, placed by its pixel scale and tie point."""
    from PIL import Image

    with Image.open(path) as image:
        tags = dict(image.tag_v2)
        try:
            z = np.asarray(image, dtype=float)
        except (TypeError, ValueError):
            z = np.asarray(image.convert("F"), dtype=float)
    if z.ndim == 3:
        z = z[:, :, 0]
    if 34264 in tags:
        raise ValueError("this GeoTIFF is rotated (it has a transformation matrix); save it north-up first")
    try:
        sx, sy = float(tags[33550][0]), float(tags[33550][1])
        i, j, _k, x, y = (float(v) for v in tags[33922][:5])
    except (KeyError, IndexError) as exc:
        raise ValueError(f"'{Path(path).name}' has no georeference (pixel scale and tie point)") from exc
    nodata = tags.get(42113)
    if nodata not in (None, ""):
        try:
            z[z == float(str(nodata).strip("\x00 "))] = np.nan
        except ValueError:
            pass
    z[np.abs(z) > 1e20] = np.nan  # common no-data markers such as -3.4e38
    point = _pixel_is_point(tags.get(34735))
    shift = 0.0 if point else 0.5
    ny, nx = z.shape
    xs = x + (np.arange(nx) + shift - i) * sx
    ys = y - (np.arange(ny) + shift - j) * sy
    return _grid_survey(xs, ys, z)


def _pixel_is_point(directory) -> bool:
    """Whether the GeoKey directory says the tie point is at a pixel's centre (RasterPixelIsPoint)."""
    if not directory:
        return False
    keys = list(directory)
    for k in range(4, len(keys) - 3, 4):
        if keys[k] == 1025 and keys[k + 1] == 0:  # GTRasterTypeGeoKey, value stored inline
            return keys[k + 3] == 2
    return False


def read_landxml(path: Path) -> Survey:
    """A LandXML TIN surface: points (northing, easting, elevation) and the triangles between them."""
    root = ET.parse(path).getroot()

    def local(element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    surfaces = [el for el in root.iter() if local(el) == "Surface"]
    if not surfaces:
        raise ValueError(f"'{Path(path).name}' has no Surface")
    ids: dict[str, int] = {}
    points, faces = [], []
    for element in surfaces[0].iter():
        tag = local(element)
        if tag == "P" and element.text:
            north, east, height = (float(v) for v in element.text.split()[:3])
            ids[element.get("id", str(len(points) + 1))] = len(points)
            points.append([east, north, height])
        elif tag == "F" and element.text and element.get("i") != "1":  # i="1": a face left out of the surface
            faces.append(element.text.split()[:3])
    triangles = [[ids[a] for a in face] for face in faces if all(a in ids for a in face)]
    survey = Survey(np.asarray(points, float).reshape(-1, 3))
    if triangles:
        survey.triangles = np.asarray(triangles, int)
    return survey


# --- to a regular grid in local coordinates -----------------------------------------------------------------------


def to_local(xy: np.ndarray, origin: tuple[float, float], angle: float) -> np.ndarray:
    """Survey coordinates to local ones: moved to the origin, then turned clockwise by ``angle`` degrees."""
    a = math.radians(angle)
    d = np.asarray(xy, float)[..., :2] - np.asarray(origin, float)
    c, s = math.cos(a), math.sin(a)
    return np.stack([c * d[..., 0] + s * d[..., 1], -s * d[..., 0] + c * d[..., 1]], axis=-1)


def from_local(xy: np.ndarray, origin: tuple[float, float], angle: float) -> np.ndarray:
    a = math.radians(angle)
    d = np.asarray(xy, float)
    c, s = math.cos(a), math.sin(a)
    return np.stack([c * d[..., 0] - s * d[..., 1] + origin[0], s * d[..., 0] + c * d[..., 1] + origin[1]], axis=-1)


def default_origin(survey: Survey) -> tuple[float, float]:
    """Survey coordinates in the thousands of kilometres move to a round 100 m near the south-west corner, so
    local ones stay small and positive; small coordinates (a model already in local ones) stay as they are."""
    lo, hi = survey.bounds()
    if max(abs(lo[0]), abs(lo[1]), abs(hi[0]), abs(hi[1])) < 1e4:
        return 0.0, 0.0
    return float(math.floor(lo[0] / 100.0) * 100.0), float(math.floor(lo[1] / 100.0) * 100.0)


def local_extent(survey: Survey, origin: tuple[float, float], angle: float) -> tuple[float, float, float, float]:
    """xmin, ymin, xmax, ymax of the survey in local coordinates."""
    local = to_local(survey.points, origin, angle)
    return (float(local[:, 0].min()), float(local[:, 1].min()), float(local[:, 0].max()), float(local[:, 1].max()))


def ground(survey: Survey, spacing: float, origin: tuple[float, float] | None = None, angle: float = 0.0,
           region: tuple[float, float, float, float] | None = None) -> Ground:  # fmt: skip
    """The ground on a regular grid of the given spacing over ``region`` (local xmin, ymin, xmax, ymax)."""
    if spacing <= 0:
        raise ValueError("the grid spacing must be above zero")
    origin = default_origin(survey) if origin is None else origin
    x0, y0, x1, y1 = region or local_extent(survey, origin, angle)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the region is empty")
    nx, ny = int(round((x1 - x0) / spacing)) + 1, int(round((y1 - y0) / spacing)) + 1
    if nx * ny > MAX_NODES:
        raise ValueError(f"a {spacing:g} m grid over this region has {nx * ny:,} points; use a coarser spacing")
    if nx < 2 or ny < 2:
        raise ValueError("the region is smaller than one grid spacing")
    gx, gy = np.linspace(x0, x0 + (nx - 1) * spacing, nx), np.linspace(y0, y0 + (ny - 1) * spacing, ny)
    qx, qy = np.meshgrid(gx, gy)
    if survey.grid is not None:
        where = from_local(np.stack([qx, qy], axis=-1), origin, angle)
        z = _bilinear(*survey.grid, where[..., 0], where[..., 1])
    else:
        z = _from_points(survey, origin, angle, qx, qy, spacing)
    return Ground(gx, gy, _filled(z), origin, angle)


def _bilinear(x: np.ndarray, y: np.ndarray, z: np.ndarray, qx: np.ndarray, qy: np.ndarray) -> np.ndarray:
    """Interpolate a raster (x, y increasing) at points; NaN outside it or next to missing data."""
    fx = (qx - x[0]) / (x[1] - x[0]) if len(x) > 1 else np.zeros_like(qx)
    fy = (qy - y[0]) / (y[1] - y[0]) if len(y) > 1 else np.zeros_like(qy)
    inside = (fx >= -1e-9) & (fx <= len(x) - 1 + 1e-9) & (fy >= -1e-9) & (fy <= len(y) - 1 + 1e-9)
    i = np.clip(np.floor(fx).astype(int), 0, max(len(x) - 2, 0))
    j = np.clip(np.floor(fy).astype(int), 0, max(len(y) - 2, 0))
    tx, ty = np.clip(fx - i, 0, 1), np.clip(fy - j, 0, 1)
    i1, j1 = np.minimum(i + 1, len(x) - 1), np.minimum(j + 1, len(y) - 1)
    value = (z[j, i] * (1 - tx) * (1 - ty) + z[j, i1] * tx * (1 - ty) + z[j1, i] * (1 - tx) * ty + z[j1, i1] * tx * ty)
    return np.where(inside, value, np.nan)


def _from_points(survey: Survey, origin, angle: float, qx: np.ndarray, qy: np.ndarray, spacing: float) -> np.ndarray:
    """Interpolate scattered points (or a TIN) linearly across their triangles onto the grid."""
    from matplotlib.tri import LinearTriInterpolator, Triangulation

    local = to_local(survey.points, origin, angle)
    heights = survey.points[:, 2]
    triangles = survey.triangles
    if triangles is None and len(local) > MAX_NODES:  # thin a dense cloud: the mean height in each grid cell
        local, heights = _binned(local, heights, qx[0, 0], qy[0, 0], spacing)
    mesh = Triangulation(local[:, 0], local[:, 1], triangles)
    value = LinearTriInterpolator(mesh, heights)(qx, qy)
    return np.ma.filled(value.astype(float), np.nan)


def _binned(local: np.ndarray, heights: np.ndarray, x0: float, y0: float, spacing: float):
    ix = np.floor((local[:, 0] - x0) / spacing + 0.5).astype(np.int64)
    iy = np.floor((local[:, 1] - y0) / spacing + 0.5).astype(np.int64)
    key = (iy - iy.min()) * (ix.max() - ix.min() + 1) + (ix - ix.min())
    _keys, inverse = np.unique(key, return_inverse=True)
    total = np.bincount(inverse, weights=heights)
    count = np.bincount(inverse)
    cx = np.bincount(inverse, weights=local[:, 0]) / count
    cy = np.bincount(inverse, weights=local[:, 1]) / count
    return np.column_stack([cx, cy]), total / count


def _filled(z: np.ndarray) -> np.ndarray:
    """Fill holes (no data, outside the survey) from their neighbours, so the ground is complete."""
    z = np.array(z, float)
    if np.all(np.isnan(z)):
        raise ValueError("the region holds no survey data")
    for _ in range(sum(z.shape)):  # one cell further each pass: enough to cross the grid
        missing = np.isnan(z)
        if not missing.any():
            break
        padded = np.pad(z, 1, constant_values=np.nan)
        near = np.stack([padded[1:-1, :-2], padded[1:-1, 2:], padded[:-2, 1:-1], padded[2:, 1:-1]])
        known = np.isfinite(near)
        mean = np.where(known.any(axis=0), np.nansum(np.where(known, near, 0), axis=0) / np.maximum(known.sum(axis=0), 1),
                        np.nan)  # fmt: skip
        z[missing] = mean[missing]
    z[np.isnan(z)] = np.nanmin(z)
    return z


# --- the solid -------------------------------------------------------------------------------------------------------


def solid(ground: Ground, base: float) -> np.ndarray:
    """A closed surface around the ground: its top, walls down its four edges to ``base`` and a flat bottom.

    Returns triangles (n, 3, 3) with their corners anticlockwise seen from outside.
    """
    x, y, z = ground.x, ground.y, ground.z
    if base >= float(np.nanmin(z)):
        raise ValueError("the bottom of the ground solid must lie below the lowest ground")
    top = np.stack([*np.meshgrid(x, y), z], axis=-1)  # (ny, nx, 3)
    a, b = top[:-1, :-1], top[:-1, 1:]
    c, d = top[1:, 1:], top[1:, :-1]
    tris = [np.stack([a, b, c], axis=-2).reshape(-1, 3, 3), np.stack([a, c, d], axis=-2).reshape(-1, 3, 3)]
    ring = np.concatenate([top[0, :], top[1:, -1], top[-1, -2::-1], top[-2:0:-1, 0]])  # anticlockwise from above
    low = ring.copy()
    low[:, 2] = base
    nxt = np.roll(np.arange(len(ring)), -1)
    tris.append(np.stack([ring, low, low[nxt]], axis=1))
    tris.append(np.stack([ring, low[nxt], ring[nxt]], axis=1))
    centre = np.array([x.mean(), y.mean(), base])
    tris.append(np.stack([np.broadcast_to(centre, low.shape), low[nxt], low], axis=1))
    return np.concatenate(tris)


def write_stl(path: Path, triangles: np.ndarray, name: str = NAME) -> Path:
    """Write triangles as a binary STL file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tri = np.asarray(triangles, np.float64)
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-30)
    record = np.zeros(len(tri), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    record["n"], record["v"] = normal, tri
    header = f"EasyFOAM {name}".encode().ljust(80, b" ")[:80]
    path.write_bytes(header + struct.pack("<I", len(tri)) + record.tobytes())
    return path


# --- in a project ----------------------------------------------------------------------------------------------------


def use_terrain(project, case_dir: Path, ground: Ground, cell_size: float, water_level: float | None,
                top: float | None = None, discharge: float = 1.0) -> list[str]:  # fmt: skip
    """Make the project model flow over the ground: the solid, the base mesh above it, the water and boundaries.

    The base mesh reaches just inside the ground's edges, so the ground solid closes it off at the sides and
    below; its top is ``top`` (default: a fifth of the relief above the highest ground). The river enters
    through the side facing -x (inlet) and leaves through +x (outlet). Returns what was set, in plain words.
    """
    from easyfoam.model import BaseFace, Boundary, Shape

    if cell_size <= 0:
        raise ValueError("the cell size must be above zero")
    low, high = float(np.nanmin(ground.z)), float(np.nanmax(ground.z))
    relief = max(high - low, 1.0)
    top = high + max(0.2 * relief, 2 * cell_size) if top is None else float(top)
    if top <= high:
        raise ValueError(f"the top of the model must be above the highest ground ({high:.4g} m)")
    margin = 0.5 * min(cell_size, ground.spacing)
    base = low - max(relief, 4 * cell_size)  # well below the base mesh
    write_stl(Path(case_dir) / "constant" / "triSurface" / f"{NAME}.stl", solid(ground, base))
    project.shapes = [s for s in project.shapes if s.name != NAME]
    project.shapes.append(Shape(NAME, kind="stl", file=f"{NAME}.stl", level_min=0, level_max=1))
    project.channel = None
    mesh = project.mesh
    lo = [float(ground.x[0]) + margin, float(ground.y[0]) + margin, low - cell_size]
    hi = [float(ground.x[-1]) - margin, float(ground.y[-1]) - margin, top]
    mesh.base.min, mesh.base.max = lo, hi
    mesh.base.cells = [max(1, math.ceil((b - a) / cell_size - 1e-9)) for a, b in zip(lo, hi)]
    mesh.base.faces["xMin"] = BaseFace("inlet", "patch")
    mesh.base.faces["xMax"] = BaseFace("outlet", "patch")
    mesh.base.faces["yMin"] = mesh.base.faces["yMax"] = BaseFace("sides", "patch")
    mesh.base.faces["zMin"] = BaseFace("bottom", "wall")
    mesh.base.faces["zMax"] = BaseFace("atmosphere", "patch")
    mesh.snappy, mesh.snap, mesh.fluid_inside = True, True, ""
    middle = [(a + b) / 2 for a, b in zip(lo, hi)]
    mesh.location_in_mesh = [middle[0] + 0.137 * cell_size, middle[1] + 0.171 * cell_size, top - 0.43 * cell_size]
    physics = project.physics
    done = [f"the ground spans {ground.x[-1] - ground.x[0]:.4g} x {ground.y[-1] - ground.y[0]:.4g} m, from "
            f"{low:.4g} to {high:.4g} m"]  # fmt: skip
    if physics.solver != "interFoam":
        physics.solver = "interFoam"
        physics.material, physics.nu, physics.rho = "water", 1.0e-06, 998.0
        done.append("the flow type is now free surface (water and air)")
    physics.water_regions = []
    if water_level is not None and water_level > low:
        physics.water_regions = [[lo[0] - 1, lo[1] - 1, lo[2] - 1, hi[0] + 1, hi[1] + 1, float(water_level)]]
        done.append(f"water fills the low ground up to {water_level:.4g} m at the start")
    boundaries = project.boundaries
    boundaries["inlet"] = Boundary(kind="flowRateInlet", flow_rate=float(discharge))
    level = float(water_level) if water_level is not None and water_level > low else low + 0.5 * relief
    boundaries["outlet"] = Boundary(kind="waterLevelOutlet", level=level)
    boundaries["atmosphere"] = Boundary(kind="atmosphere")
    boundaries.setdefault(NAME, Boundary(kind="wall"))
    boundaries["sides"] = Boundary(kind="slip")
    if "outlet" not in project.flow_monitors:
        project.flow_monitors.append("outlet")
    from easyfoam.channel import free_surface_run

    done += free_surface_run(project, cell_size, float(ground.x[-1] - ground.x[0]), 1.0)
    return done
