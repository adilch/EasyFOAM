"""A lifting sluice gate: a shape with a set motion."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def show_water(d):
    d.wait()
    d.go("Results")
    d.results("U", "water", 0.7)
    d.view("iso")


TUTORIAL = Tutorial(
    slug="gate",
    title="Lifting sluice gate",
    summary="A shape that moves during the run: a gate lifts and the water behind it runs out underneath.",
    minutes=20,
    level="Intermediate",
    topics=["Free surface", "Hydraulic structures", "Moving shapes"],
    run_time="a few seconds for the mesh and about a minute for the run, on two cores.",
    intro="""
Gates and valves change the flow by moving. In EasyFOAM any solid shape can be given a motion: it can
move to a new position over a set time, swing back and forth, or float. The mesh stretches to follow
the shape while the run goes on.

Here a sluice gate holds back water 0.5 m deep, with a 0.1 m gap under it. A tenth of a second into
the run the gate starts to lift, and half a second later the gap has doubled.
""",
    learn=[
        "give a shape a motion: how far, from when, for how long",
        "follow the motion while the run goes on",
        "know what a stretching mesh can and cannot do",
    ],
    steps=[
        *from_example("gate", "gate", "Lifting sluice gate"),
        Step(
            title="The gate and its motion",
            text="""
The gate is a box 0.1 m thick whose lower edge is 0.1 m above the bed. At the bottom of its settings
is **Motion**. *Moves to a new position* asks for three things: how far the shape ends up from where
it is drawn, when it starts, and how long the move takes. It moves at a steady speed in between.
""",
            screen="Geometry",
            before=create("gate", "gate"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'gate')", "The shape **gate**. The list notes that it moves."),
                Mark("w.geometry_panel.box_min", "The lower edge of the gate is at z = `0.1` m."),
                Mark("w.geometry_panel.motion_kind", "**Motion**: *Moves to a new position*."),
                Mark("w.geometry_panel.motion_displacement", "**Moves by**: `0`, `0`, `0.1`, so 0.1 m straight up."),
                Mark("w.geometry_panel.motion_start", "**Starts at** `0.1` s and **Takes** `0.5` s."),
            ],
        ),
        Step(
            title="The channel",
            text="""
The channel is 3 m long and 1 m high, modelled as a slice two cells thick. Both ends are closed
walls, the top is open to the air.
""",
            screen="Mesh",
            marks=[
                Mark("w.mesh_panel.base_max", "**Corner (max)**: `3`, `0.1`, `1`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `60`, `2`, `20`, which makes 5 cm cubes."),
                Mark("w.mesh_panel._face_names['zMin']", "`bed` is a wall and `atmosphere` an opening."),
                MESH_BUTTON,
            ],
        ),
        Step(
            title="Water behind the gate",
            text="""
The flow type is *Free surface: water and air*; a shape can only move in a run in time, and all
free-surface runs are. Scroll down to **Water and air**: the water starts on the upstream side only,
one box from the end wall to the face of the gate, 0.5 m deep.
""",
            screen="Physics",
            before=lambda d: d.mesh(),
            marks=[
                Mark("w.physics_panel.water_table", "One box of water: from `0, 0, 0` to `1.5, 0.1, 0.5`."),
            ],
        ),
        Step(
            title="Run for two seconds",
            text="Nothing is special about the run settings: a moving shape needs no extra choices here.",
            screen="Run",
            marks=[
                Mark("w.run_panel.end_time", "**End time**: `2` s."),
                Mark("w.run_panel.write_interval", "**Save every**: `0.1` s."),
                Mark("w.run_panel.processors", "**Processor cores**: `2`."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="Follow the gate",
            text="""
The **Motion** tab plots how far each moving shape has travelled. The gate waits for a tenth of a
second, rises steadily, and stops 0.1 m higher.
""",
            screen="Run",
            tab="Motion",
            before=lambda d: d.run(until=0.4),
            marks=[
                Mark("tab('Motion')", "Open the **Motion** tab.", "top"),
                Mark("w.motion_label", "Where the gate is now."),
            ],
        ),
        Step(
            title="The water runs out",
            text="""
In the **Results** step, look at the moment just after the gate has stopped, at 0.7 s. The water is
shooting through the gap, twice as high now as at the start, and running down the channel. Step
through the saved times and you can see the gate itself rise in the 3D view.
""",
            screen="Results",
            before=show_water,
            cover=True,
            marks=[
                Mark("w.results_panel.time", "**Saved time**: `0.7`."),
                Mark("w.results_panel.mode", "**Show**: *Water surface*, coloured by `U`, the speed."),
            ],
        ),
        Step(
            title="What a moving mesh can and cannot do",
            text="""
The mesh is not rebuilt when a shape moves. The cells around the shape are stretched and squeezed to
follow it, and their number stays the same. That is quick and robust, but it sets limits:

- Keep a movement well below the gap between the shape and the nearest wall.
- A gate can open further or close part of the way. It **cannot shut completely**, because the cells
  under it would be squeezed to nothing. Leave a small gap.
- Moving shapes cannot be combined with mesh refinement at the water surface.
""",
        ),
        Step(
            title="Try it yourself",
            text="""
- Lift the gate more slowly (**Takes** `1.5` s) and compare the surge downstream.
- Lower it instead: **Moves by** `0`, `0`, `-0.05` halves the gap.
- Choose *Swings back and forth* with an amplitude of `0.05`, `0`, `0` and a period of `1` s to turn
  the gate into a wave paddle.
""",
        ),
    ],
)
