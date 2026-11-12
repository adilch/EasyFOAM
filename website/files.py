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


DOWNLOADS = {"tutorials/files/spillway.stl": spillway_stl}
