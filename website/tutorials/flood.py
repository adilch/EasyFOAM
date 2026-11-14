"""A flood through a bend: an inflow hydrograph, a rising tailwater, the long section and where the bed would move."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.channel import channel
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON

FLOOD = [[0, 0.2], [10, 0.2], [35, 0.45], [60, 0.45]]  # m³/s: rises over 25 s and stays at its peak
TAILWATER = [[0, 0.35], [20, 0.35], [50, 0.42], [60, 0.42]]  # m: the river downstream rises as the flood arrives


def open_channel(d):
    d.create("empty", "flood")
    d.open_channel(channel())


def flood_table(d):
    d.build_channel()
    d.boundary("inlet")
    d.open_series("flow_series", FLOOD)


def tailwater_table(d):
    d.accept_series("flow_series")
    d.boundary("outlet")
    d.open_series("level_series", TAILWATER)


def rough(d):
    d.accept_series("level_series")
    for wall in ("banks", "bed"):
        d.boundary(wall)
        d.set(d.w.boundary_panel.roughness, "manning")
        d.set(d.w.boundary_panel.manning, 0.025)


def both_ends(d):
    d.go("Run")
    d.set(d.w.run_panel.flow_monitors, "inlet, outlet")


def ready_to_run(d):
    panel = d.w.run_panel
    d.set(panel.end_time, 60.0)
    d.set(panel.processors, 4)
    d.mesh()


def long_section(d):
    d.go("Results")
    d.w.hydraulics("long")
    d.settle(0.5)


def bed_shear(d):
    d.set(d.w.results_panel.d50, 8.0)
    d.w.hydraulics("shear")
    d.wait()
    d.view("-z")  # from above


TUTORIAL = Tutorial(
    slug="flood",
    title="A flood through a bend",
    summary="Send a flood hydrograph down a channel while the river downstream rises, follow the water round the bend and see where the bed would start to move.",
    minutes=25,
    level="Intermediate",
    topics=["Free surface", "Open channels", "Time series", "Sediment"],
    run_time="about a minute for the mesh and two or three minutes for the run, on four cores.",
    intro="""
Rivers are rarely steady. A flood arrives as a hydrograph, a discharge that rises and falls, and the
river downstream rises with it, which backs the water up. This tutorial gives the inlet of a channel
a flood hydrograph and its outlet a tailwater that rises in time, both as tables of time and value.
At the peak it looks at the water round the bend and at the shear stress on the bed: where it exceeds
what the bed material can take, the bed would start to move.

It uses the channel of the *Build a channel with a bend* tutorial: a trapezoid with a 1 m bed and a
60° bend.
""",
    learn=[
        "give an inlet a flood hydrograph and an outlet a tailwater that changes in time",
        "compare the discharge coming in and going out",
        "draw the long section at the peak of the flood",
        "work out the bed shear stress and where a gravel bed would move",
    ],
    steps=[
        Step(
            title="An empty project",
            text="Start a new, empty project and call it `flood`.",
            screen="Dialog",
            before=lambda d: d.show_dialog("empty", "flood"),
            marks=[Mark("dlg.name", "Type `flood`."), Mark("dlg.ok", "Click **Create project**.")],
        ),
        Step(
            title="The channel",
            text="""
In **Geometry**, press **Channel…** and build the same channel as in the *Build a channel with a
bend* tutorial: a trapezoid with a 1 m bed and 0.5 m banks at 1 to 1, a bed slope of 0.002, 6 m
straight, a 60° bend of 8 m radius and 6 m straight, with water 0.35 m deep at the start.
""",
            screen="Dialog",
            before=open_channel,
            marks=[
                Mark("dlg.pieces", "The centreline: straight `6`, a bend of radius `8` turning `60`°, straight `6`."),
                Mark("dlg.ok", "Press **Build the channel**."),
            ],
        ),
        Step(
            title="A flood comes down",
            text="""
In **Boundaries**, pick **inlet** and press **Flow changes in time…**. Type the hydrograph as a
table of times and discharges: **0.2 m³/s** for the first 10 seconds, rising to **0.45 m³/s** at
35 s and staying there. Between the rows the discharge changes in a straight line. You can also
paste two columns from a spreadsheet, or start from a ready-made flood shape.
""",
            screen="Dialog",
            before=flood_table,
            marks=[
                Mark("dlg.table", "Times and discharges: `0` `0.2`, `10` `0.2`, `35` `0.45`, `60` `0.45`."),
                Mark("dlg.presets", "**Start from…** offers a flood hydrograph, steps or a slow rise."),
                Mark("dlg.ok", "Press **Use this series**."),
            ],
        ),
        Step(
            title="The river downstream rises",
            text="""
Pick **outlet** and press **Level changes in time…**. The river downstream rises from **0.35 m** to
**0.42 m** between 20 and 50 seconds, as the flood reaches it.
""",
            screen="Dialog",
            before=tailwater_table,
            marks=[
                Mark("dlg.table", "Times and levels: `0` `0.35`, `20` `0.35`, `50` `0.42`, `60` `0.42`."),
                Mark("dlg.ok", "Press **Use this series**."),
            ],
        ),
        Step(
            title="Rough bed and banks",
            text="Give **bed** and **banks** a Manning's n of **0.025**: an earth channel.",
            screen="Boundaries",
            before=rough,
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'bed')", "The boundary **bed** (do the same for **banks**)."),
                Mark("w.boundary_panel.roughness", "**Roughness**: *Manning's n*."),
                Mark("w.boundary_panel.manning", "**Manning's n**: `0.025`."),
            ],
        ),
        Step(
            title="Discharge at both ends",
            text="In the **Run** step, record the discharge through both ends of the channel.",
            screen="Run",
            before=both_ends,
            marks=[Mark("w.run_panel.flow_monitors", "**Discharge through**: `inlet, outlet`.")],
        ),
        Step(
            title="Run a minute",
            text="Make the mesh and run a minute of the flood on four cores.",
            screen="Run",
            before=ready_to_run,
            marks=[MESH_BUTTON, Mark("w.run_panel.end_time", "**End time**: `60` s."), RUN_BUTTON],
        ),
        Step(
            title="The flood passes",
            text="""
The **Discharge** tab shows the water coming in (negative: into the channel) and going out. The
inflow follows the hydrograph exactly. The water in the channel starts still, so for the first
seconds little leaves while the flow gets going; after that the outflow follows the flood, a little
below the inflow while the water in the channel rises with it.
""",
            screen="Run",
            tab="Discharge",
            before=lambda d: d.run(),
            marks=[Mark("tab('Discharge')", "Open the **Discharge** tab.", "top")],
        ),
        Step(
            title="At the peak",
            text="""
In **Results**, press **Long section**: it is drawn for the latest saved time, at the peak of the
flood. The stations follow the curved centreline; the water surface and the energy line fall gently
round the bend.
""",
            screen="Results",
            tab="Hydraulics",
            before=long_section,
            marks=[
                Mark("w.results_panel.long_button", "Press **Long section**."),
                Mark("w.results_panel.hydraulics_info", "Discharge, depths and the Froude number at the peak."),
            ],
        ),
        Step(
            title="Where the bed would move",
            text="""
Give the size of the bed material, **8 mm** gravel, and press **Bed shear stress and sediment
movement**. OpenFOAM works out the shear stress the water puts on the walls and EasyFOAM colours the
bed with it, seen from above. The text gives the largest stress and the stress at which 8 mm gravel
starts to move (Shields). Choose **sedimentMobility** under **Quantity**: above 1, the bed would move.
""",
            screen="Results",
            before=bed_shear,
            cover=True,
            marks=[
                Mark("w.results_panel.d50", "**Bed material d50**: `8` mm."),
                Mark("w.results_panel.shear_button", "Press **Bed shear stress and sediment movement**."),
                Mark("w.results_panel.info", "The largest shear stress, and when the gravel moves."),
            ],
        ),
    ],
)
