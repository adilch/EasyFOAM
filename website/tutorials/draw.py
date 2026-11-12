"""Draw your own shapes: a weir sketched by hand and a block placed with the mouse."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON

WEIR = [[2.3, -0.3], [3.5, -0.3], [3.05, 0.5], [2.75, 0.5]]


def make_the_channel(d):
    d.create("empty", "my-weir")
    mesh = d.w.mesh_panel
    d.go("Mesh")
    d.set(mesh.base_min, [0, 0, 0])
    d.set(mesh.base_max, [6, 0.5, 1.5])
    for spin, cells in zip(mesh.cells, (96, 8, 24)):
        d.set(spin, cells)
    mesh.set_face("zMin", "bed", "wall")
    mesh.set_face("zMax", "atmosphere", "patch")
    d.view("fit")


def start_the_outline(d):
    d.go("Geometry")
    d.w.geometry_panel.add_primitive("profile")
    d.settle(0.6)


def draw_the_weir(d):
    d.open_sketch()
    d.dialog.use_preset("trapezoid")
    d.dialog.canvas.set_points(WEIR)
    d.dialog.canvas.fit()
    d.settle(0.3)


def finish_the_outline(d):
    d.accept_sketch()
    panel = d.w.geometry_panel
    d.set(panel.extent_from, -0.25)
    d.set(panel.extent_to, 0.75)
    d.set(panel.level_min, 1)
    d.set(panel.level_max, 1)
    d.view("fit")


def add_the_block(d):
    panel = d.w.geometry_panel
    panel.add_primitive("box")
    d.settle(0.5)
    panel.apply_box([4.2, 0.15, -0.1], [4.4, 0.35, 0.2])  # as if dragged there with the handles
    d.set(panel.level_min, 1)
    d.set(panel.level_max, 1)
    d.settle(0.6)


def choose_the_physics(d):
    physics = d.w.physics_panel
    d.set(physics.solver, "interFoam")
    d.set(physics.turbulence, "kOmegaSST")
    d.set(physics.material, "water")
    physics.add_water_region([0, 0, 0, 2.75, 0.5, 0.5])


def set_the_inflow(d):
    d.boundary("inlet")
    d.set(d.w.boundary_panel.kind, "flowRateInlet")
    d.set(d.w.boundary_panel.flow_rate, 0.05)
    d.boundary("outlet")
    d.set(d.w.boundary_panel.kind, "freeOutflow")
    d.boundary("inlet")


def set_the_run(d):
    run = d.w.run_panel
    d.go("Run")
    d.set(run.end_time, 12.0)
    d.set(run.delta_t, 0.001)
    d.set(run.max_courant, 0.7)
    d.set(run.write_interval, 0.5)
    d.set(run.processors, 4)


def show_surface(d):
    d.run()
    d.go("Results")
    d.results("U", "water")
    d.view("iso")


TUTORIAL = Tutorial(
    slug="draw-shapes",
    title="Draw your own weir",
    summary="No geometry file needed: sketch the cross-section of a weir with the mouse, add a block, and run the flow over them.",
    minutes=30,
    level="Intermediate",
    topics=["Free surface", "Hydraulic structures", "Your own geometry"],
    run_time="about a minute for the mesh and a few minutes for the run, on four cores.",
    intro="""
You do not need a CAD program for simple structures. EasyFOAM can draw six kinds of shape itself:
a **box**, a **sphere**, a **cylinder**, a **cone**, a **wedge** (a ramp), and an **outline that you
sketch by hand**, which is pushed through the channel to make a solid. That last one covers most
hydraulic structures, because a weir, a sill or a spillway is a cross-section that stays the same
across the width.

In this tutorial you sketch a weir with sloping faces, place a block downstream of it with the
mouse, and send 50 litres a second over both. Imported files and drawn shapes can be mixed freely
in one case.
""",
    learn=[
        "draw the cross-section of a structure on the sketch pad, by mouse and by typing",
        "extrude it across the channel",
        "add a box and move it with the handles in the 3D view",
        "set up and run the flow over what you drew",
    ],
    steps=[
        Step(
            title="Start an empty project",
            screen="Welcome",
            marks=[Mark("w.welcome.new_button", "Click **New project**, name it `my-weir` and click **Create project**.")],
        ),
        Step(
            title="Make the channel first",
            text="""
Go to the **Mesh** step before drawing anything. New shapes appear in the middle of the base mesh at
a size that fits it, so it pays to have the channel in place first: 6 m long, 0.5 m wide and 1.5 m
high, with a solid bed and an open top.
""",
            screen="Mesh",
            before=make_the_channel,
            marks=[
                Mark("w.mesh_panel.base_max", "**Corner (min)** `0`, `0`, `0` and **Corner (max)** `6`, `0.5`, `1.5`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `96`, `8`, `24`."),
                Mark("w.mesh_panel._face_names['zMin']", "**zMin**: name `bed`, type `wall`."),
                Mark("w.mesh_panel._face_names['zMax']", "**zMax**: name `atmosphere`, type `patch`."),
                Mark("viewbutton('Fit')", "Click **Fit**."),
            ],
        ),
        Step(
            title="Draw an outline",
            text="""
Go back to the **Geometry** step. There are two ways to get a shape: **Import** brings in a file,
**Draw** makes one here. Choose **Draw**, then **Outline, drawn by hand**.

A first outline appears: a small weir standing on the bed, reaching right through both side walls.
""",
            screen="Geometry",
            before=start_the_outline,
            marks=[
                Mark("w.geometry_panel.draw_button", "Click **Draw** and choose **Outline, drawn by hand**."),
                Mark("item(w.geometry_panel.shape_list, 'outline1')", "The new shape, `outline1`."),
                Mark("w.geometry_panel.outline_button", "Click **Draw the outline…** to change its shape."),
            ],
        ),
        Step(
            title="The sketch pad",
            text="""
The pad shows the channel from the side, with the base mesh as a dashed rectangle so that you can
see where the bed and the walls are. Draw with the mouse:

- **click** to add a corner, or click on a side to add one there;
- **drag** a corner to move it;
- **right-click** a corner to remove it;
- the **wheel** zooms.

For exact sizes, type the corners into the table. Here the weir is 0.5 m high with a 0.3 m wide
crest and sloping faces, and its foot lies 0.3 m *below* the bed so that the mesh is cut cleanly.
""",
            screen="Dialog",
            before=draw_the_weir,
            marks=[
                Mark("dlg.presets", "**Start from…** offers ready-made outlines: choose *Trapezoid (weir)*."),
                Mark("dlg.canvas", "Drag the corners, or add and remove some.", "centre"),
                Mark("dlg.table", "Type the corners: `2.3, -0.3`, then `3.5, -0.3`, `3.05, 0.5` and `2.75, 0.5`."),
                Mark("dlg.snap_step", "Corners snap to this distance; untick **Snap to** to place them freely."),
                Mark("dlg.ok", "Click **Use this outline**."),
            ],
            tip="An outline may have as many corners as you like and need not bulge outwards everywhere, but its sides must not cross each other. The pad turns red and says so if they do.",
        ),
        Step(
            title="Push it through the channel",
            text="""
The outline is drawn in the x–z plane, a side view, and extruded along y. Let it start before one
side wall and end beyond the other, so that it spans the whole width.
""",
            screen="Geometry",
            before=finish_the_outline,
            marks=[
                Mark("w.geometry_panel.plane", "**Drawn in**: *the x–z plane (a side view), extruded along y*."),
                Mark("w.geometry_panel.extent_row", "**Extruded from** `-0.25` **to** `0.75`: a quarter of a metre beyond each wall."),
                Mark("w.geometry_panel.level_min", "**Surface refinement**: `1` and `1`."),
            ],
        ),
        Step(
            title="Add a block and move it with the mouse",
            text="""
Now a second shape: **Draw**, then **Box**. With **Move and resize with the mouse** ticked, the
selected shape shows handles in the 3D view. Drag the small balls on the faces of a box to move its
faces; drag a sphere to move it; drag the ends of the axis of a cylinder or a cone. The numbers on
the left follow, and you can always type them instead.

Place the block downstream of the weir, standing on the bed in the middle of the channel.
""",
            screen="Geometry",
            before=add_the_block,
            marks=[
                Mark("w.geometry_panel.draw_button", "Click **Draw** and choose **Box**."),
                Mark("w.geometry_panel.handles", "**Move and resize with the mouse in the 3D view** is ticked."),
                Mark("w.viewer", "Drag the handles on the box.", "centre"),
                Mark("w.geometry_panel.box_min", "Or type: **Corner (min)** `4.2`, `0.15`, `-0.1` and **Corner (max)** `4.4`, `0.35`, `0.2`."),
                MESH_BUTTON,
            ],
        ),
        Step(
            title="The mesh",
            text="""
Both shapes are cut out of the channel. Drawn shapes are written into the project as surface files
when the mesh is made, so the case is complete without EasyFOAM.
""",
            screen="Mesh",
            before=lambda d: d.mesh(),
            marks=[
                Mark("step('Mesh')", "The number of cells and a green tick."),
                Mark("w.viewer", "The weir and the block in the channel.", "centre"),
            ],
        ),
        Step(
            title="Water, air and a full reservoir",
            text="""
The rest is the same as for any channel; the tutorial on the weir explains each choice. In the
**Physics** step choose the free-surface flow type, a turbulence model and water, then scroll down
and click **Add box** to fill the reservoir up to the crest.
""",
            screen="Physics",
            before=choose_the_physics,
            marks=[
                Mark("button(w.physics_panel, 'Add box')", "Click **Add box**."),
                Mark("w.physics_panel.water_table", "Type `0`, `0`, `0` and `2.75`, `0.5`, `0.5`."),
            ],
            tip="At the top of this step: **Flow type** *Free surface: water and air*, **Turbulence** *k-omega SST*, **Fluid** *Water*.",
        ),
        Step(
            title="The inflow and the outflow",
            text="""
Fifty litres a second come in; whatever arrives at the far end leaves. Select **outlet** as well and
set its **Condition** to *Free outflow*.
""",
            screen="Boundaries",
            before=set_the_inflow,
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "Select **inlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Inlet by flow rate*."),
                Mark("w.boundary_panel.flow_rate", "**Flow rate**: `0.05` m³/s."),
                Mark("item(w.boundary_panel.patch_list, 'outlet')", "Then select **outlet** and choose *Free outflow*."),
            ],
        ),
        Step(
            title="Run",
            screen="Run",
            before=set_the_run,
            marks=[
                Mark("w.run_panel.end_time", "**End time**: `12` s."),
                Mark("w.run_panel.delta_t", "**Time step**: `0.001` s."),
                Mark("w.run_panel.max_courant", "**Keep the Courant number below** `0.7`."),
                Mark("w.run_panel.write_interval", "**Save every**: `0.5` s."),
                Mark("w.run_panel.processors", "**Processor cores**: `4`, or as many as you have."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="The flow over what you drew",
            text="""
The water rises behind the weir, spills over the crest, runs down the sloping face and parts around
the block on the bed.
""",
            screen="Results",
            before=show_surface,
            cover=True,
            marks=[
                Mark("w.results_panel.mode", "**Show**: *Water surface*, coloured by `U`, the speed."),
                Mark("w.results_panel.time", "Step through **Saved time** to watch the reservoir fill and the flow settle."),
            ],
        ),
        Step(
            title="Try it yourself",
            text="""
- Open the sketch pad again and choose *Rounded crest (spillway)*: the same case with an ogee crest.
- Add a **Wedge** downstream as a ramp, and choose which way it rises.
- Draw a **Cylinder** standing in the channel as a bridge pier, and switch on the force monitor in
  the Run step to see the load on it.
- Give the block a **Motion** and it becomes a gate; give it a density and it floats.
""",
        ),
    ],
)
