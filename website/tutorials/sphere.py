"""Air flow past a sphere: external flow with drag."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def show_speed(d):
    d.go("Results")
    d.results("U", "slice")
    d.set(d.w.results_panel.normal, "y")
    d.view("+y")


def compute_yplus(d):
    d.set(d.w.results_panel.function, "yPlus")
    d.w.compute_quantity("yPlus")
    d.wait()
    d.view("iso")


TUTORIAL = Tutorial(
    slug="sphere",
    title="Air flow past a sphere",
    summary="External flow: a body in a wind tunnel, a turbulence model, and its drag.",
    minutes=25,
    level="Beginner",
    topics=["External flow", "Turbulence", "Forces"],
    run_time="about a minute for the mesh and two minutes for the run, on four cores.",
    intro="""
Most flows of practical interest go *around* something: a car, a building, a bridge pier. The recipe
is always the same. Put the body in a box that is much larger than the body (a virtual wind tunnel),
refine the mesh near the body and in its wake, blow air in at one end and measure the force.

Here the body is a sphere 1 m across in air at 10 m/s. The Reynolds number is about 670,000, so the
flow is turbulent and needs a turbulence model.
""",
    learn=[
        "refine the mesh on a surface and inside a region",
        "size a wind tunnel around a body",
        "use a turbulence model",
        "record drag and lift while the run goes on, and check the mesh near the wall with y+",
    ],
    steps=[
        *from_example("sphere", "sphere", "Air flow past a sphere"),
        Step(
            title="The body",
            text="""
The first shape is the sphere, `ball`. Its **surface refinement** decides how fine the mesh is on
its skin: each level halves the size of the base cells. Level 2 to 3 means the cells there are 4 to
8 times smaller than the base cells.
""",
            screen="Geometry",
            before=create("sphere", "sphere"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'ball')", "Select **ball**."),
                Mark("w.geometry_panel.radius", "**Radius**: `0.5` m, centred on the origin."),
                Mark("w.geometry_panel.level_min", "**Surface refinement, min**: `2`."),
                Mark("w.geometry_panel.level_max", "**Surface refinement, max**: `3`, used where the surface curves."),
            ],
        ),
        Step(
            title="A finer mesh in the wake",
            text="""
The second shape is not a solid. It is a **refinement region**: a box behind the sphere inside which
the cells are made smaller, because that is where the wake is and where the flow changes quickly.
""",
            screen="Geometry",
            before=lambda d: d.shape("wake"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'wake')", "Select **wake**."),
                Mark("w.geometry_panel.role", "**Use as**: *Refinement region*."),
                Mark("w.geometry_panel.box_min", "The box reaches from 1 m ahead of the centre to 4 m behind it."),
                Mark("w.geometry_panel.region_level", "**Refinement inside**: `1`, so half the base cell size."),
            ],
        ),
        Step(
            title="The wind tunnel",
            text="""
The base mesh is the tunnel: 10 m long, 5 m wide and 5 m high, made of 0.25 m cubes. The sphere sits
3 m from the inlet, with 7 m behind it for the wake. The faces already carry useful names: air comes
in through `inlet` (xMin), leaves through `outlet` (xMax), and the four `sides` are far away.
""",
            screen="Mesh",
            marks=[
                Mark("w.mesh_panel.base_min", "**Corner (min)** `-3`, `-2.5`, `-2.5` and **Corner (max)** `7`, `2.5`, `2.5`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `40`, `20`, `20`."),
                Mark("w.mesh_panel._face_names['xMin']", "The names of the six faces."),
                MESH_BUTTON,
            ],
            tip="For your own body, click **Size the base mesh automatically**: it builds a tunnel like this one around it.",
        ),
        Step(
            title="The mesh",
            text="""
Meshing takes about a minute. The result has roughly 28,000 cells: coarse far away, finer in the wake
box, finest on the sphere.
""",
            screen="Mesh",
            before=lambda d: d.mesh(),
            marks=[
                Mark("step('Mesh')", "The number of cells."),
                Mark("w.viewer", "Turn the view with the left mouse button to look at the sphere's surface mesh.", "centre"),
            ],
        ),
        Step(
            title="Air and a turbulence model",
            text="""
The defaults fit: steady flow of air with the *k-omega SST* model, the usual first choice for flow
around bodies. Set the starting velocity to the wind speed so that the run does not have to
accelerate the air from rest.
""",
            screen="Physics",
            marks=[
                Mark("w.physics_panel.solver", "**Flow type**: *Incompressible flow, steady*."),
                Mark("w.physics_panel.turbulence", "**Turbulence**: *k-omega SST*."),
                Mark("w.physics_panel.material", "**Fluid**: *Air*."),
                Mark("w.physics_panel.velocity", "**Initial velocity**: `10`, `0`, `0`."),
            ],
        ),
        Step(
            title="The wind",
            text="""
Only the inlet needs a number. The outlet is a pressure outlet at zero, and the `sides` are *slip*
boundaries: nothing flows through them and they cause no friction, which is how a far-away boundary
should behave. The sphere itself, `ball`, is a wall.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("inlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "Select **inlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Velocity inlet*."),
                Mark("w.boundary_panel.velocity", "**Velocity**: `10`, `0`, `0`."),
            ],
        ),
        Step(
            title="How long to run",
            text="Two hundred iterations are enough for the drag to settle on this mesh.",
            screen="Run",
            marks=[
                Mark("w.run_panel.end_time", "**Iterations**: `200`."),
                Mark("w.run_panel.write_interval", "**Save every (iterations)**: `50`."),
                Mark("w.run_panel.processors", "**Processor cores**: `4`. The mesh is split and put back together for you."),
            ],
        ),
        Step(
            title="Measure the drag",
            text="""
Further down the same panel, switch on the force monitor. The drag coefficient compares the force
with the pressure of the wind on the body's frontal area, here a disc of radius 0.5 m:
π × 0.5² = 0.7854 m².
""",
            screen="Run",
            marks=[
                Mark("w.run_panel.forces_on", "Tick **Record drag and lift every iteration**."),
                Mark("w.run_panel.ref_area", "**Reference area**: `0.7854`. The ruler button estimates it from the shapes."),
                Mark("w.run_panel.ref_length", "**Reference length**: `1`, the diameter."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="Watch the drag settle",
            text="""
Open the **Forces** tab while the run goes on. The drag coefficient `Cd` swings at first and then
flattens out. A force that no longer changes is a better sign of a finished run than the residuals.

On this coarse mesh `Cd` ends near **0.21**. Measurements for a smooth sphere at this speed lie
between 0.1 and 0.5, because the flow is right at the point where the drag suddenly drops; a
finer mesh is needed to say more.
""",
            screen="Run",
            tab="Forces",
            before=lambda d: d.run(),
            marks=[
                Mark("tab('Forces')", "Open the **Forces** tab.", "top"),
                Mark("w.force_label", "The latest coefficients, and the forces in newtons."),
            ],
        ),
        Step(
            title="The flow around the sphere",
            text="""
A slice through the middle shows the air slowing to a stop at the front of the sphere, speeding up
over the top and bottom, and leaving a slow wake behind.
""",
            screen="Results",
            before=show_speed,
            cover=True,
            marks=[
                Mark("w.results_panel.field", "**Quantity**: `U`. Try `p` for the pressure, too."),
                Mark("w.results_panel.normal", "**Slice plane**: *Normal to y*."),
                Mark("w.results_panel.position", "Drag **Slice position** to move the slice through the tunnel."),
            ],
        ),
        Step(
            title="Is the mesh fine enough at the wall?",
            text="""
Turbulence models make assumptions about the thin layer of air next to a wall, and those only hold
if the first cell has the right height. The number that tells you is called **y+**. With wall
functions, as used here, it should lie roughly between 30 and 300.

Here it runs from about 130 to 1100, with a mean near 600: the cells on the sphere are too thick.
That is the honest verdict on this quick example mesh, and the reason its drag figure is only a
rough one. The next step shows what to do about it.
""",
            screen="Results",
            before=compute_yplus,
            marks=[
                Mark("w.results_panel.function", "Under **Derived quantities**, choose *y+ (wall resolution)*."),
                Mark("w.results_panel.compute", "Click **Compute for the latest result**. The sphere is then coloured by y+."),
                Mark("w.results_panel.info", "The range of y+ on each wall is written here.", "left"),
            ],
        ),
        Step(
            title="Try it yourself",
            text="""
- Raise the sphere's surface refinement to `3` and `4`, mesh and run again: y+ falls and the drag changes.
- Give the sphere **Boundary-layer cells** (try `3`) in the Geometry step: thin cells stacked on its
  skin bring y+ down much more cheaply than refining everywhere.
- Replace the sphere: click **Import** in the Geometry step, bring in an STL or STEP file of your own
  body, and click **Size the base mesh automatically**.
""",
        ),
    ],
)
