"""Flow over a weir: discharge, water level and a check against the weir formula."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def show_surface(d):
    d.go("Results")
    d.results("U", "water")
    d.view("iso")


TUTORIAL = Tutorial(
    slug="weir",
    title="Flow over a weir",
    summary="An open channel with a weir: set a discharge, measure the water level and compare it with the weir formula.",
    minutes=30,
    level="Intermediate",
    topics=["Free surface", "Hydraulic structures", "Checked against theory"],
    run_time="about a minute for the mesh and several minutes for the run, on four cores.",
    intro="""
A weir is a wall across a channel that the water has to flow over. How high the water rises in front
of it for a given discharge is the oldest question in hydraulics, and the reason weirs are used to
measure flow. In this tutorial you send a known discharge down a channel, let the simulation find
the water level, and compare it with the textbook formula.

The channel is 6 m long and 0.5 m wide. The weir is 0.51 m high and 0.25 m thick, and the discharge
is 0.05 m³/s (50 litres a second).
""",
    learn=[
        "build a channel with a structure in it",
        "use the hydraulic boundaries: an inlet by flow rate, a free outflow and an open top",
        "record the discharge through a boundary and the water depth at a gauge",
        "judge when a free-surface run has become steady",
    ],
    steps=[
        *from_example("weir", "weir", "Flow over a weir"),
        Step(
            title="The weir",
            text="""
The weir is a plain box. Like the pipe in the earlier tutorial, it is **larger than the channel on
purpose**: it sticks out through both side walls and through the bed, so that the mesh is cut
cleanly and no thin gaps are left at its edges.
""",
            screen="Geometry",
            before=create("weir", "weir"),
            marks=[
                Mark("item(w.geometry_panel.shape_list, 'weir')", "The shape **weir**."),
                Mark("w.geometry_panel.box_min", "**Corner (min)**: `2.52`, `-1`, `-1`. Well outside the channel in y and z."),
                Mark("w.geometry_panel.box_max", "**Corner (max)**: `2.77`, `2`, `0.51`. The last number is the height of the crest."),
                Mark("w.geometry_panel.level_min", "**Surface refinement** `1` on the weir."),
            ],
            tip="A real spillway profile comes in the same way: **Import** an STL or STEP file. The tutorial on your own geometry shows how.",
        ),
        Step(
            title="The channel",
            text="""
The base mesh is the channel: 6 m long, 0.5 m wide and 1.5 m high, so that there is room for air
above the water. Its faces are named for what they will be.
""",
            screen="Mesh",
            marks=[
                Mark("w.mesh_panel.base_max", "**Corner (max)**: `6`, `0.5`, `1.5`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `96`, `8`, `24`, which makes 62.5 mm cubes."),
                Mark("w.mesh_panel._face_names['xMin']", "`inlet` and `outlet` at the two ends, `sides` along the channel."),
                Mark("w.mesh_panel._face_names['zMin']", "`bed` at the bottom is a `wall`; `atmosphere` at the top is an opening."),
                MESH_BUTTON,
            ],
        ),
        Step(
            title="The mesh",
            text="""
The mesh has about 20,000 cells, with finer ones on the weir. The weir itself is now a hole in the
mesh with a wall called `weir` around it.
""",
            screen="Mesh",
            before=lambda d: d.mesh(),
            marks=[
                Mark("step('Mesh')", "The number of cells."),
                Mark("w.viewer", "The weir stands in the channel; the boundaries are listed in the corner of the view.", "centre"),
            ],
        ),
        Step(
            title="Water, air and turbulence",
            text="""
The flow type is the free-surface one. Flow over a weir is turbulent, so a turbulence model is
switched on.
""",
            screen="Physics",
            marks=[
                Mark("w.physics_panel.solver", "**Flow type**: *Free surface: water and air*."),
                Mark("w.physics_panel.turbulence", "**Turbulence**: *k-omega SST*."),
                Mark("w.physics_panel.material", "**Fluid**: *Water*."),
            ],
        ),
        Step(
            title="Start with a full reservoir",
            text="""
A run that starts with an empty channel spends most of its time filling up. Start with the reservoir
already full to just below the crest instead: one box of water from the inlet to the weir, 0.5 m
deep.
""",
            screen="Physics",
            marks=[
                Mark("w.physics_panel.water_table", "One box: from `0, 0, 0` to `2.52, 0.5, 0.5`."),
                Mark("w.physics_panel.gravity", "**Gravity**: `0`, `0`, `-9.81`."),
            ],
        ),
        Step(
            title="The inflow",
            text="""
The inlet is the heart of a channel case. *Inlet by flow rate* brings in the discharge you ask for,
and it lets the water find its own level on the inlet: you do not need to know the depth beforehand.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("inlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "Select **inlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Inlet by flow rate*."),
                Mark("w.boundary_panel.flow_rate", "**Flow rate**: `0.05` m³/s."),
            ],
        ),
        Step(
            title="The outflow",
            text="""
Downstream of the weir the water shoots along the bed. *Free outflow* lets whatever arrives leave
undisturbed. The remaining boundaries need no numbers: `atmosphere` is open to the air, the `sides`
are frictionless (slip), and `bed` and `weir` are walls.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("outlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'outlet')", "Select **outlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Free outflow*."),
            ],
            tip="If the water downstream is deep and slow, use *Outlet at a water level* instead and give the tailwater level.",
        ),
        Step(
            title="A gauge and a discharge monitor",
            text="""
In the **Run** step, scroll down to the monitors. In a free-surface case each probe point acts as a
**gauge**: it records the depth of water there. A second monitor records the discharge through a
boundary. Together they tell you when the flow has become steady.
""",
            screen="Run",
            marks=[
                Mark("w.run_panel.probe_table", "One gauge in the reservoir, at `1.2`, `0.25`, `0.3`. Only its x and y matter."),
                Mark("w.run_panel.flow_monitors", "Under **Discharge**, **Through**: `outlet`."),
            ],
        ),
        Step(
            title="Run for twenty seconds",
            text="""
The reservoir needs time to rise to the level that pushes 50 litres a second over the crest. Twenty
seconds of simulated time are enough here.
""",
            screen="Run",
            marks=[
                Mark("w.run_panel.end_time", "**End time**: `20` s."),
                Mark("w.run_panel.write_interval", "**Save every**: `0.5` s."),
                Mark("w.run_panel.processors", "**Processor cores**: `4`."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="Is it steady yet?",
            text="""
Watch the **Discharge** tab while the run goes on. At first nothing leaves, then the first surge
arrives at the outlet, and finally the outflow settles at what comes in. When the outflow equals the
inflow, the amount of water in the channel has stopped changing.
""",
            screen="Run",
            tab="Discharge",
            before=lambda d: d.run(until=0.5),
            marks=[
                Mark("tab('Discharge')", "Open the **Discharge** tab.", "top"),
                Mark("w.flow_label", "The latest value. It should end close to 0.05 m³/s."),
                Mark("w.progress", "How far the run is.", "top"),
            ],
        ),
        Step(
            title="The water level in the reservoir",
            text="""
When the run has finished, open the **Probes** tab. The gauge shows the depth in the reservoir
rising and then levelling off at about **0.67 m**. The crest is at 0.51 m, so the water stands about
**0.16 m** above it. That is the *head* on the weir.
""",
            screen="Run",
            tab="Probes",
            before=lambda d: d.wait(),
            marks=[Mark("tab('Probes')", "Open the **Probes** tab: the water depth at the gauge over time.", "top")],
        ),
        Step(
            title="The water surface",
            text="""
The **Results** step opens on the water surface, coloured by the speed of the water: slow in the
reservoir, fast where it plunges over the crest and along the bed.
""",
            screen="Results",
            before=show_surface,
            cover=True,
            marks=[
                Mark("w.results_panel.mode", "**Show**: *Water surface*."),
                Mark("w.results_panel.field", "**Quantity**: `U` colours the surface by speed."),
                Mark("w.results_panel.time", "Step through **Saved time** to watch the flow establish itself."),
            ],
        ),
        Step(
            title="Check it against the weir formula",
            text="""
For a broad-crested weir without losses, the discharge per metre of width is
q = 1.705 × H^1.5, with H the head above the crest. Here q = 0.05 / 0.5 = 0.1 m²/s, which gives
H = (0.1 / 1.705)^(2/3) = **0.151 m**.

The simulation gives about 0.16 m. A real, square-edged weir has losses that the ideal formula
leaves out, so a head a little above 0.151 m is what one expects. Keep in mind that the cells are
62.5 mm high, so there are only about three of them across the head: treat this as a check that the
result is sensible, not as a calibration. For figures you can rely on, refine the mesh until the
head no longer changes.
""",
        ),
        Step(
            title="Try it yourself",
            text="""
- Double the flow rate. By the formula the head should rise by a factor of 2^(2/3) = 1.59.
- Use `192`, `16`, `48` cells (it will take much longer) and see how the head changes.
- In the Results step, choose the quantity `cavitationIndex` to see where the pressure on the structure is lowest.
- Set **Refine at the water surface** to `1` in the Physics step: the mesh then follows the surface.
""",
        ),
    ],
)
