"""Your own geometry: flow over an ogee spillway from an STL file, built from an empty project."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON


def import_the_spillway(d):
    from website.files import spillway_stl

    d.create("empty", "spillway")
    source = d.work.parent / "spillway.stl"
    source.write_text(spillway_stl(), encoding="utf-8")
    d.w.geometry_panel.import_file(source, "m")
    d.settle(0.5)
    d.view("fit")


def refine_the_surface(d):
    d.set(d.w.geometry_panel.level_min, 1)
    d.set(d.w.geometry_panel.level_max, 2)


def make_the_channel(d):
    mesh = d.w.mesh_panel
    d.go("Mesh")
    d.set(mesh.base_min, [0, 0, 0])
    d.set(mesh.base_max, [4, 0.5, 1])
    for spin, cells in zip(mesh.cells, (80, 10, 20)):
        d.set(spin, cells)
    d.view("fit")


def name_the_faces(d):
    mesh = d.w.mesh_panel
    mesh.set_face("zMin", "bed", "wall")
    mesh.set_face("zMax", "atmosphere", "patch")


def choose_the_physics(d):
    physics = d.w.physics_panel
    d.set(physics.solver, "interFoam")
    d.set(physics.turbulence, "kOmegaSST")
    d.set(physics.material, "water")


def fill_the_reservoir(d):
    d.w.physics_panel.add_water_region([0, 0, 0, 1.5, 0.5, 0.5])


def set_the_inflow(d):
    d.boundary("inlet")
    d.set(d.w.boundary_panel.kind, "flowRateInlet")
    d.set(d.w.boundary_panel.flow_rate, 0.04)


def set_the_outflow(d):
    d.boundary("outlet")
    d.set(d.w.boundary_panel.kind, "freeOutflow")


def add_the_monitors(d):
    d.go("Run")
    d.w.run_panel.add_probe([0.7, 0.25, 0.3])
    d.set(d.w.run_panel.flow_monitors, "outlet")


def set_the_run(d):
    run = d.w.run_panel
    d.set(run.end_time, 12.0)
    d.set(run.delta_t, 0.001)
    d.set(run.max_courant, 0.7)
    d.set(run.write_interval, 0.5)
    d.set(run.processors, 4)


def show_surface(d):
    d.go("Results")
    d.results("U", "water")
    d.view("iso")


TUTORIAL = Tutorial(
    slug="spillway",
    title="Spillway from your own geometry",
    summary="Import an STL file of an ogee spillway and build the whole free-surface case around it from an empty project.",
    minutes=40,
    level="Advanced",
    topics=["Free surface", "Hydraulic structures", "Your own geometry", "Checked against theory"],
    run_time="about a minute for the mesh and several minutes for the run, on four cores.",
    intro="""
The earlier tutorials started from examples. This one starts from nothing but a geometry file, the
way your own projects will: you import the shape of a structure, build a channel around it, and set
up the water, the boundaries and the monitors yourself.

The structure is an **ogee spillway**: a crest shaped like the underside of the water jet that would
spring from a sharp edge, so that the water stays attached all the way down. It stands 0.5 m above
the bed of a channel 0.5 m wide, and it has to pass 0.04 m³/s (40 litres a second).

Download the geometry first: [spillway.stl](files/spillway.stl). It is drawn in metres.
""",
    learn=[
        "import an STL (or STEP) file and choose its length unit",
        "build a channel around a structure and name its faces",
        "set up a free-surface case from an empty project: water, inflow, outflow, open top",
        "add a gauge and a discharge monitor, and compare the head with the spillway formula",
    ],
    steps=[
        Step(
            title="Start an empty project",
            text="Start EasyFOAM and create a new, empty project.",
            screen="Welcome",
            marks=[Mark("w.welcome.new_button", "Click **New project**.")],
        ),
        Step(
            title="Name it",
            screen="Dialog",
            before=lambda d: d.show_dialog("empty", "spillway"),
            marks=[
                Mark("dlg.name", "Type the name `spillway`."),
                Mark("dlg.example", "Leave **Start from** on *Empty project*."),
                Mark("dlg.ok", "Click **Create project**."),
            ],
        ),
        Step(
            title="Import the geometry",
            text="""
In the **Geometry** step, import the file you downloaded. EasyFOAM asks which length unit the file is
drawn in: STL files do not say, and a part drawn in millimetres would otherwise arrive a thousand
times too large. This one is in **metres**.

The file is copied into the project, so the project stays complete if you move it.
""",
            screen="Geometry",
            before=import_the_spillway,
            marks=[
                Mark("button(w.geometry_panel, 'Import')", "Click **Import**, choose `spillway.stl`, and answer *metres*."),
                Mark("item(w.geometry_panel.shape_list, 'spillway')", "The shape appears in the list and in the 3D view."),
                Mark("viewbutton('Fit')", "Click **Fit** to bring it into view."),
            ],
            tip="STEP, IGES and BREP files from CAD programs are imported in the same way if the optional `cad` part of EasyFOAM is installed.",
        ),
        Step(
            title="How fine the mesh is on the spillway",
            text="""
The curved crest is where the flow is decided, so ask for finer cells there. Level 1 halves the base
cell size; level 2, used where the surface curves, halves it again.
""",
            screen="Geometry",
            before=refine_the_surface,
            marks=[
                Mark("w.geometry_panel.level_min", "**Surface refinement, min**: `1`."),
                Mark("w.geometry_panel.level_max", "**Surface refinement, max**: `2`."),
            ],
        ),
        Step(
            title="Build the channel",
            text="""
The base mesh is the channel. Make it 4 m long, 0.5 m wide and 1 m high: room for a reservoir
upstream of the spillway, a stretch of bed downstream, and air above the water.

The spillway was drawn **wider than the channel and deeper than the bed** on purpose. Where the
channel cuts through it, the mesh ends cleanly on the spillway's surface.
""",
            screen="Mesh",
            before=make_the_channel,
            marks=[
                Mark("w.mesh_panel.base_min", "**Corner (min)**: `0`, `0`, `0`."),
                Mark("w.mesh_panel.base_max", "**Corner (max)**: `4`, `0.5`, `1`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `80`, `10`, `20`, which makes 5 cm cubes."),
                Mark("viewbutton('Fit')", "Click **Fit**."),
            ],
        ),
        Step(
            title="Name the faces",
            text="""
The two ends are already called `inlet` and `outlet`, and the long sides `sides`. Two faces need
changing: the bottom is the solid bed of the channel, and the top is open to the air. Names matter:
EasyFOAM recognises `atmosphere` and sets that boundary up for you.
""",
            screen="Mesh",
            before=name_the_faces,
            marks=[
                Mark("w.mesh_panel._face_names['zMin']", "**zMin**: name `bed`, type `wall`."),
                Mark("w.mesh_panel._face_names['zMax']", "**zMax**: name `atmosphere`, type `patch`."),
                MESH_BUTTON,
            ],
        ),
        Step(
            title="The mesh",
            text="""
After about a minute the mesh is ready. The spillway is cut out of the channel, and the cells on its
surface are visibly smaller than the rest.
""",
            screen="Mesh",
            before=lambda d: d.mesh(),
            marks=[
                Mark("step('Mesh')", "The number of cells and a green tick."),
                Mark("w.viewer", "Turn the view to look at the crest.", "centre"),
            ],
        ),
        Step(
            title="Water, air and turbulence",
            text="An empty project starts as a plain air-flow case. Three choices turn it into a hydraulic one.",
            screen="Physics",
            before=choose_the_physics,
            marks=[
                Mark("w.physics_panel.solver", "**Flow type**: *Free surface: water and air*."),
                Mark("w.physics_panel.turbulence", "**Turbulence**: *k-omega SST*."),
                Mark("w.physics_panel.material", "**Fluid**: *Water*."),
            ],
        ),
        Step(
            title="Fill the reservoir",
            text="""
Scroll down to **Water and air**. Start with the reservoir full to the crest, so that the run does
not have to fill it first. Click **Add box** and type the corners into the new row: from the inlet
to the upstream face of the spillway, 0.5 m deep.
""",
            screen="Physics",
            before=fill_the_reservoir,
            marks=[
                Mark("button(w.physics_panel, 'Add box')", "Click **Add box**."),
                Mark("w.physics_panel.water_table", "Type `0`, `0`, `0` and `1.5`, `0.5`, `0.5` into the row."),
            ],
        ),
        Step(
            title="The inflow",
            text="The inlet brings in the discharge and lets the water find its own level.",
            screen="Boundaries",
            before=set_the_inflow,
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "Select **inlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Inlet by flow rate*."),
                Mark("w.boundary_panel.flow_rate", "**Flow rate**: `0.04` m³/s."),
            ],
        ),
        Step(
            title="The outflow",
            text="""
Downstream the water arrives fast and shallow and simply leaves. The other boundaries are already
right: `atmosphere` is open to the air, `sides` are frictionless, `bed` and `spillway` are walls.
""",
            screen="Boundaries",
            before=set_the_outflow,
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'outlet')", "Select **outlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Free outflow*."),
            ],
        ),
        Step(
            title="A gauge and a discharge monitor",
            text="""
In the **Run** step, scroll down. Add one probe in the middle of the reservoir: in a free-surface
case it works as a gauge and records the water depth. Then ask for the discharge through the outlet.
""",
            screen="Run",
            before=add_the_monitors,
            marks=[
                Mark("button(w.run_panel, 'Add point')", "Click **Add point**."),
                Mark("w.run_panel.probe_table", "Type `0.7`, `0.25`, `0.3`."),
                Mark("w.run_panel.flow_monitors", "Under **Discharge**, **Through**: `outlet`."),
            ],
        ),
        Step(
            title="Run for twelve seconds",
            text="""
Scroll back up to the run control. An empty project still carries the settings of a steady run, so
give the time step a small starting value; EasyFOAM adjusts it from there to keep the Courant
number below the limit.
""",
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
            title="Wait for the outflow to match the inflow",
            text="""
On the **Discharge** tab the outflow starts at nothing, jumps when the first water arrives, and
settles at the 0.04 m³/s that come in. From then on the flow is steady.
""",
            screen="Run",
            tab="Discharge",
            before=lambda d: d.run(until=0.5),
            marks=[
                Mark("tab('Discharge')", "Open the **Discharge** tab.", "top"),
                Mark("w.flow_label", "The latest value."),
            ],
        ),
        Step(
            title="The head on the crest",
            text="""
When the run has finished, the **Probes** tab shows the depth in the reservoir levelling off. Take
the crest height, 0.5 m, away from it to get the head on the spillway.

Now the check. An ogee crest working near its design head passes about q = 2.18 × H^1.5 per metre
of width. Here q = 0.04 / 0.5 = 0.08 m²/s, so H = (0.08 / 2.18)^(2/3) = **0.110 m**, and the gauge
should read about 0.61 m.

It reads **0.609 m**: a head of 0.109 m, within a millimetre of the formula. Do not expect such
luck every time on a mesh this coarse; the point is that the simulation and a century of spillway
experiments agree on the size of the answer.
""",
            screen="Run",
            tab="Probes",
            before=lambda d: d.wait(),
            marks=[Mark("tab('Probes')", "Open the **Probes** tab and read the depth at the end of the run.", "top")],
        ),
        Step(
            title="The water over the spillway",
            text="""
The **Results** step shows the water surface coloured by speed. The water glides over the crest,
stays on the face all the way down and runs off along the bed as a fast, thin sheet.
""",
            screen="Results",
            before=show_surface,
            cover=True,
            marks=[
                Mark("w.results_panel.mode", "**Show**: *Water surface*."),
                Mark("w.results_panel.time", "Step through **Saved time** to watch the flow establish itself."),
            ],
        ),
        Step(
            title="Try it yourself",
            text="""
- Choose the quantity `cavitationIndex` in the Results step: on a spillway face it shows where low
  pressure could damage the concrete.
- Raise the discharge to `0.08`. Above the design head the pressure on the crest falls further.
- Halve the cell size and see how much the head changes. Until it stops changing, the mesh is part
  of the answer.
- Use your own structure: any closed STL or STEP file works in place of this one.
""",
        ),
    ],
)
