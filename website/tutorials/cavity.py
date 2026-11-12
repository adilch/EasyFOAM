"""Lid-driven cavity, built from an empty project."""

from website.sitegen import Mark, Step, Tutorial
from website.tutorials.common import RUN_BUTTON


def size_the_box(d):
    mesh = d.w.mesh_panel
    d.set(mesh.base_min, [0, 0, 0])
    d.set(mesh.base_max, [1, 1, 0.1])
    for spin, cells in zip(mesh.cells, (40, 40, 1)):
        d.set(spin, cells)
    d.view("fit")


def name_the_faces(d):
    mesh = d.w.mesh_panel
    for face in ("xMin", "xMax", "yMin"):
        mesh.set_face(face, "walls", "wall")
    mesh.set_face("yMax", "lid", "wall")
    for face in ("zMin", "zMax"):
        mesh.set_face(face, "frontAndBack", "empty")


def choose_the_physics(d):
    physics = d.w.physics_panel
    d.set(physics.turbulence, "laminar")
    d.set(physics.material, "custom")
    d.set(physics.nu, 0.01)


def move_the_lid(d):
    d.boundary("lid")
    d.set(d.w.boundary_panel.kind, "movingWall")
    d.set(d.w.boundary_panel.velocity, [1, 0, 0])


def set_the_run(d):
    d.set(d.w.run_panel.end_time, 300.0)
    d.set(d.w.run_panel.write_interval, 100.0)


def show_the_speed(d):
    d.go("Results")
    d.results("U", "slice")
    d.set(d.w.results_panel.normal, "z")
    d.view("-z")


TUTORIAL = Tutorial(
    slug="cavity",
    title="Lid-driven cavity",
    summary="Your first case, built from an empty project: a closed box of fluid stirred by its sliding lid.",
    minutes=15,
    level="Beginner",
    topics=["Basics", "Internal flow"],
    run_time="a few seconds for the mesh and about ten seconds for the run.",
    intro="""
The lid-driven cavity is the classic first exercise of flow simulation. A square box is full of
fluid; its top wall (the lid) slides sideways and drags the fluid round in one large eddy. There is
no geometry file to import and the run takes seconds, so it is the quickest way to learn the six
steps of EasyFOAM: **Geometry, Mesh, Physics, Boundaries, Run, Results**.

The box is 1 m wide and 1 m high, the lid moves at 1 m/s and the fluid has a viscosity of
0.01 m²/s. That gives a Reynolds number of 1 × 1 / 0.01 = 100: slow, smooth (laminar) flow.
""",
    learn=[
        "create a project and find your way round the window",
        "make a mesh from a plain box and name its faces",
        "choose a fluid and a flow model",
        "give a wall a motion, run, and look at the speed on a slice",
    ],
    steps=[
        Step(
            title="Start a new project",
            text="Start EasyFOAM. The start page offers ready-made examples, but this time we build the case ourselves.",
            screen="Welcome",
            marks=[Mark("w.welcome.new_button", "Click **New project**.")],
        ),
        Step(
            title="Name it",
            text="A project is an ordinary folder. EasyFOAM creates it for you and keeps everything about the case inside.",
            screen="Dialog",
            before=lambda d: d.show_dialog("empty", "cavity"),
            marks=[
                Mark("dlg.name", "Type the name `cavity`."),
                Mark("dlg.location", "Choose the folder to create it in, or keep the suggestion."),
                Mark("dlg.example", "Leave **Start from** on *Empty project*."),
                Mark("dlg.ok", "Click **Create project**."),
            ],
        ),
        Step(
            title="Look around the window",
            text="""
The project opens on the first step. Take a moment to see how the window is laid out; it stays the
same for every case.

This case has no shapes: the fluid simply fills a box. So there is nothing to do in **Geometry**.
""",
            screen="Geometry",
            before=lambda d: d.create("empty", "cavity"),
            marks=[
                Mark("step('Geometry')", "The six steps, from top to bottom. A mark on the right shows whether a step is ready."),
                Mark("w.geometry_panel.shape_list", "The settings of the step you are on.", "centre"),
                Mark("w.viewer", "The 3D view. Drag with the left mouse button to turn, with the wheel to zoom.", "centre"),
                Mark("tab('Residuals')", "Plots and the log of the running tools.", "top"),
                Mark("w.next_button", "Click **Next: Mesh**."),
            ],
        ),
        Step(
            title="Size the box",
            text="""
Every mesh starts from a box of brick-shaped cells, the *base mesh*. Here the base mesh *is* the
whole mesh. Make it 1 m × 1 m, and only 0.1 m thick with a single cell through the thickness: that
turns the case into a two-dimensional one.
""",
            screen="Mesh",
            before=size_the_box,
            marks=[
                Mark("w.mesh_panel.base_min", "**Corner (min)**: `0`, `0`, `0`."),
                Mark("w.mesh_panel.base_max", "**Corner (max)**: `1`, `1`, `0.1`."),
                Mark("w.mesh_panel.cells[0]", "**Cells**: `40`, `40`, `1`. The line below tells you the cell size and the total: 1,600 cells."),
                Mark("viewbutton('Fit')", "Click **Fit** to bring the new box into view."),
            ],
            tip="Press **Tab** or **Enter** after typing a number. The 3D view follows what you type.",
        ),
        Step(
            title="Name the six faces",
            text="""
The six faces of the box become the boundaries of the flow. Give them names you will recognise
later, and a type. Faces with the same name become one boundary.
""",
            screen="Mesh",
            before=name_the_faces,
            marks=[
                Mark("w.mesh_panel._face_names['xMin']", "**xMin**, **xMax** and **yMin**: name `walls`, type `wall`."),
                Mark("w.mesh_panel._face_names['yMax']", "**yMax**, the top: name `lid`, type `wall`."),
                Mark(
                    "w.mesh_panel._face_types['zMin']",
                    "**zMin** and **zMax**, front and back: name `frontAndBack`, type `empty`. "
                    "*Empty* tells OpenFOAM that nothing happens in that direction.",
                    "right",
                ),
            ],
        ),
        Step(
            title="Generate the mesh",
            text="There are no shapes to cut the mesh around, so switch that part off and make the mesh.",
            screen="Mesh",
            before=lambda d: d.set(d.w.mesh_panel.snappy, False),
            marks=[
                Mark("w.mesh_panel.snappy", "Untick **Refine and cut around the geometry**."),
                Mark("w.mesh_panel.generate", "Click **Generate mesh** (or press **F5**)."),
            ],
        ),
        Step(
            title="Check the mesh",
            text="""
After a few seconds the mesh appears in the 3D view. OpenFOAM's own mesh check has already run:
its report is in the log.
""",
            screen="Mesh",
            tab="Log",
            before=lambda d: d.mesh(),
            marks=[
                Mark("step('Mesh')", "The **Mesh** step now shows a green tick and the number of cells."),
                Mark("tab('Log')", "Open the **Log** tab and look for *Mesh OK* near the end.", "top"),
                Mark("w.next_button", "Click **Next: Physics**."),
            ],
        ),
        Step(
            title="Choose the physics",
            text="""
The flow is steady and slow, so the default flow type is right. Switch the turbulence model off and
enter the viscosity.
""",
            screen="Physics",
            before=choose_the_physics,
            marks=[
                Mark("w.physics_panel.solver", "Leave **Flow type** on *Incompressible flow, steady*."),
                Mark("w.physics_panel.turbulence", "**Turbulence**: *Laminar (no turbulence model)*."),
                Mark("w.physics_panel.material", "**Fluid**: *Custom*."),
                Mark("w.physics_panel.nu", "**Kinematic viscosity**: `0.01`."),
            ],
            tip="Hold the mouse over any input for a short explanation of what it means and a sensible value.",
        ),
        Step(
            title="Make the lid move",
            text="""
The **Boundaries** step lists the boundaries you named. Walls start as ordinary walls that stand
still, which is right for `walls`. The lid needs a speed. The boundary you select lights up in the
3D view.
""",
            screen="Boundaries",
            before=move_the_lid,
            marks=[
                Mark("item(w.boundary_panel.patch_list, 'lid')", "Select **lid**."),
                Mark("w.boundary_panel.kind", "**Condition**: *Moving wall*."),
                Mark("w.boundary_panel.velocity", "**Velocity**: `1`, `0`, `0` (1 m/s in the x direction)."),
            ],
        ),
        Step(
            title="Set up the run",
            text="""
A steady run repeats the calculation until the flow no longer changes. Three hundred repeats
(iterations) are plenty here. The run stops earlier by itself if the flow has settled before that.

If something is still missing or wrong, a checklist at the bottom of this panel says so in plain
words, and so does the mark next to each step on the left.
""",
            screen="Run",
            before=set_the_run,
            marks=[
                Mark("w.run_panel.end_time", "**Iterations**: `300`."),
                Mark("w.run_panel.write_interval", "**Save every (iterations)**: `100`."),
                RUN_BUTTON,
            ],
        ),
        Step(
            title="Watch it converge",
            text="""
While the run goes on, the **Residuals** plot shows how much each quantity still changes from one
iteration to the next. Lines that fall steadily mean the solution is settling down. When the run
ends, EasyFOAM jumps to the results by itself.
""",
            screen="Run",
            tab="Residuals",
            before=lambda d: d.run(),
            marks=[
                Mark("tab('Residuals')", "The residuals of the velocity (`Ux`, `Uy`) and the pressure (`p`) fall by several powers of ten.", "top"),
                Mark("step('Run')", "The **Run** step shows that the run finished."),
            ],
        ),
        Step(
            title="Look at the flow",
            text="""
The **Results** step shows the speed on a slice through the box: fast under the lid, slow in the
corners, with one large eddy turning in the middle.
""",
            screen="Results",
            before=show_the_speed,
            cover=True,
            marks=[
                Mark("w.results_panel.field", "**Quantity**: `U` is the speed, `p` the pressure."),
                Mark("w.results_panel.mode", "**Show**: *Slice through the flow*."),
                Mark("w.results_panel.normal", "**Slice plane**: *Normal to z* looks straight into the box."),
                Mark("w.results_panel.time", "**Saved time** steps through the saved iterations."),
                Mark("viewbutton('−Z')", "Click **−Z** to look straight at the slice."),
            ],
        ),
        Step(
            title="Try it yourself",
            text="""
- Halve the viscosity to `0.005` (Reynolds number 200) and run again: the eddy moves off-centre.
- Use `80`, `80`, `1` cells and compare. A result that changes little on a finer mesh can be trusted more.
- Tick **Show cell edges** in the Results step to see the mesh under the colours.
- Click **Open in ParaView** for streamlines and anything else the built-in view does not offer.

Everything you did is stored in the project folder as an ordinary OpenFOAM case, which you can open,
read and run by hand.
""",
        ),
    ],
)
