# Roadmap

Ordered by what the public SimFlow tutorials and the open-source survey show
people need most. Each milestone ends with at least one worked example that
runs end to end in the test suite.

## v0.1 - the loop works (done)

Incompressible external and internal flow from STL or primitives:
base mesh, snappyHexMesh, boundary presets, parallel run, live residuals,
built-in 3D view, ParaView hand-off, command line. Back-end: WSL / Linux.

## v0.2 - everyday aerodynamics and pipe flow (this version)

Done:

- Drag and lift coefficient monitor with live plot; y+, wall shear stress,
  vorticity and Q on demand.
- Potential-flow initialisation; convergence target (residual auto-stop).
- Multi-solid STL: one patch per solid, each a wall or an opening.
- Refinement by distance from a surface.
- Internal flow: fluid inside a chosen shape, interior point found
  automatically, snug base mesh; pipe example checked against Hagen-Poiseuille.
- Spalart-Allmaras and realizable k-epsilon.

Still open from this milestone:

- Probes and field statistics monitors.
- Renaming patches after meshing; gap refinement.
- Dragging the "point inside the fluid" in the 3D view.
- checkMesh result shown in 3D (bad cells highlighted).
- Graceful stop that writes the current state; continuing a run.
- Estimating the reference (frontal) area from the geometry.

## v0.3 - heat and free surface

- Buoyant heat transfer (buoyantSimpleFoam / buoyantPimpleFoam), temperature
  and heat-flux boundaries, thermophysical material database.
- Free-surface flow (interFoam): phase initialisation by region, gravity,
  hydrostatic pressure, open-channel and wave boundaries.
- Passive scalar transport.

## v0.4 - more ways in and out

- STEP / IGES import (through OCP or gmsh), units on import, STL check and repair.
- Mesh import: Fluent, Gmsh, existing OpenFOAM cases (read boundary and fields).
- Native Windows back-ends: ESI MinGW build and blueCFD-Core.
- Foundation-line (openfoam.org) dictionary dialect.
- Windows installer.

## v0.5 - rotating machinery and regions

- Cell zones, MRF, porous zones.
- Cyclic / AMI interfaces, sliding mesh.
- Multi-region meshing and conjugate heat transfer (chtMultiRegionFoam).

## Later

- Compressible flow (rhoSimpleFoam, rhoPimpleFoam, rhoCentralFoam).
- Particles (DPM), sprays, combustion.
- 6DoF and overset motion.
- LES / DES set-up helpers.
- Parameters and expressions; parametric sweeps from the command line.
- Remote and cluster runs (SSH, Slurm, PBS).
- Report generation.
