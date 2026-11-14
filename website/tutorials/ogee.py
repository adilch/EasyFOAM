"""An ogee spillway crest made from its design head: its design discharge, the head it runs at, and the pressure on it."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def open_design(d):
    d.shape("ogee")
    d.open_structure(d.w.project.shapes[0].structure)


def long_section(d):
    d.run()
    d.go("Results")
    d.set(d.w.results_panel.average, 6)
    d.w.hydraulics("long")
    d.settle(0.5)


def crest_pressure(d):
    d.set(d.w.results_panel.structure, "ogee")
    d.w.hydraulics("pressure")
    d.settle(0.5)


TUTORIAL = Tutorial(
    slug="ogee",
    title="Ogee spillway crest from its design head",
    summary="Make a spillway crest from its design head, let EasyFOAM give its design discharge, and check that the crest runs at that head with about atmospheric pressure on it.",
    minutes=25,
    level="Intermediate",
    topics=["Free surface", "Hydraulic structures", "Checked against theory"],
    run_time="about twenty minutes on two cores.",
    intro="""
An ogee crest is shaped like the underside of the sheet of water that would spring clear of a sharp
crest at the *design head* Hd. At that head the water follows the crest closely, the pressure on it
is about atmospheric, and the crest passes Q = C·W·Hd^1.5 with C close to **2.18** (in metres and
seconds) when the crest stands well above the bed. The standard shape (the WES crest of the US Army
Corps of Engineers) follows from Hd alone: three circular arcs upstream of the apex and the curve
x^1.85 = 2 Hd^0.85 y downstream of it, down to the face of the spillway.

In this tutorial you open an example in which EasyFOAM has made such a crest from a design head of
0.1 m, look at its design, and run the design discharge over it.
""",
    learn=[
        "make a structure from its design values and see it drawn as you type",
        "read the design discharge EasyFOAM works out for it",
        "check the head over the crest with a long section",
        "look at the pressure along the crest",
    ],
    steps=[
        *from_example("ogee", "ogee", "Ogee spillway crest"),
        Step(
            title="The crest",
            text="""
The channel is a thin slice, 2 cm wide, of a wide spillway: 3.5 m long and 0.8 m high, with
frictionless sides. The crest is a **structure**, made from its design values; the summary under it
says what it is and the discharge it is made for.
""",
            screen="Geometry",
            before=create("ogee", "ogee"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'ogee')", "The shape **ogee**, an ogee crest."),
                Mark("w.geometry_panel.design_summary", "Where it stands and its design discharge."),
                Mark("w.geometry_panel.design_button", "**Change the design…** opens its design."),
            ],
            tip="**Structure** above the list makes a new one: an ogee crest, a stepped spillway, a labyrinth weir, a stilling basin, a culvert or a fishway.",
        ),
        Step(
            title="Its design",
            text="""
The design head is **0.1 m** and the crest stands **0.4 m** above the bed, so P/Hd = 4: the water
arrives slowly enough not to change the coefficient. Below the curve the face slopes at **0.75**
horizontal to 1 vertical and turns into the bed along a curve of **0.1 m** radius. The side view
draws the crest with the design head as a dashed line; the lines below it give the design
discharge, **1.38 litres a second** through the slice (0.069 m³/s per metre).
""",
            screen="Dialog",
            before=open_design,
            marks=[
                Mark("dlg.kind", "**Structure**: *Ogee crest*."),
                Mark("dlg.inputs['design_head']", "**Design head Hd**: `0.1` m."),
                Mark("dlg.inputs['height']", "**Crest height P**: `0.4` m."),
                Mark("dlg.preview", "The crest from the side and from above.", "centre"),
                Mark("dlg.info", "Its design discharge, and P/Hd.", "left"),
            ],
            tip="Change a value and the drawing and the figures follow at once; **Use this structure** keeps it.",
        ),
        Step(
            title="The design discharge",
            text="""
The inlet lets in exactly that discharge: **0.00137875 m³/s**. The reservoir starts filled to the
design head, so the run settles quickly; the outlet lets the water leave freely.
""",
            screen="Boundaries",
            before=lambda d: (d.close_dialog(), d.boundary("inlet")),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "The boundary **inlet**."),
                Mark("w.boundary_panel.flow_rate", "**Flow rate**: `0.00137875` m³/s, the design discharge."),
            ],
        ),
        Step(
            title="Mesh and run",
            text="""
The crest is cut out of the mesh by snappyHexMesh, with cells half the size along its surface. Run
the ten seconds on two cores.
""",
            screen="Run",
            before=lambda d: d.mesh(),
            marks=[MESH_BUTTON, Mark("w.run_panel.end_time", "**End time**: `10` s."), RUN_BUTTON],
        ),
        Step(
            title="The head over the crest",
            text="""
In **Results**, average the last **6** saved times and press **Long section**. Upstream of the crest
the water stands **0.50 m** above the bed: a head of about **0.10 m** over the crest, the design
head it was made for. Over the crest the water speeds up and passes critical depth, then runs down
the face, fast and shallow.
""",
            screen="Results",
            tab="Hydraulics",
            before=long_section,
            cover=True,
            marks=[
                Mark("w.results_panel.average", "**Average over**: `6` saved times."),
                Mark("w.results_panel.long_button", "Press **Long section**."),
                Mark("w.results_panel.hydraulics_info", "Discharge and depth along the spillway."),
            ],
        ),
        Step(
            title="Pressure on the crest",
            text="""
Pick **ogee** under **Structure** and press **Pressure along it**. Up the upstream face the pressure
grows with the depth of water; over the crest it falls to about **zero**, atmospheric, as it should
at the design head. Run a larger discharge and it falls below atmospheric over the crest: the reason
a crest is not run far above its design head.
""",
            screen="Results",
            tab="Hydraulics",
            before=crest_pressure,
            marks=[
                Mark("w.results_panel.structure", "**Structure**: `ogee`."),
                Mark("w.results_panel.pressure_button", "Press **Pressure along it**."),
            ],
        ),
    ],
)
