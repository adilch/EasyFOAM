"""A river reach from a survey: bring in the ground from an ESRI ASCII grid and let the river run over it."""

from website.files import VALLEY_ANGLE, VALLEY_ORIGIN, valley_asc
from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON

SETTINGS = {"origin": VALLEY_ORIGIN, "angle": VALLEY_ANGLE, "region": (5, -30, 155, 30), "spacing": 1.0,
            "cell": 1.0, "water": 99.3, "top": 101.5, "discharge": 4.0}  # fmt: skip


def survey(d):
    path = d.work / "valley.asc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(valley_asc())
    return path


def open_dialog(d):
    d.create("empty", "reach")
    d.open_terrain(survey(d), **SETTINGS)


def ground_in(d):
    open_dialog(d)
    d.use_terrain()
    run = d.w.project.run
    run.end_time, run.write_interval, run.processors = 60.0, 10.0, 8
    d.w._load_panels()


def rough_ground(d):
    d.boundary("terrain")
    d.set(d.w.boundary_panel.roughness, "manning")
    d.set(d.w.boundary_panel.manning, 0.035)


def water_surface(d):
    d.run()
    d.go("Results")
    d.results("U", "water")
    d.view("iso")


def long_section(d):
    d.w.hydraulics("long")
    d.settle(0.5)


TUTORIAL = Tutorial(
    slug="reach",
    title="A river reach from a survey",
    summary="Bring in the ground of a valley from an ESRI ASCII grid, turn it so the river runs along x, and send a flow down its meandering channel.",
    minutes=25,
    level="Intermediate",
    topics=["Free surface", "Rivers", "Terrain", "Hydraulic results"],
    run_time="about a minute for the mesh and a minute for the run, on eight cores.",
    intro="""
River models start from the ground: a survey, a lidar grid or a terrain model. EasyFOAM reads XYZ
points, ESRI ASCII grids, GeoTIFF elevation rasters and LandXML surfaces, moves them to small local
coordinates, turns them so the river runs along x and closes the ground into a solid that the mesh
is cut from. The water and the air are above it.

In this tutorial you use a survey of a small valley, 150 m long, with a meandering channel about
1.2 m deep. Download it here: [valley.asc](files/valley.asc). Its coordinates are survey
coordinates, half a million metres east and four million north.
""",
    learn=[
        "read a survey file and see what it holds",
        "choose the local origin, the direction of the river and the part to model",
        "give the ground a Manning roughness",
        "run the flow and draw the long section of the reach",
    ],
    steps=[
        Step(
            title="An empty project",
            text="Start a new, empty project and call it `reach`.",
            screen="Dialog",
            before=lambda d: d.show_dialog("empty", "reach"),
            marks=[Mark("dlg.name", "Type `reach`."), Mark("dlg.ok", "Click **Create project**.")],
        ),
        Step(
            title="Bring in the ground",
            text="In the **Geometry** step, press **Terrain…** and choose the file **valley.asc**.",
            screen="Geometry",
            before=lambda d: d.create("empty", "reach"),
            marks=[Mark("w.geometry_panel.terrain_button", "Press **Terrain…**.")],
        ),
        Step(
            title="Where and what to model",
            text="""
The dialog says what the file holds: a 1 m grid, ground from 98.2 to 102 m. Put the local origin
where the valley starts, at **512000**, **4181000**, and say the river flows **30°** north of east:
the survey is turned so that it runs along x. Model **5 to 155 m** along it and **30 m** to each
side. The water starts at **99.3 m**, which fills the channel, and **4 m³/s** come in.
""",
            screen="Dialog",
            before=open_dialog,
            marks=[
                Mark("dlg.origin_x", "**Local origin**: `512000`, `4181000`."),
                Mark("dlg.angle", "**River flows towards**: `30` degrees."),
                Mark("dlg.x_from", "**Region**: x `5` to `155`, y `-30` to `30`."),
                Mark("dlg.water", "**Initial water level**: `99.3` m."),
                Mark("dlg.discharge", "**Discharge**: `4` m³/s."),
                Mark("dlg.ok", "Press **Use this ground**."),
            ],
        ),
        Step(
            title="The ground",
            text="""
The ground is now a shape called **terrain**, and the case is set up: the base mesh sits on the
ground with its top at 101.5 m, the inlet faces -x, the outlet +x holds the water at 99.3 m, and
the sides let the water slide.
""",
            screen="Geometry",
            before=ground_in,
            cover=True,
            marks=[Mark("item(w.geometry_panel.shape_list, 'terrain')", "The shape **terrain**: the ground, closed into a solid.")],
        ),
        Step(
            title="A rough bed",
            text="A natural channel with some stones and weeds: give the ground a Manning's n of **0.035**.",
            screen="Boundaries",
            before=rough_ground,
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'terrain')", "The boundary **terrain**."),
                Mark("w.boundary_panel.roughness", "**Roughness**: *Manning's n*."),
                Mark("w.boundary_panel.manning", "**Manning's n**: `0.035`."),
            ],
        ),
        Step(
            title="Mesh and run",
            text="""
snappyHexMesh cuts the ground out of the base mesh and refines once at it. Then run a minute of
flow on eight cores: long enough for the water to run the length of the reach.
""",
            screen="Run",
            before=lambda d: d.mesh(),
            marks=[
                MESH_BUTTON,
                Mark("w.run_panel.end_time", "**End time**: `60` s."),
                Mark("w.run_panel.processors", "**Processor cores**: `8`."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="The river",
            text="""
The **Results** step shows the water surface coloured by speed: the water winds round the meanders,
faster on the outside of the bends.
""",
            screen="Results",
            before=water_surface,
            marks=[Mark("w.results_panel.mode", "**Show**: *Water surface*."), Mark("w.results_panel.field", "**Quantity**: `U`.")],
        ),
        Step(
            title="Long section of the reach",
            text="""
**Long section** integrates the water across the valley at stations along x. The water surface
falls along the reach, the discharge settles towards the 4 m³/s let in, and the Froude number says
the flow is slow and deep (subcritical).
""",
            screen="Results",
            tab="Hydraulics",
            before=long_section,
            marks=[
                Mark("w.results_panel.long_button", "Press **Long section**."),
                Mark("w.results_panel.hydraulics_info", "Discharge, depth and Froude number along the reach."),
            ],
        ),
    ],
)
