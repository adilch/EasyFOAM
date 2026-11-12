"""Waves in a flume: a wave maker, an absorbing outlet and two gauges."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def show_waves(d):
    d.go("Results")
    d.results("alpha.water", "slice")
    d.set(d.w.results_panel.normal, "y")
    d.view("+y")


TUTORIAL = Tutorial(
    slug="waves",
    title="Waves in a flume",
    summary="Make regular waves at one end of a flume, absorb them at the other, and measure them on the way.",
    minutes=25,
    level="Intermediate",
    topics=["Free surface", "Waves"],
    run_time="a few seconds for the mesh and a few minutes for the run.",
    intro="""
A wave flume is a long, narrow tank with a wave maker at one end. Here it is 8 m long with water
0.4 m deep. The wave maker sends waves 0.04 m high every 1.5 seconds; the far end swallows them
instead of sending them back; and two gauges record the water level as the waves pass.

The flume is modelled as a thin slice, one cell thick, which keeps the run short.
""",
    learn=[
        "fill a tank with still water to a level",
        "set up a wave maker: height, period and wave theory",
        "let waves leave without reflection",
        "measure the waves with gauges and compare with what you asked for",
    ],
    steps=[
        *from_example("waves", "waves", "Waves in a flume"),
        Step(
            title="The flume",
            text="""
There are no shapes: the flume is the base mesh itself, 8 m long, 0.8 m high and one 5 cm cell
thick. The cells are 25 mm, so a 0.04 m wave is less than two cells high: enough to carry the wave,
too few for fine detail.
""",
            screen="Mesh",
            before=create("waves", "waves"),
            marks=[
                Mark("w.mesh_panel.base_max", "**Corner (max)**: `8`, `0.05`, `0.8`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `320`, `1`, `32`."),
                Mark("w.mesh_panel._face_names['xMin']", "`inlet` will be the wave maker, `outlet` the absorbing end."),
                Mark("w.mesh_panel._face_types['yMin']", "Front and back are `empty`: a two-dimensional case.", "right"),
                MESH_BUTTON,
            ],
        ),
        Step(
            title="Still water",
            text="""
The physics is free-surface flow without a turbulence model. The water starts at rest and fills the
whole flume to 0.4 m, which is what **Fill to a level** produces: one box as long and wide as the
mesh.
""",
            screen="Physics",
            before=lambda d: d.mesh(),
            marks=[
                Mark("w.physics_panel.water_table", "One box of water, from `0, 0, 0` to `8, 0.05, 0.4`: still water 0.4 m deep."),
                Mark("w.physics_panel.gravity", "**Gravity**: `0`, `0`, `-9.81`."),
            ],
            tip="Make the still-water level fall on the line between two layers of cells (here 0.4 m = 16 cells of 25 mm). The water then starts exactly at the level you asked for.",
        ),
        Step(
            title="The wave maker",
            text="""
The inlet becomes a wave maker. You describe the waves you want and choose a wave theory that suits
them; for ordinary regular waves the second-order Stokes theory is the usual choice.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("inlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "Select **inlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Wave maker*."),
                Mark("w.boundary_panel.wave_height", "**Wave height**: `0.04` m, from trough to crest."),
                Mark("w.boundary_panel.wave_period", "**Wave period**: `1.5` s."),
                Mark("w.boundary_panel.wave_model", "**Wave theory**: *Stokes 2nd order*."),
            ],
        ),
        Step(
            title="The absorbing end",
            text="""
A plain wall at the far end would send every wave back and spoil the measurement. The
*Wave-absorbing outlet* moves like a paddle to cancel the waves that reach it.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("outlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'outlet')", "Select **outlet**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Wave-absorbing outlet*."),
            ],
        ),
        Step(
            title="Two gauges",
            text="""
In the **Run** step, scroll down to the probes. Two gauges record the water depth: one 2 m from the
wave maker, one 6 m from it. Comparing them shows whether the waves keep their height on the way.
""",
            screen="Run",
            marks=[Mark("w.run_panel.probe_table", "Gauges at x = `2` and x = `6`. Only x and y matter; the depth is measured along z.")],
        ),
        Step(
            title="Run for twelve seconds",
            text="Twelve seconds are eight wave periods: time for the first waves to cross the flume and for a regular pattern to form.",
            screen="Run",
            marks=[
                Mark("w.run_panel.end_time", "**End time**: `12` s."),
                Mark("w.run_panel.adjust", "**Keep the Courant number below** `0.5`: waves need a smaller value than other free-surface flows."),
                Mark("w.run_panel.write_interval", "**Save every**: `0.25` s."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="The waves pass the gauges",
            text="""
Open the **Probes** tab during the run. The first gauge starts to move after about a second; the
second one stays still until the waves have travelled the 6 m to it.
""",
            screen="Run",
            tab="Probes",
            before=lambda d: d.run(until=0.6),
            marks=[
                Mark("tab('Probes')", "Open the **Probes** tab: water depth at the two gauges.", "top"),
                Mark("w.progress", "How far the run is.", "top"),
            ],
        ),
        Step(
            title="Measure the waves",
            text="""
At the end, both gauges swing evenly around 0.4 m. Read the height from trough to crest off the
plot: about **0.038 m** at the first gauge and **0.037 m** at the second, for the 0.04 m asked for.
The small loss comes from the coarse mesh. The mean level stays at 0.4 m, which shows that no water
piles up at the absorbing end.
""",
            screen="Run",
            tab="Probes",
            before=lambda d: d.wait(),
            marks=[Mark("tab('Probes')", "Zoom into the plot with the mouse wheel to read the crests and troughs.", "top")],
        ),
        Step(
            title="The wave train",
            text="""
On a slice along the flume you can see the whole wave train at once. Because the flume is ten times
longer than it is high and the waves are small, they look gentle: that is how they really are.
""",
            screen="Results",
            before=show_waves,
            cover=True,
            marks=[
                Mark("w.results_panel.field", "**Quantity**: `alpha.water`."),
                Mark("w.results_panel.normal", "**Slice plane**: *Normal to y*."),
                Mark("w.results_panel.time", "Step through **Saved time** to see the waves travel."),
            ],
        ),
        Step(
            title="Try it yourself",
            text="""
- Change the wave theory to *Solitary wave* and send a single crest down the flume.
- Halve the cell size (`640`, `1`, `64` cells) and measure the wave height again.
- Add a box in the Geometry step, standing on the bed in the middle of the flume, and watch the
  waves break over a submerged breakwater.
""",
        ),
    ],
)
