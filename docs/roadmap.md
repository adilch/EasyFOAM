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

## v0.4 - free surface for hydraulic structures (done)

Done:

- Water and air with a free surface (interFoam): gravity, surface tension,
  both fluids' properties, adaptive time step limited by the interface.
- Water placed at the start as boxes or by filling to a level.
- Boundaries for channels, weirs and spillways: inlet by flow rate that follows
  the water level, open atmosphere, free outflow; flow-rate inlet and open
  boundary also for single-fluid flow.
- Water-surface view coloured by speed; share of water in the domain while running.
- Examples: flow over a weir (compared with the weir formula) and a dam break.

## v0.5 - hydraulics completed, CAD import (done)

Done:

- Outlet at a fixed tailwater level (hydrostatic below the level).
- Regular waves: wave maker with Stokes 1st or 2nd order theory and a
  wave-absorbing outlet; wave-flume example.
- Monitors: discharge through chosen boundaries (water only in free-surface
  runs) and water depth at the probe points, both with live plots.
- Sharper interface solver (interIsoFoam) as a second free-surface flow type.
- STEP / IGES / BREP import through the optional gmsh package, with every CAD
  face optionally kept as its own boundary; length unit asked on import.

Still open for hydraulics:

- Irregular (spectrum) and solitary waves; wave direction.
- Several tailwater levels in one case (one reference level is supported).
- Sediment transport and air entrainment (out of scope for now).

## v0.6 - quick additions and hydraulics extras (this version)

The build order from here on follows the capability review of 2026-11, hydraulics first.

Done:

- Turbulence: RNG k-epsilon, standard k-omega, k-kl-omega transition; choice
  between wall functions and a resolved boundary layer.
- Fluids: non-Newtonian laws (Cross, Bird-Carreau, Herschel-Bulkley, power law, Casson).
- A passive tracer; a velocity limiter.
- Free surface: contact angle on walls; Stokes 5th order, cnoidal and solitary
  waves; mesh refinement that follows the water surface (serial and parallel);
  cavitation index computed from the results.

## Next for hydraulics

1. Moving parts: prescribed motion (gates, valves) and floating bodies (6DoF).
2. Cavitating flow in closed conduits (interPhaseChangeFoam: Schnerr-Sauer, Kunz, Merkle).
3. Irregular (spectrum) waves and stream-function waves.

## Then, in this order

1. Cell zones: porous media, MRF, SRF, source terms, fixed-value zones.
2. Heat transfer in one region: buoyancy, thermal boundaries, P1 / DO radiation.
3. Conjugate heat transfer, S2S radiation, solar load, Joule heating.
4. LES, DES, SAS.
5. Sliding meshes (AMI), multi-body motion, mesh deformation; overset last.
6. Compressible flow and equations of state.
7. Phase change, Euler-Euler.
8. Particles.
9. Combustion.

## Next - heat

- Buoyant heat transfer (buoyantSimpleFoam / buoyantPimpleFoam), temperature
  and heat-flux boundaries, thermophysical material database.
- Passive scalar transport.

## v0.6 - more ways in and out

- STL check and repair; geometry booleans.
- Mesh import: Fluent, Gmsh, existing OpenFOAM cases (read boundary and fields).
- Native Windows back-ends: ESI MinGW build and blueCFD-Core.
- Foundation-line (openfoam.org) dictionary dialect.
- Windows installer.

## v0.7 - rotating machinery and regions

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
