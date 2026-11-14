"""The rating curve of a weir: step the inflow through several discharges, read off head and weir coefficient."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def set_up_sweep(d):
    panel = d.w.run_panel
    d.set(panel.rating_discharges, "0.025, 0.05, 0.075")
    d.set(panel.rating_hold, 20.0)
    panel.rating_button.click()
    d.settle(0.5)


def rating_curve(d):
    d.go("Results")
    d.w.hydraulics("rating")
    d.settle(0.5)


TUTORIAL = Tutorial(
    slug="rating",
    title="Rating curve of a weir",
    summary="Step the inflow through three discharges in one run and read off the head over the weir, its weir coefficient and whether each level settled.",
    minutes=25,
    level="Intermediate",
    topics=["Free surface", "Hydraulic structures", "Hydraulic results"],
    run_time="about twenty minutes on four cores.",
    intro="""
A rating curve tells how high the water stands for each discharge: the relation a weir or a gauging
station is used for. Measuring one point at a time means one run per discharge. Here a single run
steps the inflow through several discharges, holds each one until the level settles, and EasyFOAM
reads off the head over the crest at a gauge for each step.

This tutorial uses the weir of the earlier *Flow over a weir* tutorial: 0.5 m wide, a crest 0.51 m
above the bed, with a gauge in the reservoir.
""",
    learn=[
        "set up a rating-curve run from a list of discharges",
        "see the inflow step up as a time table at the inlet",
        "read the head, the weir coefficient C and Cd for each discharge",
        "tell from the run whether each level had settled",
    ],
    steps=[
        *from_example("weir", "rating", "Flow over a weir"),
        Step(
            title="The gauge",
            text="""
The rating curve is read at a gauge: a probe point in the reservoir, well upstream of the crest,
where the water is calm. The weir example already has one.
""",
            screen="Run",
            before=create("weir", "rating"),
            marks=[Mark("w.run_panel.probe_table", "Probe **1** at `1.2`, `0.25`, `0.3`: the gauge in the reservoir.")],
        ),
        Step(
            title="Set up the sweep",
            text="""
Under **Rating curve** give the discharges, smallest first, and how long to hold each. Twenty
seconds is enough here for the reservoir to fill to each new level and for the outflow to catch up.
The crest is found by itself: the top of the highest structure, 0.51 m.
""",
            screen="Run",
            before=set_up_sweep,
            marks=[
                Mark("w.run_panel.rating_discharges", "**Discharges**: `0.025, 0.05, 0.075` m³/s."),
                Mark("w.run_panel.rating_hold", "**Hold each for**: `20` s."),
                Mark("w.run_panel.rating_gauge", "**Gauge**: probe `1`."),
                Mark("w.run_panel.rating_button", "Press **Set up the rating-curve run**."),
                Mark("w.run_panel.rating_status", "What was done: the run now ends at 60 s."),
            ],
        ),
        Step(
            title="The inflow steps up",
            text="""
In **Boundaries**, the inlet now follows a time table: each discharge held for 20 seconds, with a
short ramp between them. **Flow changes in time…** opens the table if you want to change it.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("inlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "The boundary **inlet**."),
                Mark("w.boundary_panel.flow_series_hint", "The inflow: three steps, from 0.025 to 0.075 m³/s."),
                Mark("w.boundary_panel.flow_series_button", "**Flow changes in time…** opens the table."),
            ],
        ),
        Step(
            title="Mesh and run",
            text="Make the mesh and run the 60 seconds on four cores.",
            screen="Run",
            before=lambda d: d.mesh(),
            marks=[MESH_BUTTON, Mark("w.run_panel.end_time", "**End time**: `60` s, set by the sweep."), RUN_BUTTON],
        ),
        Step(
            title="The level steps up",
            text="""
The **Probes** tab shows the water at the gauge rising with each step of the inflow and levelling
off before the next one: that level, over the crest, is the head for that discharge.
""",
            screen="Run",
            tab="Probes",
            before=lambda d: d.run(),
            marks=[Mark("tab('Probes')", "Open the **Probes** tab: the water depth at the gauge over time.", "top")],
        ),
        Step(
            title="The rating curve",
            text="""
In **Results**, press **Rating curve**. For each discharge EasyFOAM averages the level at the gauge
over the last part of its hold and gives the head over the crest, the weir coefficient
C = Q / (B H^1.5) and the discharge coefficient Cd. The head rises from about **0.10 m** to
**0.20 m**, and C from about **1.5 to 1.65**, a little below the 1.70 of an ideal broad-crested
weir: a square-edged crest loses some energy. The first point is marked *not settled*: at the start
the channel below the weir was still filling, and 20 seconds were not quite enough.
""",
            screen="Results",
            tab="Hydraulics",
            before=rating_curve,
            cover=True,
            marks=[
                Mark("w.results_panel.rating_button", "Press **Rating curve**."),
                Mark("w.results_panel.hydraulics_info", "Head, C and Cd for each discharge."),
                Mark("w.results_panel.export_button", "**Save the table…** writes them to a CSV file."),
            ],
            tip="A point marked *not settled* needs a longer hold: the level was still moving when the next discharge came.",
        ),
    ],
)
