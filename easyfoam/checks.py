"""Plain-language checks of a project and a one-line status for each workflow step.

Pure functions: the window shows their results as badges and messages, and the
tests pin the wording down.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from easyfoam.foam.boundaryfile import Patch
from easyfoam.model import Project
from easyfoam.solvers import SOLVERS

STEPS = ("Geometry", "Mesh", "Physics", "Boundaries", "Run", "Results")
TURBULENCE_NAMES = {
    "laminar": "laminar",
    "kEpsilon": "k-epsilon",
    "kOmegaSST": "k-omega SST",
    "realizableKE": "realizable k-epsilon",
    "SpalartAllmaras": "Spalart-Allmaras",
}
_RANK = {"error": 3, "warning": 2, "todo": 1}


@dataclass(frozen=True)
class Issue:
    step: str
    level: str  # error (cannot run) | warning (probably not what you want) | todo (not done yet)
    text: str


@dataclass(frozen=True)
class StepState:
    state: str  # done | todo | warning | error
    detail: str


def _moving(vector: Sequence[float]) -> bool:
    return any(abs(c) > 0 for c in vector)


def project_issues(project: Project, patches: Sequence[Patch], has_mesh: bool) -> list[Issue]:
    issues: list[Issue] = []
    mesh, base = project.mesh, project.mesh.base

    if any(hi <= lo for lo, hi in zip(base.min, base.max)):
        issues.append(Issue("Mesh", "error", "The base mesh has no size: each max corner must be above its min."))
    if mesh.fluid_inside and not any(s.name == mesh.fluid_inside for s in project.shapes):
        issues.append(
            Issue("Mesh", "error", f"The fluid is set to be inside '{mesh.fluid_inside}', which no longer exists.")
        )
    if not has_mesh:
        issues.append(Issue("Mesh", "todo", "Generate the mesh before running."))

    if project.physics.nu <= 0:
        issues.append(Issue("Physics", "error", "The viscosity must be greater than zero."))

    multiphase = project.physics.solver in SOLVERS and SOLVERS[project.physics.solver].multiphase
    chosen = [project.boundary_for(p.name, p.type) for p in patches]
    if multiphase:
        if not _moving(project.physics.gravity):
            issues.append(Issue("Physics", "error", "Free-surface flow needs gravity: set it in the Physics step."))
        water_inlet = any(
            b.kind == "flowRateInlet" or (b.kind == "velocityInlet" and b.water_fraction > 0) for b in chosen
        )
        if patches and not project.physics.water_regions and not water_inlet:
            issues.append(
                Issue("Physics", "warning", "There is no water yet: add an initial water region or a water inlet.")
            )

    if patches:
        inlets = [b for b in chosen if b.kind in ("velocityInlet", "flowRateInlet", "waveInlet")]
        outlets = [
            b for b in chosen
            if b.kind in ("pressureOutlet", "freeOutflow", "atmosphere", "waterLevelOutlet", "waveOutlet")
        ]  # fmt: skip
        if not multiphase:
            for patch, b in zip(patches, chosen):
                if b.kind in ("waterLevelOutlet", "waveInlet", "waveOutlet"):
                    issues.append(
                        Issue("Boundaries", "error",
                              f"The condition on '{patch.name}' only exists in free-surface flow: "
                              "choose a free-surface flow type in Physics, or another condition here.")  # fmt: skip
                    )
        if inlets and not outlets:
            issues.append(
                Issue("Boundaries", "error",
                      "There is an inlet but no outlet, so the fluid has nowhere to go. "
                      "Make one boundary a pressure outlet.")  # fmt: skip
            )
        driven = (
            any(_moving(b.velocity) for b in chosen if b.kind in ("velocityInlet", "movingWall"))
            or any(b.flow_rate != 0 for b in chosen if b.kind == "flowRateInlet")
            or any(b.kind == "waveInlet" for b in chosen)
            or (multiphase and bool(project.physics.water_regions))  # water falling under gravity
        )
        if not driven:
            issues.append(
                Issue("Boundaries", "warning",
                      "Nothing drives the flow yet: give an inlet a velocity or a wall a motion.")  # fmt: skip
            )

    run = project.run
    steady = SOLVERS[project.physics.solver].steady if project.physics.solver in SOLVERS else True
    if run.end_time <= 0:
        issues.append(Issue("Run", "error", "The number of iterations (or the end time) must be above zero."))
    if not steady and run.delta_t <= 0:
        issues.append(Issue("Run", "error", "The time step must be greater than zero."))
    if project.forces.enabled and (project.forces.ref_area <= 0 or project.forces.ref_length <= 0):
        issues.append(Issue("Run", "error", "The force monitor needs a reference area and length above zero."))
    return issues


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def step_states(
    project: Project,
    patches: Sequence[Patch],
    has_mesh: bool,
    cells: int | None,
    times: Sequence[float],
) -> dict[str, StepState]:
    """State and a short summary for every workflow step."""
    computed = [t for t in times if t > 0]
    steady = SOLVERS[project.physics.solver].steady if project.physics.solver in SOLVERS else True
    turbulence = TURBULENCE_NAMES.get(project.physics.turbulence, project.physics.turbulence)
    multiphase = project.physics.solver in SOLVERS and SOLVERS[project.physics.solver].multiphase
    flow_kind = "Free surface" if multiphase else ("Steady" if steady else "Transient")

    states = {
        "Geometry": StepState(
            "done", _plural(len(project.shapes), "shape") if project.shapes else "Base mesh only"
        ),
        "Mesh": (
            StepState("done", f"{cells:,} cells" if cells else "Generated")
            if has_mesh
            else StepState("todo", "Not generated yet")
        ),
        "Physics": StepState("done", f"{flow_kind}, {turbulence}"),
        "Boundaries": (
            StepState("done", _plural(len(patches), "boundary").replace("boundarys", "boundaries"))
            if patches
            else StepState("todo", "Known after meshing")
        ),
        "Run": (
            StepState("done", f"Finished at {max(computed):g}") if computed else StepState("todo", "Not run yet")
        ),
        "Results": (
            StepState("done", _plural(len(computed), "saved result"))
            if computed
            else StepState("todo", "No results yet")
        ),
    }
    worst: dict[str, Issue] = {}
    for issue in project_issues(project, patches, has_mesh):
        if issue.step not in worst or _RANK[issue.level] > _RANK[worst[issue.step].level]:
            worst[issue.step] = issue
    for step, issue in worst.items():
        if issue.level != "todo":
            states[step] = StepState(issue.level, issue.text)
    return states
