# Roadmap

Ordered by what the public SimFlow tutorials and the open-source survey show
people need most. Each milestone ends with at least one worked example that
runs end to end in the test suite.

## v0.1 - the loop works (done)

Incompressible external and internal flow from STL or primitives:
base mesh, snappyHexMesh, boundary presets, parallel run, live residuals,
built-in 3D view, ParaView hand-off, command line. Back-end: WSL / Linux.

## v0.2 - everyday aerodynamics and pipe flow (done)

Done:

- Drag and lift coefficient monitor with live plot; y+, wall shear stress,
  vorticity and Q on demand.
- Potential-flow initialisation; convergence target (residual auto-stop).
- Multi-solid STL: one patch per solid, each a wall or an opening.
- Refinement by distance from a surface.
- Internal flow: fluid inside a chosen shape, interior point found
  automatically, snug base mesh; pipe example checked against Hagen-Poiseuille.
- Spalart-Allmaras and realizable k-epsilon.

## v0.3 - made to be easy (done)

Done:

- Interface overhaul: start page with examples and recent projects, icon
  toolbar and menus, step list with status and summaries, pre-run checklist,
  Back / Next, tooltips, view buttons, highlighting of the selected shape or
  boundary, progress bar. Icons are SVG (Lucide plus EasyFOAM's own).
- Graceful stop that saves the current state; continuing a run; the final
  state is always saved even off the save interval.
- Probes with a live plot; frontal-area estimate for the force monitor.
- Renaming shapes (and with them their boundaries).
- Dragging the "point inside the fluid" in the 3D view.

Still open:

- Field statistics monitors (min / max / average).
- Gap refinement.
- checkMesh result shown in 3D (bad cells highlighted).
- Renaming single regions of an STL.

## v0.4 - free surface for hydraulic structures (this version)

Done:

- Water and air with a free surface (interFoam): gravity, surface tension,
  both fluids' properties, adaptive time step limited by the interface.
- Water placed at the start as boxes or by filling to a level.
- Boundaries for channels, weirs and spillways: inlet by flow rate that follows
  the water level, open atmosphere, free outflow; flow-rate inlet and open
  boundary also for single-fluid flow.
- Water-surface view coloured by speed; share of water in the domain while running.
- Examples: flow over a weir (compared with the weir formula) and a dam break.

Still open for hydraulics:

- Outlet with a fixed tailwater level; wave generation and absorption.
- Monitors for discharge through a boundary and for the water level at a point.
- Sharper interface capturing (interIsoFoam); sediment and air entrainment are out of scope for now.
- STEP import for real spillway geometry (STL works today).

## v0.4.x - heat

- Buoyant heat transfer (buoyantSimpleFoam / buoyantPimpleFoam), temperature
  and heat-flux boundaries, thermophysical material database.
- Passive scalar transport.

## v0.5 - more ways in and out

- STEP / IGES import (through OCP or gmsh), units on import, STL check and repair.
- Mesh import: Fluent, Gmsh, existing OpenFOAM cases (read boundary and fields).
- Native Windows back-ends: ESI MinGW build and blueCFD-Core.
- Foundation-line (openfoam.org) dictionary dialect.
- Windows installer.

## v0.6 - rotating machinery and regions

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
