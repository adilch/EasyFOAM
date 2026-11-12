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

## v0.6 - quick additions and hydraulics extras

The build order from here on follows the capability review of 2026-11, hydraulics first.

Done:

- Turbulence: RNG k-epsilon, standard k-omega, k-kl-omega transition; choice
  between wall functions and a resolved boundary layer.
- Fluids: non-Newtonian laws (Cross, Bird-Carreau, Herschel-Bulkley, power law, Casson).
- A passive tracer; a velocity limiter.
- Free surface: contact angle on walls; Stokes 5th order, cnoidal and solitary
  waves; mesh refinement that follows the water surface (serial and parallel);
  cavitation index computed from the results.

## v0.7 - moving gates and floating bodies (this version)

Done:

- Any solid shape can be given a motion in the Geometry step: move to a new
  position over a set time (a gate that opens), swing back and forth, or float.
- A floating body is moved by the water and its own weight (rigid-body motion,
  6DoF). Its mass, centre and inertia are worked out from its shape and
  density, for boxes, spheres, cylinders and closed STL surfaces. Freedom:
  up and down only, in the x-z plane, or all six directions.
- A Motion tab plots where each moving shape is and how far a floating body
  has turned, live.
- Two examples: a lifting sluice gate and a floating box. Checks stop set-ups
  that cannot work (steady solver, a floating body without water, and so on).

Open items:

- The mesh stretches to follow a shape; cells are not added or removed. So a
  gate cannot shut completely, and a body cannot roll over or travel far.
  Overset or re-meshing would lift this.
- Floating bodies and shapes with a set motion cannot be mixed in one run.
- No mooring lines, springs or dampers on a floating body; it always starts at rest.
- Rotation about a hinge (a flap gate, a radial gate) as a set motion.
- Combining moving shapes with mesh refinement at the water surface.

## Tutorials website (0.7.1)

- Ten tutorials in `docs/` (open `docs/index.html`): install, cavity from an empty project, pipe,
  sphere, dam break, weir, waves, sluice gate, floating box, and a spillway from an STL file.
- Each tutorial is described once in `website/tutorials/`; that description operates the real
  application to take the pictures and produces the page, so text and pictures cannot drift apart.
- Found on the way and fixed: a quantity computed after the run (y+, vorticity) was not offered in
  the Results step when earlier saved times did not have it.

Open items: tutorials for non-Newtonian fluids, the tracer, the tailwater outlet and CAD (STEP)
import; a search box; translations.

## v0.8 - draw your own shapes (this version)

Done:

- Three more shapes to draw next to box, sphere and cylinder: a cone (or tapering round piece), a
  wedge (ramp), and an outline sketched by hand that is extruded across the plane it is drawn in.
- A sketch pad for the outline: click to add corners, drag them, right-click to remove them, snap
  to a grid, type exact corners in a table, start from a rectangle, triangle, trapezoid or rounded
  spillway crest. Outlines need not be convex; one whose sides cross is refused with a message.
- Handles in the 3D view to move and resize the selected box, wedge, sphere, cylinder or cone.
- New shapes appear inside the base mesh at a size that fits it.
- Drawn shapes are written into the case as surface files when the mesh is made, so they work
  wherever an imported file does (flow inside them, floating, refinement regions) and the case
  stays complete without EasyFOAM.

Open items:

- Turning a box or a wedge (they follow the axes); revolving an outline about an axis.
- Arcs and curves in the sketch (only straight sides for now); several outlines in one shape (holes).
- Saving a drawn shape as an STL file for use elsewhere.

## Next for hydraulics

1. Cavitating flow in closed conduits (interPhaseChangeFoam: Schnerr-Sauer, Kunz, Merkle).
2. Irregular (spectrum) waves and stream-function waves.
3. Hinged gates and moorings (see the open items above).

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

## Later - more ways in and out

- STL check and repair; geometry booleans.
- Mesh import: Fluent, Gmsh, existing OpenFOAM cases (read boundary and fields).
- Native Windows back-ends: ESI MinGW build and blueCFD-Core.
- Foundation-line (openfoam.org) dictionary dialect.
- Windows installer.

## Later - rotating machinery and regions

- Cell zones, MRF, porous zones.
- Cyclic / AMI interfaces, sliding mesh.
- Multi-region meshing and conjugate heat transfer (chtMultiRegionFoam).

## Later

- Compressible flow (rhoSimpleFoam, rhoPimpleFoam, rhoCentralFoam).
- Particles (DPM), sprays, combustion.
- Overset motion (large movements, bodies that roll over, gates that shut).
- LES / DES set-up helpers.
- Parameters and expressions; parametric sweeps from the command line.
- Remote and cluster runs (SSH, Slurm, PBS).
- Report generation.
