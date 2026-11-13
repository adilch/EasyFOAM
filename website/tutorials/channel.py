"""Build a channel in the program: a trapezoidal section, a bed slope and a bend; mesh, run, long section."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON


def channel():
    from easyfoam.model import Channel, ChannelSegment

    return Channel(
        section="trapezoidal", bottom_width=1.0, depth=0.5, side_slope=1.0, slope=0.002, freeboard=0.15,
        cell_size=0.1, water_depth=0.35,
        segments=[ChannelSegment("straight", length=6), ChannelSegment("bend", radius=8, angle=60),
                  ChannelSegment("straight", length=6)],
    )  # fmt: skip


def built(d):
    d.create("empty", "channel")
    d.open_channel(channel())
    d.build_channel()
    d.w.project.boundaries["inlet"].flow_rate = 0.2
    d.w.project.run.end_time, d.w.project.run.processors = 10.0, 4
    d.w._load_panels()


def long_section(d):
    d.go("Results")
    d.w.hydraulics("long")
    d.settle(0.5)


TUTORIAL = Tutorial(
    slug="channel",
    title="Build a channel with a bend",
    summary="Draw a trapezoidal channel with a bed slope and a 60° bend, let EasyFOAM mesh it to fit, and follow the water round the bend in a long section.",
    minutes=20,
    level="Beginner",
    topics=["Free surface", "Open channels", "Hydraulic results"],
    run_time="a few seconds for the mesh and about a minute for the run, on four cores.",
    intro="""
Many questions in open-channel hydraulics start with a channel of a known shape: a trapezoid cut
into the ground, falling gently, with a bend in it. Instead of drawing it in a CAD program, you can
give EasyFOAM the cross-section, the slope and the centreline, and it builds the channel and a mesh
that follows its banks and bends.
""",
    learn=[
        "build a channel from its cross-section, bed slope and centreline",
        "see the starting water and the boundaries the builder sets up",
        "give the bed a Manning roughness",
        "draw a long section along a curved centreline",
    ],
    steps=[
        Step(
            title="An empty project",
            text="Start a new, empty project and call it `channel`.",
            screen="Dialog",
            before=lambda d: d.show_dialog("empty", "channel"),
            marks=[Mark("dlg.name", "Type `channel`."), Mark("dlg.ok", "Click **Create project**.")],
        ),
        Step(
            title="Open the channel builder",
            text="In the **Geometry** step, press **Channel…**.",
            screen="Geometry",
            before=lambda d: d.create("empty", "channel"),
            marks=[Mark("w.geometry_panel.channel_button", "Press **Channel…**.")],
        ),
        Step(
            title="Cross-section and centreline",
            text="""
A trapezoid with a **1 m** bed, **0.5 m** banks leaning out at 1 to 1, and a bed slope of **0.002**.
The centreline runs **6 m** straight, turns **60°** to the left round a bend of **8 m** radius, and
runs another **6 m**. The water starts **0.35 m** deep. The preview draws the section (heights
exaggerated) and the plan.
""",
            screen="Dialog",
            before=lambda d: d.open_channel(channel()),
            marks=[
                Mark("dlg.section", "**Cross-section**: *Trapezoidal*."),
                Mark("dlg.slope", "**Bed slope**: `0.002`."),
                Mark("dlg.water_depth", "**Initial water depth**: `0.35` m."),
                Mark("dlg.pieces", "The centreline: straight `6`, a bend of radius `8` turning `60`°, straight `6`."),
                Mark("dlg.ok", "Press **Build the channel**."),
            ],
        ),
        Step(
            title="The channel",
            text="""
EasyFOAM builds the channel and sets up the case: free-surface flow, an inlet that lets in the
uniform-flow discharge for the starting depth, an outlet that holds that depth, and walls named
**bed** and **banks**. The 3D view shows the starting water in the channel.
""",
            screen="Geometry",
            before=built,
            cover=True,
            marks=[Mark("w.geometry_panel.channel_summary", "What was built: length, slope and the number of cells.")],
        ),
        Step(
            title="Inflow and roughness",
            text="""
In **Boundaries**, pick **inlet** and set its flow rate to **0.2 m³/s**. Then pick **bed** and give
it a Manning's n of **0.025**, a clean earth channel.
""",
            screen="Boundaries",
            before=lambda d: (d.boundary("bed"), d.set(d.w.boundary_panel.roughness, "manning"),
                              d.set(d.w.boundary_panel.manning, 0.025)),  # fmt: skip
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'bed')", "The boundary **bed**."),
                Mark("w.boundary_panel.roughness", "**Roughness**: *Manning's n*."),
                Mark("w.boundary_panel.manning", "**Manning's n**: `0.025`."),
            ],
        ),
        Step(
            title="Mesh and run",
            text="""
The mesh is made by blockMesh alone, fitted to the channel: no cells are wasted outside it. Then run
for **10 s** on four cores.
""",
            screen="Mesh",
            before=lambda d: d.mesh(),
            marks=[Mark("w.mesh_panel.channel_note", "The base mesh is not used: the mesh follows the channel."), MESH_BUTTON, RUN_BUTTON],
        ),
        Step(
            title="Round the bend",
            text="""
After the run, press **Long section** in **Results**. The stations follow the curved centreline, so
the long section runs round the bend. The bed falls about 4 cm over the 20.4 m from inlet to outlet.
""",
            screen="Results",
            tab="Hydraulics",
            before=lambda d: (d.run(), long_section(d)),
            marks=[
                Mark("w.results_panel.long_button", "Press **Long section**."),
                Mark("w.results_panel.hydraulics_info", "Discharge, depth and Froude number along the channel."),
            ],
        ),
    ],
)
