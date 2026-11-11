# EasyFOAM design

## Intent

A free desktop application that takes someone from a geometry file to a
converged OpenFOAM result without hand-editing dictionaries, while leaving a
normal OpenFOAM case on disk that an expert can open, read and continue by hand.

## Goals

1. Drive the user's own, unmodified OpenFOAM (ESI line first: v2212 to current).
2. One window for the whole loop: geometry, mesh, set-up, run, results.
3. The case folder is ordinary OpenFOAM. The only extras are `easyfoam.json`
   (the project) and `.easyfoam/` (the exact scripts that were run).
4. Everything the window does is also available from the command line.
5. No artificial limits on cells or cores.

## Non-goals (for now)

- Bundling or patching OpenFOAM itself.
- CAD modelling. Geometry is imported; only simple primitives are built in.
- Replacing ParaView. The built-in view covers checking and quick looks.

## Anti-goals

- Copying another product's code, assets, texts or screen layouts
  (see the clean-room rules in `feature-map.md`).
- Hiding what is run. Every command and its log must be inspectable.
- A case that only EasyFOAM can open.

## Decisions (made by the builder, change if you disagree)

| Decision | Choice | Why |
|---|---|---|
| Language and GUI | Python 3.11+, PySide6 (Qt 6) | Fast to develop, native look, LGPL. |
| 3D view | VTK through PyVista / pyvistaqt | VTK reads OpenFOAM cases directly. |
| Plots | pyqtgraph | Fast live plots. |
| First OpenFOAM back-end | WSL 2 on Windows, native on Linux | Works with stock packages, full feature set, live output. |
| OpenFOAM line | ESI (openfoam.com) | Most widely used in industry; Foundation line later. |
| Licence | GPL-3.0-or-later | Same family as OpenFOAM; compatible with every dependency. |
| Project format | JSON, case regenerated from it | Simple, diff-able, forward compatible (unknown keys ignored). |
| Own dictionary writer | yes, about 100 lines | No dependency for the core; foamlib (GPL-3.0-only) can be added for reading. |

## Architecture

```
easyfoam/
  model.py            Project dataclasses <-> easyfoam.json
  solvers.py          supported solvers, turbulence models, materials
  geometry.py         STL import, bounding boxes, base-mesh sizing
  foam/
    dictfmt.py        Python data -> OpenFOAM dictionary text
    boundaryfile.py   read constant/polyMesh/boundary
    logparser.py      solver log -> residuals, Courant number, errors
  casegen/
    mesh.py           blockMeshDict, snappyHexMeshDict, surfaceFeatureExtractDict
    setup.py          0/ fields, fvSchemes, fvSolution, controlDict, properties
    __init__.py       file sets, writing, cleaning
  runtime.py          where OpenFOAM is and how to launch it (WSL / native)
  pipeline.py         prepare_mesh / prepare_run, Job (run, stream, stop)
  examples.py         starting projects
  cli.py              command line
  gui/                the window (depends on everything above, nothing depends on it)
```

Rules that keep it testable:

- `casegen` functions are pure: project in, Python dictionaries out. Unit tests
  assert on those dictionaries; one end-to-end test runs a real mesh and solve.
- Launching is always "write a bash script into the case, run it in the
  runtime". Scripts print `@@EASYFOAM step <name>` marker lines so progress and
  the failing step are known without parsing tool output.
- Boundary conditions are stored per patch **name**. After meshing the real
  patch list is read from the mesh, and patches without a user choice get a
  default from their type and name.
- The GUI never builds dictionaries itself; it edits the project and calls
  `pipeline`.

## Adding a solver

1. Add it to `SOLVERS` in `solvers.py`.
2. Extend `casegen/setup.py`: fields, boundary entries per boundary kind,
   schemes, solution controls and property files.
3. Add unit tests for the new dictionaries and an end-to-end example.
