"""A hydraulic jump below a sluice gate: long section, the jump against Bélanger, the force on the gate."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def long_section(d):
    d.run()
    d.go("Results")
    d.set(d.w.results_panel.average, 5)
    d.w.hydraulics("long")
    d.settle(0.5)


def gate_pressure(d):
    d.set(d.w.results_panel.structure, "gate")
    d.w.hydraulics("pressure")
    d.settle(0.5)


def gate_loads(d):
    d.w.hydraulics("loads")
    d.settle(0.5)


TUTORIAL = Tutorial(
    slug="jump",
    title="Hydraulic jump: long section and loads",
    summary="Water shoots under a sluice gate and jumps back up. Find the jump, check it against Bélanger and work out the force on the gate.",
    minutes=30,
    level="Intermediate",
    topics=["Free surface", "Hydraulic structures", "Hydraulic results", "Checked against theory"],
    run_time="about ten minutes on four cores.",
    intro="""
Below a sluice gate the water leaves in a fast, shallow jet. Downstream, the tailwater is deep and
slow. Where the two meet, the jet jumps up in a turbulent roller: a hydraulic jump, which destroys a
large part of the jet's energy. Its height follows from the momentum balance (Bélanger's equation).

In this tutorial you run the jump example, draw its long section, let EasyFOAM find the jump and
compare it with Bélanger, then read off the pressure on the gate and the force that pushes on it.
""",
    learn=[
        "draw a long section: water level, energy line and Froude number along a channel",
        "average an oscillating flow over several saved times",
        "find a hydraulic jump and compare its sequent depth and energy loss with theory",
        "work out the pressure on a structure and the force and moment it carries",
    ],
    steps=[
        *from_example("jump", "jump", "Hydraulic jump"),
        Step(
            title="The gate",
            text="""
The channel is a thin slice, 6 m long and 0.8 m high, of a wide channel. The gate is a box from the
top of the channel down to **0.1 m above the bed**: the opening the water shoots through.
""",
            screen="Geometry",
            before=create("jump", "jump"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'gate')", "The shape **gate**."),
                Mark("w.geometry_panel.box_min", "**Corner (min)**: `1`, `-1`, `0.1`. The last number is the gate opening."),
            ],
        ),
        Step(
            title="Discharge and tailwater",
            text="""
The inlet lets in **0.0103 m³/s** through the 5 cm slice, which is 0.206 m³/s per metre width. The
outlet holds the tailwater at **0.32 m**: that is what pushes the jump back towards the gate.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("outlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'outlet')", "The boundary **outlet**."),
                Mark("w.boundary_panel.level", "**Tailwater level**: `0.32` m."),
            ],
            tip="The tailwater can also change in time: **Level changes in time…** takes a table of times and levels.",
        ),
        Step(
            title="Mesh and run",
            text="""
Make the mesh, then run. Fifteen seconds of simulated time are enough for the jump to form and
settle in front of the gate.
""",
            screen="Run",
            before=lambda d: d.mesh(),
            marks=[
                MESH_BUTTON,
                Mark("w.run_panel.end_time", "**End time**: `15` s."),
                Mark("w.run_panel.processors", "**Processor cores**: `4`."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="The long section",
            text="""
When the run has finished, go to **Results** and press **Long section**. EasyFOAM integrates the
water across the channel at stations along it and draws the bed, the water surface and the energy
line, with the Froude number below. A jump oscillates, so average over the last **5** saved times.

The text lists the jump it found: the depth and Froude number of the jet before it, the depth after
it, and both next to Bélanger's values. On this coarse mesh they agree within about 5 to 10 %;
averaging over a longer run brings them closer.
""",
            screen="Results",
            tab="Hydraulics",
            before=long_section,
            cover=True,
            marks=[
                Mark("w.results_panel.average", "**Average over**: `5` saved times."),
                Mark("w.results_panel.long_button", "Press **Long section**."),
                Mark("w.results_panel.hydraulics_info", "The jump: its sequent depth and energy loss next to Bélanger's (within about 5 to 10 %)."),
            ],
        ),
        Step(
            title="Pressure on the gate",
            text="""
Pick the gate under **Structure** and press **Pressure along it**. The plot shows the pressure head
down the upstream face of the gate: zero in the air at the top, rising with depth in the reservoir.
""",
            screen="Results",
            tab="Hydraulics",
            before=gate_pressure,
            marks=[
                Mark("w.results_panel.structure", "**Structure**: `gate`."),
                Mark("w.results_panel.pressure_button", "Press **Pressure along it**."),
            ],
        ),
        Step(
            title="The force on the gate",
            text="""
**Loads** adds up the pressure over the gate: the force on it, per metre width as the gate spans the
channel, and the overturning moment about its downstream toe. For this flow the momentum balance
between the reservoir and the jet gives about **1290 N per metre**; EasyFOAM finds about 1230.
""",
            screen="Results",
            tab="Hydraulics",
            before=gate_loads,
            marks=[
                Mark("w.results_panel.loads_button", "Press **Loads**."),
                Mark("w.results_panel.hydraulics_info", "Force and moment, in total and per metre width."),
                Mark("w.results_panel.export_button", "**Save table…** writes the numbers to a CSV file."),
            ],
        ),
    ],
)
