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

## v0.8 - draw your own shapes (done)

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

## v0.9 - hydraulic results (done)

- A long section of any free-surface result: the water fraction is integrated over vertical lines
  across the channel at stations along its axis, which gives water level, depth, flow area, top width,
  discharge, mean velocity, Froude number, specific energy, the energy line and the Coriolis coefficient.
  Oscillating flows are averaged over several saved times.
- Hydraulic jumps: the toe is found where the incoming jet ends (the velocity profile turns over), the
  sequent depth and energy loss are compared with Bélanger, and the jump is classed (USBR). Control
  sections are compared with critical depth.
- Pressure along a structure and the force and overturning moment on it; bed shear stress and
  sediment mobility (Shields).
- Checked: a hydraulic jump below a sluice gate (sequent depth within 2 % of Bélanger when averaged,
  gate force within 5 % of the momentum balance), critical depth on a weir crest.

## v0.10 - roughness, hydrographs and rating curves (done)

- Wall roughness from Manning's n or a sand-grain height (Strickler); checked in a rough channel against
  the 1D backwater curve (effective n within 3 % of the n set).
- Inflow hydrographs and tailwater levels as time tables. The tailwater is one expression on the
  pressure, rho g (level - hRef) with the density beside each face: water feels the tailwater, air stays
  at ambient, in serial and parallel runs alike. The inflow is spread over the wetted part of the inlet so
  that exactly the water asked for comes in, however smeared the surface is there.
- A rating-curve sweep: the inflow steps through discharges; head, weir coefficient and whether the
  level settled are read off for each.

## v0.11 - contact tanks and reacting tracers (done)

- Several tracers with their own inlet concentrations, a first-order decay (chlorine residual) and the
  age of the water.
- A tracer test in the frozen steady flow, step or pulse: T10, T50, T90, mean residence time, baffling
  factor with its EPA class, Morrill index, and the share of a decaying substance left at the outlet.
- Checked in a contact-tank example: the outlet age and the mean residence time equal V/Q within
  0.3 %, the tracer fed in balances what is left plus what has gone, nine baffles raise the baffling
  factor from 0.19 to 0.51, and the steady chlorine residual matches the one from the residence times.
- Lessons kept in the code: steady tracers are carried with upwind and never relaxed (relaxation and
  limitedLinear left the age 8 % high or blew up a decaying tracer), and water drawn back in at an outlet
  keeps its own concentration.

## v0.12 - channels and terrain (done)

- A channel builder: rectangular, trapezoidal, compound or circular culvert sections, bed slope, and a
  centreline of straight pieces and bends. blockMesh makes a mesh fitted to it (cells follow the banks
  and bends); the starting water is a cell zone, and the long section follows the curved centreline.
- Terrain from survey files: XYZ points, ESRI ASCII grids, GeoTIFF and LandXML TIN surfaces, moved to
  local coordinates, turned so the river runs along x, resampled and closed into a solid that
  snappyHexMesh cuts out of the base mesh.

Open items:

- Channels: transitions between sections, a different section per piece, drop structures built in.
- Terrain: breaklines and building footprints; burning a surveyed channel into a coarser ground.
- Long sections on terrain follow the axis of the base mesh; a centreline drawn on the map.

## v0.13 - hydraulic structures from design values (done)

- A **Structure** menu in the Geometry step and an `easyfoam structure` command make six structures
  from their design values, drawn from the side and from above as they are typed: an ogee crest
  shaped by the WES standard for its design head (with its design discharge), a stepped spillway
  (with its flow regime), a labyrinth weir, USBR stilling basins II, III and IV sized from the
  entering depth and Froude number, a box or pipe culvert through an embankment (barrels on or
  buried in the bed) and a vertical-slot fishway.
- Two new examples and tutorials: an ogee crest run at its design head, and a Type III basin
  holding the jump of a Froude 6 jet, fed through a slot at the inlet instead of a tall reservoir.

Open items:

- Piano-key weirs, side-channel and shaft (morning-glory) spillways, flip buckets, baffled chutes
  (USBR Type IX), Parshall flumes; wing walls and aprons for culverts.
- Structures placed on a built channel, following its bed slope and curved centreline.
- A rating curve read straight from a structure's design (head against discharge).

## v0.14 - easier to use (this version)

- **Reports**: one click (toolbar, File menu, Results step, `easyfoam report`) writes a web page or a
  PDF for a design note: the set-up, the mesh, the run, monitors, the 3D view and every plot, and the
  results checked against theory, each check with its verdict.
- **Search** (Ctrl+K) for every setting, section, choice and command, including words the window
  does not use itself (tailwater, gauge, Strickler, CFL, scour).
- Long forms in **sections that fold** and remember it; the ones most projects do not need start
  folded and say in a few words what they hold.
- **Picking** in the 3D view: the value under the cursor, gauges and probes placed with a click,
  distances, and the line the long section follows.
- Plots and log in a **window of their own** (a second screen); files **dropped** on the window;
  a **?** per step that opens the tutorial at that step; **project templates**; a **dark theme** and
  the text size.

Open items:

- Re-take the tutorial pictures with the new toolbar, sections and view bar.
- More checks in reports: rating curves against weir formulas, energy dissipation of basins, culvert
  control (inlet or outlet).

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
