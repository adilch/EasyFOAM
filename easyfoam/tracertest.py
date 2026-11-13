"""Tracer test of a tank: the residence-time distribution, with the flow frozen at a steady solution.

As in a field tracer test, a tracer is fed in at the inlet (a step: switched on and left on, or
a short pulse) and its concentration is recorded where the water leaves. From that come T10 (the
time by which 10 % of the tracer has passed), the mean residence time, the baffling factor
T10 / (V/Q) used to credit contact time in disinfection, and the Morrill index T90 / T10.

The flow is taken from a finished steady run and kept fixed (pimpleFoam with no pressure
corrections and the turbulence frozen), so the test costs only the tracer equation per step.
It runs in a case folder of its own, ``tracer-test`` inside the project, so that the steady
results stay as they are.
"""

from __future__ import annotations

import copy
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from easyfoam import casegen
from easyfoam.casegen import setup as base
from easyfoam.foam.boundaryfile import read_boundary
from easyfoam.foam.dictfmt import foam_file
from easyfoam.model import Project, Tracer
from easyfoam.runtime import Step

SUBCASE = "tracer-test"
SETTINGS_FILE = "easyfoam-test.json"  # what the test was asked to do, kept beside its results
FIELD = "rtd"
FLOW_FIELDS = ("U", "p", "phi", "nut", "k", "omega", "epsilon", "nuTilda", "kt", "kl", "alpha.water", "p_rgh")


def subcase(case_dir: Path) -> Path:
    return Path(case_dir) / SUBCASE


# --- volume and flow ----------------------------------------------------------------


def volume_and_flow(data, project: Project, inlets: list[str]) -> tuple[float, float]:
    """Water volume of the domain (m³) and the flow entering through the inlets (m³/s)."""
    from easyfoam.hydraulics import area_vectors

    grid = data.internal
    volumes = np.asarray(grid.compute_cell_sizes(length=False, area=False, volume=True).cell_data["Volume"])
    if "alpha.water" in grid.array_names:
        volumes = volumes * np.clip(np.asarray(grid.cell_data["alpha.water"]), 0.0, 1.0)
    flow = 0.0
    for name in inlets:
        surface = data.patches.get(name)
        if surface is None or surface.n_cells == 0:
            raise ValueError(f"the result has no boundary called '{name}'")
        _centres, vectors = area_vectors(surface)
        velocity = np.asarray(surface.cell_data["U"], float)
        flux = -(velocity * vectors).sum(axis=1)  # the area vectors point out of the domain
        if "alpha.water" in surface.array_names:
            flux = flux * np.clip(np.asarray(surface.cell_data["alpha.water"], float), 0.0, 1.0)
        flow += float(flux.sum())
    return float(volumes.sum()), flow


# --- the frozen-flow run ------------------------------------------------------------


@dataclass
class TestSettings:
    inlet: str
    outlet: str
    kind: str = "step"  # step: the tracer is switched on at the start and left on; pulse: a short dose
    duration: float = 0.0  # s; 0 = three theoretical residence times
    pulse: float = 0.0  # s, length of a pulse; 0 = a fiftieth of the residence time


def inlet_dose(kind: str, pulse: float) -> str:
    if kind == "pulse":
        return f"table ((0 1) ({pulse:g} 1) ({pulse * 1.001:g} 0))"
    return "table ((0 1) (1e9 1))"


def prepare(case_dir: Path, project: Project, test: TestSettings, residence_time: float) -> tuple[Path, list[Step]]:
    """Write the tracer-test case next to the steady results and return it with its steps."""
    from easyfoam.pipeline import computed_times

    case_dir = Path(case_dir)
    times = computed_times(case_dir)
    if not times:
        raise RuntimeError("run the steady flow first: the tracer test starts from its result")
    patches = read_boundary(case_dir)
    names = {p.name for p in patches}
    for name in (test.inlet, test.outlet):
        if name not in names:
            raise ValueError(f"there is no boundary called '{name}'")
    duration = test.duration or 3.0 * residence_time
    pulse = test.pulse or residence_time / 50.0

    frozen = copy.deepcopy(project)
    frozen.physics.solver = "pimpleFoam" if not _multiphase(project) else project.physics.solver
    frozen.tracers = [Tracer(FIELD, 1e-9)]
    frozen.flow_monitors = [test.outlet]
    frozen.probes = []
    frozen.forces.enabled = False
    frozen.mesh.base = project.mesh.base
    run = frozen.run
    run.end_time, run.write_interval = duration, duration / 20.0
    run.adjust_time_step, run.max_courant, run.purge_write = True, 2.0, 0
    run.delta_t = max(duration / 20000.0, 1e-4)

    target = subcase(case_dir)
    shutil.rmtree(target, ignore_errors=True)
    (target / "0").mkdir(parents=True)
    shutil.copytree(case_dir / "constant", target / "constant",
                    ignore=shutil.ignore_patterns("boundaryData", "triSurface", "extendedFeatureEdgeMesh"))  # fmt: skip
    latest = case_dir / _time_name(case_dir, times[-1])
    for name in FLOW_FIELDS:
        if (latest / name).is_file():
            shutil.copy2(latest / name, target / "0" / name)

    solution = base.fv_solution(frozen)
    pimple = solution.setdefault("PIMPLE", {})
    pimple.update({"nOuterCorrectors": 1, "nCorrectors": 0, "momentumPredictor": False,
                   "nNonOrthogonalCorrectors": 0})  # fmt: skip
    pimple.pop("residualControl", None)
    properties = base.turbulence_properties(frozen)
    for model in ("RAS", "LES"):
        if model in properties:
            properties[model]["turbulence"] = False  # keep the eddy viscosity of the steady solution
    boundaries = {p.name: frozen.boundary_for(p.name, p.type) for p in patches}
    tracer = base.tracer_fields(frozen, patches, boundaries)[FIELD][1]
    tracer["boundaryField"][test.inlet] = {"type": "uniformFixedValue", "uniformValue": inlet_dose(test.kind, pulse)}
    files = {
        "system/controlDict": foam_file("dictionary", "controlDict", base.control_dict(frozen, patches)),
        "system/fvSchemes": foam_file("dictionary", "fvSchemes", base.fv_schemes(frozen)),
        "system/fvSolution": foam_file("dictionary", "fvSolution", solution),
        "system/decomposeParDict": foam_file("dictionary", "decomposeParDict", base.decompose_dict(frozen)),
        "constant/turbulenceProperties": foam_file("dictionary", "turbulenceProperties", properties,
                                                   location="constant"),  # fmt: skip
        f"0/{FIELD}": foam_file("volScalarField", FIELD, tracer, location="0"),
        f"{project.name}.foam": "",
    }
    casegen.write_files(target, files)
    record = {"inlet": test.inlet, "outlet": test.outlet, "kind": test.kind, "duration": duration, "pulse": pulse,
              "theoretical": residence_time}  # fmt: skip
    (target / SETTINGS_FILE).write_text(json.dumps(record, indent=1), encoding="utf-8")
    solver = frozen.physics.solver
    n = frozen.run.processors
    if n <= 1:
        steps = [Step(solver, solver)]
    else:
        steps = [Step("decomposePar", "decomposePar -force"),
                 Step(solver, f"mpirun -np {n} {solver} -parallel"),
                 Step("reconstructPar", "reconstructPar")]  # fmt: skip
    return target, steps


def _multiphase(project: Project) -> bool:
    from easyfoam.solvers import solver_spec

    return solver_spec(project.physics.solver).multiphase


def _time_name(case_dir: Path, time: float) -> str:
    for d in Path(case_dir).iterdir():
        if casegen._is_time_dir(d) and math.isclose(float(d.name), time):
            return d.name
    raise FileNotFoundError(f"no result folder for time {time:g}")


# --- the residence-time distribution -------------------------------------------------


@dataclass
class ResidenceTimes:
    """What a tracer test says about a tank."""

    times: np.ndarray
    concentration: np.ndarray  # at the outlet, as a share of the inlet concentration
    cumulative: np.ndarray  # F(t): share of the tracer that has left by time t
    density: np.ndarray  # E(t) = dF/dt, 1/s
    kind: str
    theoretical: float  # V/Q, s
    t10: float
    t50: float
    t90: float
    mean: float  # mean residence time, s
    peak: float  # time of the highest outlet concentration (pulse) or of the steepest rise (step)
    complete: float  # F at the end of the test: below about 0.98 the tank was not yet flushed
    pulse: float = 0.0  # s, length of the dose of a pulse test

    @property
    def baffling_factor(self) -> float:
        return self.t10 / self.theoretical

    @property
    def morrill(self) -> float:
        return self.t90 / self.t10 if self.t10 > 0 else math.nan

    def lines(self) -> list[str]:
        out = [
            f"Theoretical residence time V/Q = {self.theoretical:.4g} s.",
            f"T10 = {self.t10:.4g} s, T50 = {self.t50:.4g} s, T90 = {self.t90:.4g} s.",
            f"Baffling factor T10/(V/Q) = {self.baffling_factor:.2f} ({baffling_class(self.baffling_factor)}); "
            f"Morrill index T90/T10 = {self.morrill:.2f}.",
            f"Mean residence time {self.mean:.4g} s ({self.mean / self.theoretical:.2f} of V/Q).",
        ]
        if self.complete < 0.98:
            out.append(
                f"Only {100 * self.complete:.0f} % of the tracer had left by the end: the mean includes the "
                "washout still to come (extrapolated); run the test longer for a firmer T90."
            )
        return out

    def remaining(self, decay: float) -> float:
        """The share of a substance decaying at a first-order rate (1/s) that is left where the water leaves.

        In a steady flow it follows from the residence times alone: the integral of E(t) exp(-decay t).
        """
        k = float(decay)
        if k <= 0:
            return 1.0
        t = self.times
        if self.kind == "pulse":
            c = self.concentration
            share = float(np.trapezoid(c * np.exp(-k * t), t) / np.trapezoid(c, t))
            w = self.pulse
            return share * k * w / -math.expm1(-k * w) if w > 0 else share  # the dose took w to go in
        rest = 1.0 - self.cumulative
        share = 1.0 - k * float(np.trapezoid(rest * np.exp(-k * t), t))
        rate = _washout_rate(t, self.cumulative)
        if rate > 0:  # the tracer still in the tank decays as it washes out
            share -= k * float(rest[-1]) * math.exp(-k * float(t[-1])) / (k + rate)
        return share

    def rows(self) -> list[list[float]]:
        return [[float(t), float(c), float(f), float(e)]
                for t, c, f, e in zip(self.times, self.concentration, self.cumulative, self.density)]  # fmt: skip

    def write_csv(self, path: Path) -> None:
        from easyfoam.hydraulics import write_table

        write_table(path, ["time [s]", "outlet concentration [-]", "F [-]", "E [1/s]"], self.rows())


#: baffling factors of contact basins (US EPA, LT2 guidance) and what they stand for
BAFFLING = ((0.2, "unbaffled, mixed flow"), (0.4, "poor baffling"), (0.6, "average baffling"),
            (0.85, "superior baffling"), (math.inf, "near plug flow"))  # fmt: skip


def baffling_class(factor: float) -> str:
    return next(label for limit, label in BAFFLING if factor < limit)


def _crossing(times: np.ndarray, values: np.ndarray, level: float) -> float:
    above = np.flatnonzero(values >= level)
    if above.size == 0:
        return math.nan
    i = int(above[0])
    if i == 0:
        return float(times[0])
    t0, t1, v0, v1 = times[i - 1], times[i], values[i - 1], values[i]
    return float(t0 + (level - v0) * (t1 - t0) / (v1 - v0)) if v1 != v0 else float(t1)


def _washout_rate(t: np.ndarray, f: np.ndarray) -> float:
    """How fast the tracer still in the tank was washing out at the end of a step test (1/s; 0 if unknown).

    The last stage of a tracer test washes out like a mixed volume: 1 - F decays exponentially, at a
    rate fitted over the last quarter of the record.
    """
    remaining = 1.0 - f
    late = (t >= t[0] + 0.75 * (t[-1] - t[0])) & (remaining > 1e-6)
    if remaining[-1] <= 1e-4 or late.sum() < 3:
        return 0.0
    slope = float(np.polyfit(t[late], np.log(remaining[late]), 1)[0])
    return -slope if slope < 0 else 0.0


def _tail(t: np.ndarray, f: np.ndarray) -> float:
    """What the part of the tracer still in the tank adds to the mean residence time."""
    rate = _washout_rate(t, f)
    return float((1.0 - f[-1]) / rate) if rate > 0 else 0.0


def residence_times(times, concentration, kind: str, theoretical: float, pulse: float = 0.0) -> ResidenceTimes:
    """Analyse the outlet record of a step or pulse tracer test (inlet concentration 1)."""
    t = np.asarray(times, float)
    c = np.clip(np.asarray(concentration, float), 0.0, None)
    if t.size and t[0] > 0:  # OpenFOAM records from the first time step on; at 0 none has reached the outlet
        t, c = np.concatenate([[0.0], t]), np.concatenate([[0.0], c])
    if kind == "pulse":
        dose = np.trapezoid(c, t)
        if dose <= 0:
            raise ValueError("no tracer has reached the outlet yet")
        e = c / dose
        f = np.concatenate([[0.0], np.cumsum(0.5 * (e[1:] + e[:-1]) * np.diff(t))])
        complete = float(dose / pulse) if pulse > 0 else float(f[-1])
        mean = float(np.trapezoid(t * e, t)) - pulse / 2
        peak = float(t[int(np.argmax(c))])
    else:
        f = np.clip(c, 0.0, 1.0)
        e = np.gradient(f, t)
        complete = float(f[-1])
        mean = float(np.trapezoid(1.0 - f, t)) + _tail(t, f)
        peak = float(t[int(np.argmax(e))])
    return ResidenceTimes(
        times=t, concentration=c, cumulative=f, density=e, kind=kind, theoretical=theoretical,
        t10=_crossing(t, f, 0.1), t50=_crossing(t, f, 0.5), t90=_crossing(t, f, 0.9),
        mean=mean, peak=peak, complete=complete, pulse=pulse if kind == "pulse" else 0.0,
    )  # fmt: skip


def decay_lines(result: ResidenceTimes, project: Project, inlet: str) -> list[str]:
    """What the test says about each decaying tracer of the project: how much of it is left at the outlet."""
    bc = project.boundaries.get(inlet)
    out = []
    for tracer in project.tracers:
        if tracer.kind == "age" or tracer.decay <= 0:
            continue
        share = result.remaining(tracer.decay)
        dosed = bc.tracer_values.get(tracer.name, bc.tracer_value) if bc is not None else 1.0
        out.append(
            f"{tracer.name}, decaying at {tracer.decay * 3600:.3g} per hour: {100 * share:.1f} % is left at the "
            f"outlet ({share * dosed:.3g} of the {dosed:g} dosed)."
        )
    return out


def load_test(case_dir: Path) -> tuple[TestSettings, float, float] | None:
    """The tracer test last prepared in this case: (settings, V/Q in s, pulse length in s), or None."""
    try:
        data = json.loads((subcase(case_dir) / SETTINGS_FILE).read_text(encoding="utf-8"))
        pulse = float(data.get("pulse", 0.0))
        settings = TestSettings(data["inlet"], data["outlet"], data.get("kind", "step"),
                                float(data.get("duration", 0.0)), pulse)  # fmt: skip
        return settings, float(data["theoretical"]), pulse
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_test(case_dir: Path, outlet: str):
    """Times and outlet concentration recorded by a finished (or running) tracer test."""
    from easyfoam.foam.monitors import read_outlet_tracers

    found = read_outlet_tracers(subcase(case_dir)).get(outlet)
    if not found:
        raise ValueError("the tracer test has not recorded anything at the outlet yet")
    times, series = found
    return times, series[0]
