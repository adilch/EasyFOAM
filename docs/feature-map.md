# Feature map

What a commercial OpenFOAM front-end offers, what already exists as open source,
and where EasyFOAM stands. Researched on 2026-11-11.

## How this was researched (clean-room rules)

- SimFlow's features were taken **only from public pages**: sim-flow.com and
  help.sim-flow.com (documentation, FAQ, tutorials, pricing).
- SimFlow's programs were **not** reverse engineered, decompiled or disassembled.
  Its licence (clause 3.3b) forbids that, and code derived from it could not be
  published as open source.
- No SimFlow code, icons, texts, material data or screen layouts are used.
  Everything here is written from scratch against OpenFOAM's own open formats.
- Contributors who have seen SimFlow's source or decompiled code should not
  contribute to the matching parts of EasyFOAM.

## SimFlow at a glance (public information)

| Area | What it offers |
|---|---|
| Workflow | One window with about 27 panels, from Geometry and Hex Meshing through Boundary Conditions, Monitors and Run to Postprocessing. A wizard picks the solver from a few questions. |
| Geometry | Import STL, OBJ, STEP, IGES, BREP, airfoil DAT. Box, cylinder, sphere primitives. Move/rotate/scale, booleans (not on STL), STL check and split, face groups that become patches. |
| Meshing | Hex-dominant cut-cell meshing in the snappyHexMesh style: base mesh (box, cylinder, 2D plate, wedge), surface and volume refinement, gap refinement, boundary layers, material point, multi-region, parallel meshing. 2D airfoil mesher, optional Gmsh. |
| Mesh tools | Import from Fluent, Ansys, I-DEAS, Gambit, Gmsh, CFX4, OpenFOAM. checkMesh with bad cells shown in 3D, transforms, refine, extrude, patch split/merge/retype, cyclic/AMI interfaces, cell zones. |
| Solvers | 54 solvers of the ESI OpenFOAM line: incompressible, compressible, buoyant and conjugate heat transfer, VoF multiphase, cavitation and phase change, Euler-Euler, particles (DPM/MPPIC), combustion and sprays, overset, SRF. |
| Models | RANS, LES, DES; radiation; porous media; MRF; non-Newtonian; waves; passive scalars; rigid, deforming and 6DoF mesh motion. |
| Set-up | About 70 boundary-condition types with time tables, material database, initialisation (uniform, potential flow, by region, mapped), full discretisation and linear-solver control, named parameters and expressions. |
| Run | Serial or parallel with a core count, adaptive time step, write and purge control, e-mail notification, chained runs. Back-ends: bundled Windows build, WSL, bashrc script, Docker. |
| Monitoring | Live residuals with auto-stop, forces and coefficients, probes, volume and boundary statistics, runtime slices in the 3D view. |
| Post-processing | Calculators (vorticity, Q, y+, wall shear stress, Mach), bundled ParaView for everything else, export to other formats. |
| Platforms | Windows, Linux, macOS (Apple Silicon). ESI OpenFOAM v2512/v2506/v2212/v1812. |
| Editions | Free: 200,000 mesh nodes, 1 CPU, no case import/export. Professional 8,000 EUR/year, Enterprise 10,000 EUR/year. |

Sources: https://help.sim-flow.com/documentation/panels/geometry ,
https://help.sim-flow.com/solvers , https://help.sim-flow.com/boundary-conditions ,
https://help.sim-flow.com/tutorials , https://help.sim-flow.com/faq ,
https://sim-flow.com/pricing-plans/ .

The 28 official tutorials show what users do most: pipe flow, wind around
buildings, car and wing aerodynamics, ventilation, ship hull and dam break
(free surface), mixing tank and propeller (rotating parts), electronics
cooling and heat exchangers (heat transfer), cyclone and spray (particles).

## Existing open-source front-ends

| Project | Licence | Stack | State | Notes |
|---|---|---|---|---|
| [BARAM](https://github.com/nextfoam/baram) | GPL-3.0 | Python, PySide6, VTK | Active, v26.3 (Sep 2026) | Native Windows/Linux/macOS. Mesher and flow solver GUIs. Uses its own bundled, modified solvers. |
| [CfdOF](https://github.com/jaheyns/CfdOF) | LGPL-3.0 | FreeCAD workbench | Very active | Needs FreeCAD. cfMesh, snappyHexMesh, gmsh. Works with blueCFD, WSL, Docker. |
| [SplashFOAM](https://github.com/cfddose/Splash) | LGPL-3.0 | Python | Slow | Ubuntu only (Windows through WSL). |
| [HELYX-OS](https://github.com/ENGYS/HELYX-OS) | GPL | Java | Deprecated | OpenFOAM 4.1 era. |
| FoamPilot, OpenFOAM Studio | MIT | Electron | New, small | Early wizards. |

**Is there still a gap?** A narrower one than "no free GUI exists". BARAM is a
credible product and CfdOF is mature for FreeCAD users. What is missing is a
standalone application that drives the user's **own stock OpenFOAM** (any
current version, through WSL or natively), keeps **plain case folders** that
remain usable by hand, and has no cell or core limits. That is the space
EasyFOAM aims at. If that distinction does not matter to you, use BARAM.

## Where EasyFOAM stands (v0.12)

Legend: done = works and is tested end to end; partial; planned = see roadmap.

| Capability | Status |
|---|---|
| Use your own OpenFOAM through WSL (auto-detected), Linux native | done |
| Native Windows OpenFOAM builds (ESI MinGW, blueCFD) | planned |
| Plain case folder, exact scripts kept in `.easyfoam/`, logs as `log.<step>` | done |
| Command line for every operation (batch use) | done |
| STL import (ASCII and binary), box / sphere / cylinder primitives | done |
| Drawn shapes: cone, wedge (ramp), and an outline sketched with the mouse and extruded | done |
| Sketch pad: click, drag and delete corners, snap to a grid, type exact corners, ready-made outlines | done |
| Move and resize shapes with handles in the 3D view | done |
| Rotating boxes and wedges, revolving an outline, curved sides in the sketch | planned |
| STL regions (named solids) as separate patches, each a wall or an opening | done |
| STEP / IGES / BREP import (optional gmsh package), each CAD face usable as its own boundary | done |
| Length unit on import (m, cm, mm, in) | done |
| Booleans, STL repair and splitting | planned |
| Base mesh box with named faces, automatic wind-tunnel or snug internal sizing | done |
| Internal flow: fluid inside a chosen shape, interior point found automatically for closed surfaces | done |
| snappyHexMesh: surface refinement, refinement regions and by distance, boundary layers, feature edges | done |
| Gap refinement, multi-region meshing, parallel meshing, 2D and wedge base meshes | planned |
| Mesh import (Fluent, Gmsh), mesh transforms, patch editing, cyclic/AMI | planned |
| checkMesh report | done (text); 3D display of bad cells planned |
| Incompressible flow, steady and transient (simpleFoam, pimpleFoam) | done |
| Laminar, k-epsilon (standard, realizable, RNG), k-omega (standard, SST), Spalart-Allmaras, k-kl-omega transition | done |
| Wall functions or resolved boundary layer (low-Re wall treatment) | done |
| Non-Newtonian fluids: Cross, Bird-Carreau, Herschel-Bulkley, power law, Casson | done |
| Passive tracer carried by the flow; velocity limiter | done |
| LES, DES, SAS | planned |
| Potential-flow initialisation | done |
| Free-surface flow of water and air (VoF, interFoam) with gravity and surface tension | done |
| Initial water regions (boxes, fill to a level); water-surface display; water-volume read-out | done |
| Hydraulic boundaries: inlet by flow rate that follows the water level, open atmosphere, free outflow | done |
| Heat transfer, compressible, rotating machinery, particles, combustion | planned |
| Outlet at a fixed tailwater level | done |
| Waves: Stokes 1st / 2nd / 5th order, cnoidal and solitary, with an absorbing outlet | done |
| Contact angle of the water surface on walls | done |
| Mesh refined at the water surface while running (serial and parallel) | done |
| Cavitation index from free-surface results, with a plain-language verdict | done |
| Discharge through boundaries and water depth at gauge points, with live plots | done |
| Sharper interface solver (interIsoFoam) | done |
| Moving shapes with a set motion: move to a new position (gates), swing back and forth | done |
| Floating bodies moved by the water (6DoF): mass and inertia from shape and density; heave, in-plane or all six | done |
| Live plot of where moving shapes are and how far a floating body has turned | done |
| Hinged (rotating) gates, moorings and springs, large motion by overset meshes | planned |
| Cavitating flow solver, irregular waves | planned |
| Long section of a free-surface result: water level, bed, energy line, Froude number, specific energy, discharge per station, along a straight or curved centreline, averaged over saved times | done |
| Hydraulic jumps found and compared with Bélanger (sequent depth, energy loss, USBR type); control sections compared with critical depth | done |
| Pressure along a structure, and the force and overturning moment on it (per metre width when it spans the channel) | done |
| Bed shear stress and sediment mobility (Shields critical stress) on the bed | done |
| Wall roughness given as Manning's n or a sand-grain height (rough wall functions) | done |
| Inflow hydrographs and tailwater levels that change in time; the inflow lets in exactly the water asked for | done |
| Rating-curve sweep: a run steps through discharges and gives head, weir coefficient and steadiness for each | done |
| 1D gradually-varied flow profile with Manning's n drawn over the long section | done |
| Several tracers, each with its own inlet concentrations; first-order decay (chlorine); the age of the water | done |
| Tracer test in the frozen flow (step or pulse): T10, T50, T90, mean residence time, baffling factor, Morrill index, the residual of a decaying substance at the outlet | done |
| Channel builder: rectangular, trapezoidal, compound (floodplains) or circular culvert sections, bed slope, straight pieces and bends; mesh fitted to the channel by blockMesh, starting water as a cell zone | done |
| Terrain from XYZ points, ESRI ASCII grids, GeoTIFF rasters and LandXML surfaces: local coordinates, turned to run along x, resampled and closed into a solid that the mesh is cut from | done |
| Sediment transport and bed change, air entrainment | planned |
| Boundary presets: velocity inlet, pressure outlet, wall, moving wall, slip, symmetry/empty | done |
| Time tables for inflow and tailwater | done |
| Wider boundary-condition library, profiles | planned |
| Material list (air, water, oils) | done (small) |
| Numerics presets (robust / accurate) | done; per-term editing planned |
| Parallel run with automatic decomposition and reconstruction | done |
| Live residual plot, convergence target, solver log, progress bar | done |
| Graceful stop (saves first), continue a run, final state always saved | done |
| Start page, step status badges, pre-run checklist, tooltips, SVG icons | done |
| Step-by-step tutorials website, with pictures taken by running each tutorial in the real program | done |
| Shape and boundary highlighting, view buttons, draggable point inside the fluid | done |
| Drag and lift coefficients with live plot and forces in newtons | done |
| y+, wall shear stress, vorticity, Q computed on demand | done |
| Probes (pressure and speed at points) with live plot | done |
| Frontal-area estimate, renaming shapes (and so their boundaries) | done |
| Field statistics monitors, gap refinement, bad cells shown in 3D | planned |
| Built-in 3D view of geometry, mesh and results with slices | done (basic) |
| One-click ParaView | done |
| Parametric studies, parameters and expressions | planned |
| Cluster / remote runs | planned |
