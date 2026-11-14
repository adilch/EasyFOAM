"""Shapes that are drawn rather than imported: a cone, a wedge and a sketched outline.

The mesher knows boxes, spheres and cylinders by itself. These shapes are
turned into triangles here and reach it as a surface file written with the
case, exactly like an imported STL, so everything that works for an STL
(internal flow, floating, regions of refinement) works for them too.
"""

from __future__ import annotations

import math

import numpy as np

from easyfoam.model import Shape

DRAWN = ("cone", "wedge", "profile", "structure")
#: which way the top of a wedge rises
RISES = ("+x", "-x", "+y", "-y")
#: plane of a sketch -> (axis of the first coordinate, of the second, of the extrusion)
PLANES = {"xz": (0, 2, 1), "xy": (0, 1, 2), "yz": (1, 2, 0)}
SEGMENTS = 48  # around a cone


def is_drawn(shape: Shape) -> bool:
    return shape.kind in DRAWN


# --- outlines ---------------------------------------------------------------------


def signed_area(points) -> float:
    """Area of an outline; positive when it runs counter-clockwise."""
    p = np.asarray(points, float)
    x, y = p[:, 0], p[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def clean_outline(points) -> list[tuple[float, float]]:
    """The corners of an outline without repeats and without points in the middle of a straight side."""
    corners = [(float(u), float(v)) for u, v in points]
    corners = [p for i, p in enumerate(corners) if p != corners[i - 1]] if len(corners) > 1 else corners
    span = max((max(c) - min(c) for c in zip(*corners)), default=0.0) or 1.0
    kept = []
    for i, (u, v) in enumerate(corners):
        (pu, pv), (nu, nv) = corners[i - 1], corners[(i + 1) % len(corners)]
        turn = (u - pu) * (nv - v) - (v - pv) * (nu - u)
        if len(corners) < 3 or abs(turn) > 1e-12 * span * span:
            kept.append((u, v))
    return kept


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _sides_cross(p, q, r, s) -> bool:
    """Do the segments p-q and r-s cross each other (touching at a shared end does not count)?"""
    d1, d2 = _cross(r, s, p), _cross(r, s, q)
    d3, d4 = _cross(p, q, r), _cross(p, q, s)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def outline_problem(points) -> str | None:
    corners = clean_outline(points)
    if len(corners) < 3:
        return "its outline needs at least three corners that are not in one line"
    count = len(corners)
    for i in range(count):
        for j in range(i + 1, count):
            if (j + 1) % count == i or (i + 1) % count == j:
                continue  # neighbouring sides share a corner
            if _sides_cross(corners[i], corners[(i + 1) % count], corners[j], corners[(j + 1) % count]):
                return "its outline crosses itself"
    if abs(signed_area(corners)) < 1e-14:
        return "its outline encloses no area"
    return None


def ear_clip(points) -> list[tuple[int, int, int]]:
    """Cut a simple outline (convex or not) into triangles; returns corner numbers, counter-clockwise."""
    corners = [(float(u), float(v)) for u, v in points]
    order = list(range(len(corners)))
    if signed_area(corners) < 0:
        order.reverse()
    triangles = []
    guard = 0
    while len(order) > 3 and guard < 10 * len(corners) ** 2:
        guard += 1
        for k in range(len(order)):
            i, j, m = order[k - 1], order[k], order[(k + 1) % len(order)]
            a, b, c = corners[i], corners[j], corners[m]
            if _cross(a, b, c) <= 0:
                continue  # a corner that points inwards cannot be cut off
            if any(
                _cross(a, b, corners[n]) >= 0 and _cross(b, c, corners[n]) >= 0 and _cross(c, a, corners[n]) >= 0
                for n in order
                if n not in (i, j, m)
            ):
                continue  # another corner lies inside this ear
            triangles.append((i, j, m))
            del order[k]
            break
        else:
            break  # nothing could be cut: the outline is not simple
    if len(order) == 3:
        triangles.append((order[0], order[1], order[2]))
    return triangles


# --- surfaces ---------------------------------------------------------------------


def _outwards(triangles: np.ndarray) -> np.ndarray:
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    volume = float(np.einsum("ij,ij->i", a - a[0], np.cross(b - a[0], c - a[0])).sum())
    return triangles[:, ::-1].copy() if volume < 0 else triangles


def _extrude(outline, plane: str, extent) -> np.ndarray:
    corners = clean_outline(outline)
    if signed_area(corners) < 0:
        corners.reverse()  # sides and ends must turn the same way, whichever way the outline was drawn
    first, second, along = PLANES.get(plane, PLANES["xz"])
    low, high = sorted(float(e) for e in extent)

    def point(corner, w):
        p = [0.0, 0.0, 0.0]
        p[first], p[second], p[along] = corner[0], corner[1], w
        return p

    triangles = []
    count = len(corners)
    for i in range(count):
        a, b = corners[i], corners[(i + 1) % count]
        triangles.append([point(a, low), point(b, low), point(b, high)])
        triangles.append([point(a, low), point(b, high), point(a, high)])
    for i, j, m in ear_clip(corners):
        triangles.append([point(corners[i], low), point(corners[m], low), point(corners[j], low)])
        triangles.append([point(corners[i], high), point(corners[j], high), point(corners[m], high)])
    return _outwards(np.asarray(triangles, float))


def _cone(shape: Shape) -> np.ndarray:
    p1, p2 = np.asarray(shape.point1, float), np.asarray(shape.point2, float)
    axis = (p2 - p1) / np.linalg.norm(p2 - p1)
    helper = np.eye(3)[int(np.argmin(np.abs(axis)))]
    e1 = np.cross(axis, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    angles = [2.0 * math.pi * i / SEGMENTS for i in range(SEGMENTS)]
    ring1 = [p1 + shape.radius * (math.cos(t) * e1 + math.sin(t) * e2) for t in angles]
    ring2 = [p2 + shape.radius2 * (math.cos(t) * e1 + math.sin(t) * e2) for t in angles]
    triangles = []
    for i in range(SEGMENTS):
        j = (i + 1) % SEGMENTS
        if shape.radius > 0:
            triangles.append([ring1[i], ring1[j], ring2[j]])
            triangles.append([p1, ring1[j], ring1[i]])
        if shape.radius2 > 0:
            triangles.append([ring1[i], ring2[j], ring2[i]])
            triangles.append([p2, ring2[i], ring2[j]])
    return _outwards(np.asarray(triangles, float))


def _wedge(shape: Shape) -> np.ndarray:
    (x0, y0, z0), (x1, y1, z1) = shape.min, shape.max
    if shape.rise in ("+y", "-y"):
        top = y1 if shape.rise == "+y" else y0
        return _extrude([(y0, z0), (y1, z0), (top, z1)], "yz", [x0, x1])
    top = x0 if shape.rise == "-x" else x1
    return _extrude([(x0, z0), (x1, z0), (top, z1)], "xz", [y0, y1])


def problem(shape: Shape) -> str | None:
    """What is wrong with a shape, in words, or ``None`` if it can be used."""
    if shape.kind == "profile":
        wrong = outline_problem(shape.points)
        if wrong:
            return wrong
        if len(shape.extent) != 2 or shape.extent[0] == shape.extent[1]:
            return "it has no length: the two ends of the extrusion are in the same place"
    elif shape.kind == "cone":
        if list(shape.point1) == list(shape.point2):
            return "it has no length: its two ends are in the same place"
        if shape.radius < 0 or shape.radius2 < 0 or (shape.radius == 0 and shape.radius2 == 0):
            return "it needs a radius above zero at one end at least"
    elif shape.kind in ("wedge", "box"):
        if any(hi <= lo for lo, hi in zip(shape.min, shape.max)):
            return "it has no size: each max corner must be above its min"
    elif shape.kind in ("sphere", "cylinder"):
        if shape.radius <= 0:
            return "it needs a radius above zero"
        if shape.kind == "cylinder" and list(shape.point1) == list(shape.point2):
            return "it has no length: its two ends are in the same place"
    elif shape.kind == "structure":
        if shape.structure is None:
            return "it has no design values"
        from easyfoam import structures  # it builds on the surfaces made here

        wrong = structures.problems(shape.structure)
        if wrong:
            return wrong[0]
    return None


def triangulate(shape: Shape) -> np.ndarray:
    """The surface of a drawn shape as triangles (n, 3, 3), closed and facing outwards."""
    wrong = problem(shape)
    if wrong:
        raise ValueError(f"'{shape.name}' cannot be used: {wrong}")
    if shape.kind == "cone":
        return _cone(shape)
    if shape.kind == "wedge":
        return _wedge(shape)
    if shape.kind == "profile":
        return _extrude(shape.points, shape.plane, shape.extent)
    if shape.kind == "structure":
        from easyfoam import structures

        return structures.triangles(shape.structure)
    raise ValueError(f"'{shape.name}' is not a drawn shape")


def ascii_stl(name: str, triangles: np.ndarray) -> str:
    lines = [f"solid {name}"]
    for triangle in triangles:
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        length = float(np.linalg.norm(normal))
        nx, ny, nz = normal / length if length else (0.0, 0.0, 0.0)
        lines += [f"facet normal {nx:.6g} {ny:.6g} {nz:.6g}", " outer loop"]
        lines += [f"  vertex {x:.9g} {y:.9g} {z:.9g}" for x, y, z in triangle]
        lines += [" endloop", "endfacet"]
    lines.append(f"endsolid {name}")
    return "\n".join(lines) + "\n"
