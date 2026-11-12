"""Install EasyFOAM and OpenFOAM, start the program, find your way."""

from website.sitegen import Mark, Step, Tutorial


def open_sphere(d):
    d.create("sphere", "first-look")
    d.view("iso")


TUTORIAL = Tutorial(
    slug="getting-started",
    title="Install and first look",
    summary="Set up OpenFOAM and EasyFOAM on your computer, start the program and see how it is laid out.",
    minutes=20,
    level="Beginner",
    topics=["Basics"],
    run_time="none; most of the time goes into downloading OpenFOAM.",
    intro="""
EasyFOAM is a window for [OpenFOAM](https://www.openfoam.com), the free flow solver used across
industry and research. EasyFOAM does not contain OpenFOAM: it drives the ordinary OpenFOAM that you
install yourself, and it leaves an ordinary OpenFOAM case in your project folder. Nothing is locked
in, and there are no limits on the size of a case or the number of processor cores.

So there are two things to install: OpenFOAM, and EasyFOAM itself.
""",
    learn=[
        "install OpenFOAM on Windows (inside WSL) or on Linux",
        "install and start EasyFOAM",
        "check that EasyFOAM has found OpenFOAM",
        "find your way round the window",
    ],
    steps=[
        Step(
            title="What you need",
            text="""
- Windows 10 or 11, or Linux.
- About 3 GB of free disk space for OpenFOAM.
- [Python](https://www.python.org/downloads/) 3.11 or newer.
- Optional: [ParaView](https://www.paraview.org/download/) for films, streamlines and other detailed pictures.
""",
        ),
        Step(
            title="Install OpenFOAM",
            text="""
On **Windows**, OpenFOAM runs inside WSL, the Linux system that Windows provides. Open PowerShell and
install Ubuntu:

```
wsl --install -d Ubuntu-24.04
```

Restart the computer if Windows asks you to, start **Ubuntu** from the Start menu, and choose a user
name and a password when it asks. Then, in the Ubuntu window (or in a terminal on a Linux computer),
install OpenFOAM:

```
curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt-get install openfoam2506-default
```

That is all: you do not need to start OpenFOAM yourself. EasyFOAM finds it.
""",
            tip="EasyFOAM is tested with OpenFOAM v2506 from openfoam.com. Other recent versions from the same source should work too.",
        ),
        Step(
            title="Install EasyFOAM",
            text="""
Download the EasyFOAM source and open a terminal (PowerShell on Windows) in its folder. Create a
private Python environment for it and install EasyFOAM into that:

```
python -m venv .venv
.venv\\Scripts\\python -m pip install -e ".[gui]"
```

On Linux the second line starts with `.venv/bin/python`. To import STEP and IGES files from CAD
programs as well, install `".[gui,cad]"` instead.
""",
        ),
        Step(
            title="Start it",
            text="""
On Windows, double-click **EasyFOAM.cmd** in the EasyFOAM folder. On any system you can also start
it from the terminal:

```
.venv\\Scripts\\python -m easyfoam.gui.app
```

The start page appears. Look at the bottom right corner first.
""",
            screen="Welcome",
            marks=[
                Mark("w.runtime_label", "EasyFOAM has found OpenFOAM. If this says *not found*, check the installation above, then use **OpenFOAM › Search again**.", "left"),
                Mark("w.welcome.example_buttons['sphere']", "Ready-made examples. Each has a tutorial on this site."),
                Mark("w.welcome.new_button", "**New project** starts from nothing."),
                Mark("w.welcome.no_recent", "Projects you have worked on are listed here for quick access.", "left"),
            ],
        ),
        Step(
            title="The window",
            text="""
Open any example to see the working window; the picture shows *Air flow past a sphere*. Every case
is set up in the same six steps, from top to bottom.
""",
            screen="Geometry",
            before=open_sphere,
            cover=True,
            marks=[
                Mark("step('Geometry')", "**The steps.** Geometry, Mesh, Physics, Boundaries, Run, Results. A green tick means a step is ready; an orange mark means something needs your attention."),
                Mark("w.geometry_panel.shape_list", "**The settings** of the step you are on. Hold the mouse over any input for an explanation.", "centre"),
                Mark("w.viewer", "**The 3D view.** Left mouse button turns, right button or wheel zooms, middle button moves. The buttons above it set standard views.", "centre"),
                Mark("tab('Residuals')", "**Plots and log.** Live plots of the run, and the full output of every tool.", "top"),
                Mark("w.mesh_action", "**The toolbar.** *Mesh* (F5) makes the mesh, *Run* (F6) starts the simulation, *Stop* ends it and saves first."),
                Mark("w.next_button", "**Back** and **Next** walk through the steps."),
            ],
        ),
        Step(
            title="What is in a project folder",
            text="""
A project is a folder. EasyFOAM writes one small file of its own into it, and otherwise a normal
OpenFOAM case that any OpenFOAM user can read:

```
my-case/
  easyfoam.json     everything you chose, in one file
  system/ constant/ 0/    the OpenFOAM case, written from your choices
  log.blockMesh ...       the output of every tool that ran
  .easyfoam/mesh.sh       the exact commands that were run
```

Projects are saved automatically as you work. To move one to another computer, copy the folder.
""",
        ),
        Step(
            title="Where to go next",
            text="""
Go on to the [lid-driven cavity](cavity.html). It takes a quarter of an hour, needs no geometry and
teaches the six steps on a case that runs in seconds. The tutorials after it each add one new idea:
flow inside a shape, flow around a body, a free water surface, hydraulic structures, waves, and
shapes that move.
""",
        ),
    ],
)
