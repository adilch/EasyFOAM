"""Dam break: the first free-surface case."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def show_water(time_):
    def show(d):
        d.go("Results")
        d.results("alpha.water", "slice", time_)
        d.set(d.w.results_panel.normal, "y")
        d.view("+y")

    return show


TUTORIAL = Tutorial(
    slug="dambreak",
    title="Dam break",
    summary="Water and air with a free surface: a column of water collapses in a tank.",
    minutes=20,
    level="Beginner",
    topics=["Free surface"],
    run_time="a few seconds for the mesh and about a minute for the run.",
    intro="""
Rivers, spillways, tanks and waves all have a **free surface**: water below, air above, and a
boundary between them that moves. EasyFOAM follows it by storing, for every cell, the share of the
cell that is full of water (a number between 0 and 1 called `alpha.water`).

The dam break is the simplest such case. A column of water stands in one corner of a tank; at time
zero the invisible dam holding it disappears. The tank is a thin slice, one cell thick, so the run
is quick.
""",
    learn=[
        "choose the free-surface flow type",
        "say where the water is at the start",
        "leave the top of the tank open to the air",
        "run in time, with a time step that adjusts itself, and step through the saved moments",
    ],
    steps=[
        *from_example("dambreak", "dambreak", "Dam break"),
        Step(
            title="A tank with an open top",
            text="""
There are no shapes, so go straight to the **Mesh** step. The tank is 0.584 m wide and high and one
cell (14.6 mm) thick. Look at the names of the faces: three of them are `walls`, the top is
`atmosphere`, and the front and back are `empty` because nothing happens through the thickness.
""",
            screen="Mesh",
            before=create("dambreak", "dambreak"),
            marks=[
                Mark("w.mesh_panel.base_max", "**Corner (max)**: `0.584`, `0.0146`, `0.584`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `46`, `1`, `46`."),
                Mark("w.mesh_panel._face_names['zMax']", "**zMax**, the top, is named `atmosphere` and has the type `patch`: an opening."),
                Mark("w.mesh_panel._face_types['yMin']", "**yMin** and **yMax** are `empty`.", "right"),
                MESH_BUTTON,
            ],
        ),
        Step(
            title="Water and air",
            text="""
In the **Physics** step the flow type is what makes this a free-surface case. Once it is chosen, the
fluid you pick is the water, and a new group of settings for the air and the water's starting
position appears below.
""",
            screen="Physics",
            before=lambda d: d.mesh(),
            marks=[
                Mark("w.physics_panel.solver", "**Flow type**: *Free surface: water and air*."),
                Mark("w.physics_panel.turbulence", "**Turbulence**: *Laminar* is enough for this short, violent event."),
                Mark("w.physics_panel.material", "**Fluid**: *Water*."),
            ],
        ),
        Step(
            title="Where the water starts",
            text="""
Scroll down to **Water and air**. Gravity points down the z axis. The table lists boxes that are
full of water at the start; everything else is air. Here there is one box: the column, 0.146 m wide
and 0.292 m high, in the corner.
""",
            screen="Physics",
            marks=[
                Mark("w.physics_panel.gravity", "**Gravity**: `0`, `0`, `-9.81`."),
                Mark("w.physics_panel.water_table", "One box of water: from `0, 0, 0` to `0.1461, 0.0146, 0.292`."),
            ],
            tip="**Fill to a level** adds a box that fills the whole tank up to a height: the quick way to make a pond or a reservoir.",
        ),
        Step(
            title="The open top",
            text="""
The top of the tank must let air in and out as the water moves, without holding the water in. That
is what *Open to the atmosphere* does. EasyFOAM chose it by itself because of the name.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("atmosphere"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'atmosphere')", "Select **atmosphere**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Open to the atmosphere*."),
            ],
        ),
        Step(
            title="Running in time",
            text="""
This is a *transient* run: it marches forward in small time steps. You choose how long to simulate
and how often to save. The time step looks after itself: EasyFOAM shortens it when the water moves
fast, so that nothing crosses more than a cell in one step (that is what the Courant number
measures).
""",
            screen="Run",
            marks=[
                Mark("w.run_panel.end_time", "**End time**: `1` s."),
                Mark("w.run_panel.delta_t", "**Time step**: `0.001` s to start with."),
                Mark("w.run_panel.adjust", "**Keep the Courant number below** `0.8`: leave it ticked."),
                Mark("w.run_panel.write_interval", "**Save every**: `0.05` s, which gives 20 saved moments."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="The run",
            text="""
This small case takes only a few seconds. While a run goes on, the line at the bottom of the window
shows how far it is and how much of the tank is filled with water. That share should stay the same
from start to end: a quick check that no water is lost.
""",
            screen="Run",
            tab="Residuals",
            before=lambda d: d.run(),
            marks=[
                Mark("tab('Residuals')", "In a run in time the residuals do not fall to zero; they stay at a steady, low level.", "top"),
                Mark("step('Run')", "The **Run** step shows that the run reached the end time."),
            ],
        ),
        Step(
            title="The collapse",
            text="""
When the run ends, look at `alpha.water` on a slice: red is water, blue is air. At 0.2 s the column
has slumped and a tongue of water is racing along the floor.
""",
            screen="Results",
            before=show_water(0.2),
            cover=True,
            marks=[
                Mark("w.results_panel.time", "**Saved time**: `0.2`."),
                Mark("w.results_panel.field", "**Quantity**: `alpha.water`."),
                Mark("w.results_panel.mode", "**Show**: *Slice through the flow*."),
                Mark("w.results_panel.normal", "**Slice plane**: *Normal to y*."),
            ],
        ),
        Step(
            title="The splash",
            text="""
Step through the saved times. By 0.5 s the water has hit the far wall, climbed it and is falling
back on itself.
""",
            screen="Results",
            before=lambda d: d.results("alpha.water", "slice", 0.5),
            marks=[Mark("w.results_panel.time", "**Saved time**: `0.5`. Use the arrow keys to step through the others.")],
        ),
        Step(
            title="Try it yourself",
            text="""
- Use `92`, `1`, `92` cells: the water surface becomes sharper and the splash shows more detail.
- In the Physics step choose *Free surface, sharper interface* as the flow type and compare.
- Make the column taller, or add a second box of water on the other side.
- Click **Open in ParaView** and press play to watch the collapse as a film.
""",
        ),
    ],
)
