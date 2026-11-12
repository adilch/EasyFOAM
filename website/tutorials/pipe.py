"""Laminar flow in a pipe, checked against theory."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def show_speed(d):
    d.go("Results")
    d.results("U", "slice")
    d.set(d.w.results_panel.normal, "y")
    d.view("+y")


def show_pressure(d):
    d.results("p", "slice")


TUTORIAL = Tutorial(
    slug="pipe",
    title="Laminar flow in a pipe",
    summary="Flow inside a shape: a straight pipe whose result you can check by hand.",
    minutes=20,
    level="Beginner",
    topics=["Internal flow", "Checked against theory"],
    run_time="about half a minute for the mesh and a minute for the run, on four cores.",
    intro="""
Slow flow through a straight pipe has an exact solution, known since the 1840s: far enough from the
entrance, the speed across the pipe is a parabola whose peak is **twice** the average speed. That
makes it a good second case: you learn how to simulate the flow *inside* a shape, and you can tell
whether the answer is right.

The pipe is 0.2 m in diameter and 2 m long. The fluid enters at 1 m/s and has a viscosity of
0.004 m²/s, so the Reynolds number is 1 × 0.2 / 0.004 = 50.
""",
    learn=[
        "let the base mesh cut a shape open to make an inlet and an outlet",
        "tell EasyFOAM that the fluid is inside the shape",
        "set an inlet velocity and an outlet pressure",
        "stop a steady run automatically when it has converged, and compare with theory",
    ],
    steps=[
        *from_example("pipe", "pipe", "Laminar flow in a pipe"),
        Step(
            title="The pipe is a cylinder",
            text="""
The only shape is a cylinder called `tube`. Notice that it is **longer than it needs to be**: it
runs from x = −0.5 m to x = 2.5 m, but the mesh will only cover 0 to 2 m. The two ends of the
mesh cut the cylinder open, and those cuts become the inlet and the outlet.
""",
            screen="Geometry",
            before=create("pipe", "pipe"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'tube')", "The shape **tube** is selected and shown in the 3D view."),
                Mark("w.geometry_panel.point1", "**Axis start** and **Axis end**: the two ends of the cylinder's centre line."),
                Mark("w.geometry_panel.radius", "**Radius**: `0.1` m."),
                Mark("w.geometry_panel.level_min", "**Surface refinement** `1`: cells at the pipe wall are half the size of the base cells."),
            ],
            tip="To use your own pipework instead, click **Import** and choose an STL or STEP file.",
        ),
        Step(
            title="The base mesh and where the fluid is",
            text="""
The base mesh is a box of cubes a little wider than the pipe and exactly as long as the part we want
to simulate. One setting matters most here: by default EasyFOAM keeps the mesh *around* the shapes.
For a pipe we want the opposite.
""",
            screen="Mesh",
            marks=[
                Mark("w.mesh_panel.base_min", "The box runs from x = `0` to `2` and is `0.25` m wide and high."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `80`, `10`, `10`, which makes cubes of 25 mm."),
                Mark("w.mesh_panel.fluid_region", "**The fluid is**: *inside tube*."),
                MESH_BUTTON,
            ],
            tip="**Size the base mesh automatically** makes a snug box like this one around any shape you import.",
        ),
        Step(
            title="The mesh of the inside",
            text="""
After about half a minute the mesh appears: only the inside of the pipe is left, with finer cells
along the wall. The boundaries are named after where they came from: `inlet` and `outlet` are the
two end faces of the base mesh, `tube` is the pipe wall.
""",
            screen="Mesh",
            before=lambda d: d.mesh(),
            marks=[
                Mark("step('Mesh')", "The **Mesh** step shows the number of cells, about 24,000."),
                Mark("w.viewer", "The boundaries are listed with their colours in the corner of the view.", "centre"),
            ],
        ),
        Step(
            title="A thick fluid, flowing slowly",
            text="""
The flow is steady and laminar. The fluid is an invented one, thick enough to keep the Reynolds
number at 50.
""",
            screen="Physics",
            marks=[
                Mark("w.physics_panel.turbulence", "**Turbulence**: *Laminar*."),
                Mark("w.physics_panel.material", "**Fluid**: *Custom*."),
                Mark("w.physics_panel.nu", "**Kinematic viscosity**: `0.004`."),
                Mark("w.physics_panel.velocity", "**Initial velocity**: `1`, `0`, `0`. Starting close to the answer saves iterations."),
            ],
        ),
        Step(
            title="The inlet",
            text="At the inlet the fluid enters with the same speed everywhere across the pipe.",
            screen="Boundaries",
            before=lambda d: d.boundary("inlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "Select **inlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Velocity inlet*."),
                Mark("w.boundary_panel.velocity", "**Velocity**: `1`, `0`, `0`."),
            ],
        ),
        Step(
            title="The outlet and the wall",
            text="""
At the outlet the pressure is fixed and the fluid leaves as it likes. Pressures in EasyFOAM are
relative, so zero is the natural choice. The pipe wall `tube` is an ordinary wall: the fluid sticks
to it.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("outlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'outlet')", "Select **outlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Pressure outlet*."),
                Mark("w.boundary_panel.pressure", "**Pressure**: `0`."),
            ],
        ),
        Step(
            title="Run until it has converged",
            text="""
Instead of guessing how many iterations are needed, give a generous limit and a target: the run
stops by itself once every residual is below it.
""",
            screen="Run",
            marks=[
                Mark("w.run_panel.end_time", "**Iterations**: `500`, an upper limit."),
                Mark("w.run_panel.processors", "**Processor cores**: `4`. Use fewer if your computer has fewer."),
                Mark("w.run_panel.residual_target", "**Stop below residual**: `1e-5`."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="Converged",
            text="""
The residuals fall steadily and the run ends well before the limit, as soon as the last of them
passes the target.
""",
            screen="Run",
            tab="Residuals",
            before=lambda d: d.run(),
            marks=[
                Mark("tab('Residuals')", "All four lines fall below 0.00001.", "top"),
                Mark("step('Run')", "The step shows at which iteration the run finished."),
            ],
        ),
        Step(
            title="The speed along the pipe",
            text="""
On a slice along the pipe you can watch the profile develop: flat at the inlet, then the fluid near
the wall slows down and the middle speeds up, until the profile no longer changes.

Now the check. Theory says the middle ends up at **twice** the average speed, 2.0 m/s. The top of the
colour scale reads about **1.93 m/s**: within 4 % on this coarse mesh.
""",
            screen="Results",
            before=show_speed,
            cover=True,
            marks=[
                Mark("w.results_panel.field", "**Quantity**: `U`."),
                Mark("w.results_panel.normal", "**Slice plane**: *Normal to y*."),
                Mark("viewbutton('+Y')", "Click **+Y** to look at the slice from the side."),
            ],
        ),
        Step(
            title="The pressure drop",
            text="""
Switch the quantity to the pressure. It falls evenly along the developed part of the pipe. Theory
gives 32 × viscosity × speed / diameter² = 32 × 0.004 × 1 / 0.04 = **3.2** per metre; the
simulation gives about 3.15.

EasyFOAM shows the pressure divided by the density (in m²/s²). Multiply by the density, here
1000 kg/m³, to get pascals: 3200 Pa per metre.
""",
            screen="Results",
            before=show_pressure,
            marks=[Mark("w.results_panel.field", "**Quantity**: `p`.")],
        ),
        Step(
            title="Try it yourself",
            text="""
- Raise **Surface refinement** of the tube to `2` and mesh again: the peak speed moves closer to 2.0.
- Double the inlet speed. The pressure drop doubles too, as it must in laminar flow.
- Set the viscosity to `1e-6` (water) and choose a turbulence model: the flat profile of turbulent
  pipe flow appears instead of the parabola.
""",
        ),
    ],
)
