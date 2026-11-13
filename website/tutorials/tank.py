"""A chlorine contact tank: the age of the water, a decaying chlorine residual and a tracer test (T10)."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import MESH_BUTTON, RUN_BUTTON, create, from_example


def show_age(d):
    d.go("Results")
    d.results("age")
    d.view("+z")
    d.flat(True)


def tracer_test(d):
    d.go("Run")
    d.w.run_tracer_test()
    d.wait()


def residence(d):
    d.go("Results")
    d.w.hydraulics("residence")
    d.settle(0.5)


TUTORIAL = Tutorial(
    slug="tank",
    title="Contact tank: water age and a tracer test",
    summary="How long does the water stay in a baffled chlorine contact tank? Map its age, follow a tracer through it and read off T10 and the baffling factor.",
    minutes=25,
    level="Intermediate",
    topics=["Water treatment", "Tracers", "Residence time"],
    run_time="about a minute for the flow and half a minute for the tracer test, on one core.",
    intro="""
Disinfection credit in a chlorine contact tank depends on **T10**: the time by which the first tenth
of the water has passed through. Baffles stop the water from short-circuiting, which raises T10
towards the theoretical residence time V/Q. Their effect is summed up in the *baffling factor*
T10/(V/Q).

In this tutorial you solve the steady flow through a tank with nine cross baffles, look at the age of
the water and a decaying chlorine residual, and then run a tracer test the way it is done in the
field: switch a tracer on at the inlet and record it at the outlet.
""",
    learn=[
        "carry several tracers: the age of the water and a chlorine residual that decays",
        "set the concentration that enters at an inlet",
        "run a step tracer test in the frozen flow",
        "read T10, the mean residence time, the baffling factor and the Morrill index",
    ],
    steps=[
        *from_example("tank", "tank", "Contact tank"),
        Step(
            title="Nine baffles",
            text="""
The tank is 30 m by 10 m and 3 m deep, seen from above (one cell over the depth). Nine cross baffles
3 m apart leave a 2 m gap at alternate ends, so the water winds from one corner to the other.
""",
            screen="Geometry",
            before=create("tank", "tank"),
            marks=[Mark("item(w.geometry_panel.shape_list, 'baffle1')", "The baffles are plain boxes, **baffle1** to **baffle9**.")],
        ),
        Step(
            title="Age and chlorine",
            text="""
In **Physics**, the tank carries two tracers. **age** counts the seconds since the water came in,
so dead zones show up as old water. **chlorine** comes in at 2 mg/L and decays at **0.3 per hour**,
a first-order rate.
""",
            screen="Physics",
            marks=[
                Mark("w.physics_panel.tracer_table", "Two tracers: the age of the water and chlorine, decaying at `0.3` per hour."),
                Mark("w.physics_panel.add_age_button", "**Add water age** adds a tracer that counts seconds."),
            ],
        ),
        Step(
            title="What comes in",
            text="""
The inlet sends in 0.1 m³/s through a 2 m opening. Its **tracer concentration** is the chlorine dose:
**2** mg/L. The age needs none: water enters with age zero.
""",
            screen="Boundaries",
            before=lambda d: d.boundary("inlet"),
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'inlet')", "The boundary **inlet**."),
                Mark("w.boundary_panel.tracer_value", "**Tracer concentration**: `2`."),
            ],
        ),
        Step(
            title="Mesh and solve the flow",
            text="""
The flow is steady (simpleFoam). The mesh takes a few seconds and the flow about a minute; the
tracers are solved along with it.
""",
            screen="Run",
            before=lambda d: d.mesh(),
            marks=[MESH_BUTTON, RUN_BUTTON],
        ),
        Step(
            title="The age of the water",
            text="""
When the run is done, show **age** in the **Results** step, seen from above. Young water (blue) runs
round the ends of the baffles; the corners behind them hold older water. The age of the water
leaving is V/Q, 7680 s, as it must be for a steady flow.
""",
            screen="Results",
            before=lambda d: (d.run(), show_age(d)),
            cover=True,
            marks=[Mark("w.results_panel.field", "**Quantity**: `age`, in seconds.")],
        ),
        Step(
            title="The tracer test",
            text="""
In the **Run** step, under **Tracer test**, a tracer is fed in at the inlet and followed to the
outlet in the frozen flow. A **step** test switches it on and leaves it on, as in the field. Leave
**Follow it for** at 0: EasyFOAM follows it for three times V/Q.
""",
            screen="Run",
            before=tracer_test,
            marks=[
                Mark("w.run_panel.test_kind", "**Dose**: *Step*."),
                Mark("w.run_panel.test_button", "Press **Run the tracer test**."),
                Mark("w.run_panel.test_status", "The water volume, the inflow and V/Q."),
            ],
        ),
        Step(
            title="T10 and the baffling factor",
            text="""
In **Results**, press **Residence time**. The plot shows F(t), the share of the tracer that has left,
with T10 and V/Q marked. With nine baffles the baffling factor is about **0.5**: *average* baffling.
Without them it drops to about 0.2. The last line says how much of the chlorine is left at the
outlet, worked out from these residence times.
""",
            screen="Results",
            tab="Hydraulics",
            before=residence,
            marks=[
                Mark("w.results_panel.residence_button", "Press **Residence time**."),
                Mark("w.results_panel.hydraulics_info", "T10, T50, T90, the baffling factor and the chlorine left at the outlet."),
            ],
            tip="Delete the baffles in the Geometry step, rerun the flow and the tracer test, and compare.",
        ),
    ],
)
