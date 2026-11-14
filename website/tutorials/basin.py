"""A USBR Type III stilling basin made from the flow entering it, holding the jump of a Froude 6 jet."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def open_design(d):
    d.shape("basin")
    basin = next(s for s in d.w.project.shapes if s.name == "basin")
    d.open_structure(basin.structure)


def show_jump(d):
    d.run()
    d.go("Results")
    d.results("alpha.water", "slice")
    d.set(d.w.results_panel.normal, "y")  # a side view through the middle of the slice
    d.view("+y")
    d.flat(True)


def long_section(d):
    d.set(d.w.results_panel.average, 12)
    d.w.hydraulics("long")
    d.settle(0.5)


TUTORIAL = Tutorial(
    slug="basin",
    title="Stilling basin from the flow entering it",
    summary="Make a USBR Type III stilling basin from the depth and Froude number of the jet entering it, and see it hold the jump within 2.7 sequent depths.",
    minutes=25,
    level="Intermediate",
    topics=["Free surface", "Hydraulic structures", "Hydraulic results"],
    run_time="about half an hour on four cores.",
    intro="""
Water leaving a spillway or a gate is fast and shallow. Left to itself it forms a hydraulic jump
about six sequent depths long, which moves about as the tailwater changes. A stilling basin holds
the jump in place and makes it shorter. The US Bureau of Reclamation's basins (Engineering Monograph
25) are sized from the flow that enters them: Type III, for a Froude number above 4.5 and speeds
below about 18 m/s, has a row of chute blocks, a staggered row of baffle blocks and an end sill, and
needs only **2.7 sequent depths** of length.

In this tutorial you open an example in which a jet 4 cm deep enters at a Froude number of 6, look
at the basin EasyFOAM made for it, and run it.
""",
    learn=[
        "make a USBR stilling basin from the depth and Froude number of the flow entering it",
        "read its sequent depth, length and the tailwater it needs",
        "feed a fast jet in through a slot at the inlet",
        "see the jump held in the basin on a slice and in a long section",
    ],
    steps=[
        *from_example("basin", "basin", "Stilling basin"),
        Step(
            title="A fast jet",
            text="""
The channel is a slice 0.24 m wide of a wide basin, with frictionless sides. The jet comes in
through the bottom **4 cm** of the inlet: the box **lid** closes the rest. So the jet needs no tall
reservoir and no gate above it. The region **near_bed** halves the cells along the bed, where the
jet and the blocks are.
""",
            screen="Geometry",
            before=create("basin", "basin"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'lid')", "**lid**: a box from 4 cm above the bed upwards, at the inlet."),
                Mark("item(w.geometry_panel.shape_list, 'near_bed')", "**near_bed**: a region of finer cells."),
                Mark("item(w.geometry_panel.shape_list, 'basin')", "**basin**: the stilling basin, a structure."),
            ],
        ),
        Step(
            title="The basin's design",
            text="""
A basin is made from the flow entering it: **Type III**, a depth of **0.04 m** and a Froude number of
**6**. That makes the jet 3.76 m/s fast, the sequent depth y2 **0.32 m** and the basin **0.864 m**
long. Chute blocks as high, wide and far apart as the jet is deep stand at its entrance; baffle
blocks 0.066 m high stand 0.8 y2 further on, and an end sill closes the basin.
""",
            screen="Dialog",
            before=open_design,
            marks=[
                Mark("dlg.inputs['basin_type']", "**USBR type**: *Type III*."),
                Mark("dlg.inputs['y1']", "**Depth entering y1**: `0.04` m."),
                Mark("dlg.inputs['froude']", "**Froude number Fr1**: `6`."),
                Mark("dlg.preview", "The blocks and the sill, from the side and from above.", "centre"),
                Mark("dlg.info", "Sequent depth, length, tailwater and the size of every block.", "left"),
            ],
            tip="Choose Type IV and EasyFOAM tells you it is meant for Froude numbers between 2.5 and 4.5.",
        ),
        Step(
            title="Jet and tailwater",
            text="""
The inlet is a **velocity inlet** of water at the jet's speed, **3.7585 m/s**, through the slot under
the lid. The outlet holds the tailwater at the sequent depth, **0.32 m**, as a Type III basin needs.
""",
            screen="Boundaries",
            before=lambda d: (d.close_dialog(), d.boundary("inlet")),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "The boundary **inlet**."),
                Mark("w.boundary_panel.velocity", "**Velocity**: `3.7585`, `0`, `0` m/s."),
            ],
        ),
        Step(
            title="Mesh and run",
            text="Make the mesh and run the eight seconds on four cores.",
            screen="Run",
            before=lambda d: d.mesh(),
            marks=[MESH_BUTTON, Mark("w.run_panel.end_time", "**End time**: `8` s."), RUN_BUTTON],
        ),
        Step(
            title="The jump in the basin",
            text="""
Show **alpha.water** on a slice through the middle of the channel, seen from the side. The jet
strikes the chute blocks and the baffle blocks, the jump rolls over them, and the end sill lifts the
water to the tailwater depth: the jump is over by the end of the basin.
""",
            screen="Results",
            before=show_jump,
            cover=True,
            marks=[
                Mark("w.results_panel.field", "**Quantity**: `alpha.water`, the share of water."),
                Mark("w.results_panel.normal", "**Slice plane**: *Normal to y*, a side view."),
            ],
        ),
        Step(
            title="The long section",
            text="""
Average the last **12** saved times and press **Long section**. The jump starts at the chute blocks,
and the water is up to 0.9 y2 by the end sill, **2.7 y2** into the basin; a free jump would need
about 6 y2, 1.9 m. After the basin the flow is calm, with a Froude number of about **0.27**, and the
energy lost is what Bélanger gives for the jump.
""",
            screen="Results",
            tab="Hydraulics",
            before=long_section,
            marks=[
                Mark("w.results_panel.average", "**Average over**: `12` saved times."),
                Mark("w.results_panel.long_button", "Press **Long section**."),
                Mark("w.results_panel.hydraulics_info", "Depth and Froude number along the basin."),
            ],
            tip="**Structure** in the Geometry step also makes a labyrinth weir, a stepped spillway, a culvert and a vertical-slot fishway in the same way.",
        ),
    ],
)
