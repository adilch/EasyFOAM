"""Meshing dictionaries: blockMeshDict, snappyHexMeshDict, surfaceFeatureExtractDict."""

from __future__ import annotations

from pathlib import Path, PurePath

from easyfoam import geometry
from easyfoam.foam.boundaryfile import Patch
from easyfoam.foam.dictfmt import Named, Q
from easyfoam.model import FACES, BaseMesh, Project, Shape
from easyfoam.runtime import Step

#: vertex indices of each face of the base block, ordered so the normal points outwards
FACE_VERTICES = {
    "xMin": [0, 4, 7, 3],
    "xMax": [1, 2, 6, 5],
    "yMin": [0, 1, 5, 4],
    "yMax": [3, 7, 6, 2],
    "zMin": [0, 3, 2, 1],
    "zMax": [4, 5, 6, 7],
}


def wall_shapes(project: Project) -> list[Shape]:
    return [s for s in project.shapes if s.role == "wall"]


def stl_shapes(project: Project) -> list[Shape]:
    """Solid shapes that reach the mesher as a surface file: imported ones and drawn ones."""
    return [s for s in wall_shapes(project) if geometry.is_surface(s)]


def uses_snappy(project: Project) -> bool:
    return project.mesh.snappy and bool(project.shapes)


def block_mesh_dict(project: Project) -> dict:
    if project.channel is not None:  # a channel built in the program: blocks fitted to it
        from easyfoam import channel

        return channel.block_mesh_dict(project.channel)
    base = project.mesh.base
    (x0, y0, z0), (x1, y1, z1) = base.min, base.max
    vertices = [
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ]  # fmt: skip
    patches: dict[str, dict] = {}
    for face in FACES:
        info = base.faces[face]
        patch = patches.setdefault(info.name, {"type": info.type, "faces": []})
        patch["faces"].append(FACE_VERTICES[face])
    return {
        "scale": 1,
        "vertices": vertices,
        # blockMesh wants a flat token list: blocks ( hex (...) (...) simpleGrading (...) );
        "blocks": ["hex", list(range(8)), list(base.cells), "simpleGrading", [1, 1, 1]],
        "edges": [],
        "boundary": [Named(name, body) for name, body in patches.items()],
        "mergePatchPairs": [],
    }


def auto_location_in_mesh(base: BaseMesh) -> list[float]:
    """A point inside the first corner cell, away from every cell face."""
    fractions = (0.37, 0.41, 0.43)
    return [lo + (hi - lo) * frac / n for lo, hi, n, frac in zip(base.min, base.max, base.cells, fractions)]


def _clip_segment(p1, p2, lo, hi) -> list[float]:
    """Middle of the part of the segment p1-p2 that lies inside the box lo-hi."""
    t_min, t_max = 0.0, 1.0
    for a, b, low, high in zip(p1, p2, lo, hi):
        d = b - a
        if d == 0:
            if not low < a < high:
                raise ValueError("the shape lies outside the base mesh")
            continue
        t0, t1 = sorted(((low - a) / d, (high - a) / d))
        t_min, t_max = max(t_min, t0), min(t_max, t1)
    if t_min >= t_max:
        raise ValueError("the shape lies outside the base mesh")
    t = (t_min + t_max) / 2
    return [a + (b - a) * t for a, b in zip(p1, p2)]


def location_in_mesh(project: Project, case_dir: Path | None = None) -> list[float]:
    """The point that tells snappyHexMesh which side of the surfaces is fluid."""
    mesh = project.mesh
    if mesh.location_in_mesh:
        return list(mesh.location_in_mesh)
    if project.channel is not None:
        from easyfoam import channel

        return channel.inside_point(project.channel)
    if not mesh.fluid_inside:
        return auto_location_in_mesh(mesh.base)
    shape = next((s for s in project.shapes if s.name == mesh.fluid_inside), None)
    if shape is None:
        raise ValueError(f"the fluid is set to be inside '{mesh.fluid_inside}', but there is no such shape")
    base = mesh.base
    if geometry.is_surface(shape):
        if case_dir is None and shape.kind == "stl":
            raise ValueError("the case folder is needed to find a point inside an STL surface")
        return geometry.interior_point(geometry.surface_triangles(shape, case_dir), base.min, base.max)
    if shape.kind == "cylinder":
        point = _clip_segment(shape.point1, shape.point2, base.min, base.max)
    elif shape.kind == "sphere":
        point = list(shape.centre)
    else:
        point = [(a + b) / 2 for a, b in zip(shape.min, shape.max)]
    # centres and axes often coincide with cell faces of the base mesh: step off them
    cell = min((hi - lo) / n for lo, hi, n in zip(base.min, base.max, base.cells))
    point = [c + 0.17 * cell * f for c, f in zip(point, (1.0, 0.83, 0.71))]
    if not all(lo < c < hi for c, lo, hi in zip(point, base.min, base.max)):
        raise ValueError(f"'{shape.name}' does not lie inside the base mesh")
    return point


def _geometry_entry(shape: Shape) -> dict:
    if geometry.is_surface(shape):
        return {"type": "triSurfaceMesh", "file": Q(geometry.surface_file(shape))}
    if shape.kind == "sphere":
        return {"type": "sphere", "origin": list(shape.centre), "radius": shape.radius}
    if shape.kind == "cylinder":
        return {
            "type": "cylinder",
            "point1": list(shape.point1),
            "point2": list(shape.point2),
            "radius": shape.radius,
        }
    if shape.kind == "box":
        return {"type": "box", "min": list(shape.min), "max": list(shape.max)}
    raise ValueError(f"unknown shape kind '{shape.kind}' for '{shape.name}'")


def _surface_entry(shape: Shape) -> dict:
    level = [shape.level_min, shape.level_max]
    entry: dict = {"level": level, "patchInfo": {"type": "wall"}}
    if len(shape.regions) > 1:
        entry["regions"] = {
            name: {"level": list(level), "patchInfo": {"type": kind}} for name, kind in shape.regions.items()
        }
    return entry


def _refinement_regions(project: Project) -> dict:
    regions = {}
    for shape in project.shapes:
        if shape.role == "refinement":
            regions[shape.name] = {"mode": "inside", "levels": [[1e15, shape.region_level]]}
        elif shape.near_level > 0 and shape.near_distance > 0:
            regions[shape.name] = {"mode": "distance", "levels": [[shape.near_distance, shape.near_level]]}
    return regions


def snappy_dict(project: Project, case_dir: Path | None = None, location: list[float] | None = None) -> dict:
    mesh = project.mesh
    walls = wall_shapes(project)
    stls = stl_shapes(project)
    explicit = bool(walls) and len(stls) == len(walls)
    layered = {f'"{s.name}.*"': {"nSurfaceLayers": s.layers} for s in walls if s.layers > 0}
    add_layers = mesh.add_layers and bool(layered)
    location = location or location_in_mesh(project, case_dir)

    return {
        "castellatedMesh": True,
        "snap": mesh.snap,
        "addLayers": add_layers,
        "geometry": {s.name: _geometry_entry(s) for s in project.shapes},
        "castellatedMeshControls": {
            "maxLocalCells": 2000000,
            "maxGlobalCells": 20000000,
            "minRefinementCells": 10,
            "maxLoadUnbalance": 0.1,
            "nCellsBetweenLevels": mesh.cells_between_levels,
            "features": (
                [{"file": Q(PurePath(geometry.surface_file(s)).stem + ".eMesh"), "level": s.level_min} for s in stls]
                if explicit
                else []
            ),
            "refinementSurfaces": {s.name: _surface_entry(s) for s in walls},
            "resolveFeatureAngle": mesh.feature_angle,
            "refinementRegions": _refinement_regions(project),
            "locationInMesh": list(location),
            "allowFreeStandingZoneFaces": True,
        },
        "snapControls": {
            "nSmoothPatch": 3,
            "tolerance": 2.0,
            "nSolveIter": 50,
            "nRelaxIter": 5,
            "nFeatureSnapIter": 10,
            "implicitFeatureSnap": not explicit,
            "explicitFeatureSnap": explicit,
            "multiRegionFeatureSnap": False,
        },
        "addLayersControls": {
            "relativeSizes": True,
            "layers": layered if add_layers else {},
            "expansionRatio": mesh.layer_expansion,
            "finalLayerThickness": mesh.final_layer_thickness,
            "minThickness": 0.1,
            "nGrow": 0,
            "featureAngle": 130,
            "slipFeatureAngle": 30,
            "nRelaxIter": 5,
            "nSmoothSurfaceNormals": 1,
            "nSmoothNormals": 3,
            "nSmoothThickness": 10,
            "maxFaceThicknessRatio": 0.5,
            "maxThicknessToMedialRatio": 0.3,
            "minMedialAxisAngle": 90,
            "nBufferCellsNoExtrude": 0,
            "nLayerIter": 50,
            "nRelaxedIter": 20,
        },
        "meshQualityControls": {
            "maxNonOrtho": 65,
            "maxBoundarySkewness": 20,
            "maxInternalSkewness": 4,
            "maxConcave": 80,
            "minVol": 1e-13,
            "minTetQuality": 1e-15,
            "minArea": -1,
            "minTwist": 0.02,
            "minDeterminant": 0.001,
            "minFaceWeight": 0.05,
            "minVolRatio": 0.01,
            "minTriangleTwist": -1,
            "nSmoothScale": 4,
            "errorReduction": 0.75,
            "relaxed": {"maxNonOrtho": 75},
        },
        "mergeTolerance": 1e-06,
    }


def feature_extract_dict(project: Project) -> dict | None:
    stls = stl_shapes(project)
    if not stls:
        return None
    return {
        geometry.surface_file(s): {
            "extractionMethod": "extractFromSurface",
            "includedAngle": 150,
            "subsetFeatures": {"nonManifoldEdges": False, "openEdges": True},
            "writeObj": False,
        }
        for s in stls
    }


def mesh_steps(project: Project) -> list[Step]:
    steps = [Step("blockMesh", "blockMesh")]
    if uses_snappy(project):
        if stl_shapes(project):
            steps.append(Step("surfaceFeatureExtract", "surfaceFeatureExtract"))
        steps.append(Step("snappyHexMesh", "snappyHexMesh -overwrite"))
    steps.append(Step("checkMesh", "checkMesh"))
    return steps


def predicted_patches(project: Project) -> list[Patch]:
    """The patches the mesh will have, for setting boundaries before meshing."""
    seen: dict[str, str] = {}
    if project.channel is not None:
        from easyfoam import channel

        seen.update((p.name, p.type) for p in channel.patches(project.channel))
    else:
        for face in FACES:
            info = project.mesh.base.faces[face]
            seen.setdefault(info.name, info.type)
    if uses_snappy(project):
        for shape in wall_shapes(project):
            if len(shape.regions) > 1:
                for region, kind in shape.regions.items():
                    seen.setdefault(f"{shape.name}_{region}", kind)
            else:
                seen.setdefault(shape.name, "wall")
    return [Patch(name, kind, 0, 0) for name, kind in seen.items()]
