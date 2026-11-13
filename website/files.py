"""Files that tutorials offer for download, made here so that they are exact and reproducible."""

from __future__ import annotations

import math

# The spillway of the "your own geometry" tutorial: an ogee crest 0.5 m above the bed.
SPILLWAY_X = 1.5  # where its upstream face stands in the channel [m]
CREST = 0.5  # height of the crest above the bed [m]
DESIGN_HEAD = 0.12  # the head the crest is shaped for [m]
NOSE = 0.06  # radius of the rounded upstream corner [m]
SLOPE = 1.25  # of the straight downstream face (vertical over horizontal)
BELOW = -0.2  # the body reaches below the bed and beyond both side walls, so the mesh is cut cleanly
Y_RANGE = (-0.25, 0.75)


def spillway_profile() -> list[tuple[float, float]]:
    """The outline of the spillway in the x-z plane, counter-clockwise seen from -y."""
    points = [(0.0, BELOW), (0.0, CREST - NOSE)]
    for step in range(1, 9):  # the rounded upstream corner, up to the crest
        angle = math.radians(90.0 * step / 8)
        points.append((NOSE * (1 - math.cos(angle)), CREST - NOSE + NOSE * math.sin(angle)))
    # downstream of the crest the classic ogee shape: drop = 0.5 X^1.85 / Hd^0.85
    tangent = DESIGN_HEAD * (SLOPE / 0.925) ** (1 / 0.85)  # where the curve is as steep as the straight face
    for step in range(1, 13):
        x = tangent * step / 12
        points.append((NOSE + x, CREST - 0.5 * x**1.85 / DESIGN_HEAD**0.85))
    x, z = points[-1]
    points.append((x + (z - BELOW) / SLOPE, BELOW))
    return [(SPILLWAY_X + px, pz) for px, pz in reversed(points)]  # reversed: outward-facing triangles below


def spillway_stl() -> str:
    """The spillway as an ASCII STL file (a closed surface, in metres)."""
    outline = spillway_profile()
    y0, y1 = Y_RANGE
    triangles = []
    count = len(outline)
    for i in range(count):  # the skin
        (xa, za), (xb, zb) = outline[i], outline[(i + 1) % count]
        triangles.append(((xa, y0, za), (xb, y0, zb), (xb, y1, zb)))
        triangles.append(((xa, y0, za), (xb, y1, zb), (xa, y1, za)))
    for i in range(1, count - 1):  # the two flat ends (the outline bulges outwards everywhere)
        (xa, za), (xb, zb), (xc, zc) = outline[0], outline[i], outline[i + 1]
        triangles.append(((xa, y0, za), (xc, y0, zc), (xb, y0, zb)))
        triangles.append(((xa, y1, za), (xb, y1, zb), (xc, y1, zc)))
    lines = ["solid spillway"]
    for triangle in triangles:
        lines += ["facet normal 0 0 0", " outer loop"]
        lines += [f"  vertex {x:.6f} {y:.6f} {z:.6f}" for x, y, z in triangle]
        lines += [" endloop", "endfacet"]
    lines.append("endsolid spillway")
    return "\n".join(lines) + "\n"


# The valley of the "river reach from a survey" tutorial: survey coordinates the size of UTM ones.
VALLEY_ORIGIN = (512_000.0, 4_181_000.0)  # where the valley's axis starts (east, north) [m]
VALLEY_ANGLE = 30.0  # the valley runs this many degrees north of east


def valley_asc(size: float = 1.0) -> str:
    """A valley falling 0.4 % along its axis, with a 1.2 m deep meandering channel, as an ESRI ASCII grid."""
    import numpy as np

    along = np.arange(int(160 / size) + 1) * size
    across = np.arange(int(100 / size) + 1) * size - 50
    a, c = np.meshgrid(along, across)
    z = 100 - 0.004 * a + 0.0008 * c**2 - 1.2 * np.exp(-(((c - 8 * np.sin(2 * math.pi * a / 80)) / 3.0) ** 2))
    angle = math.radians(VALLEY_ANGLE)
    east = VALLEY_ORIGIN[0] + a * math.cos(angle) - c * math.sin(angle)
    north = VALLEY_ORIGIN[1] + a * math.sin(angle) + c * math.cos(angle)
    e = np.arange(east.min(), east.max() + size, size)
    n = np.arange(north.min(), north.max() + size, size)
    grid = np.full((len(n), len(e)), -9999.0)
    grid[np.round((north - n[0]) / size).astype(int), np.round((east - e[0]) / size).astype(int)] = z
    rows = "\n".join(" ".join(f"{v:.3f}" for v in row) for row in grid[::-1])
    header = [f"ncols {len(e)}", f"nrows {len(n)}", f"xllcenter {e[0]:.3f}", f"yllcenter {n[0]:.3f}",
              f"cellsize {size}", "NODATA_value -9999"]  # fmt: skip
    return "\n".join(header) + "\n" + rows + "\n"


DOWNLOADS = {"tutorials/files/spillway.stl": spillway_stl, "tutorials/files/valley.asc": valley_asc}
