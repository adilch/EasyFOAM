"""Incremental parser for OpenFOAM solver logs.

Feed it one line at a time while the solver runs; it accumulates the series
the GUI plots (initial residuals, Courant number, continuity errors) and
notices the normal ``End`` marker or a ``FOAM FATAL ERROR`` block.
"""

from __future__ import annotations

import re

_NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
_TIME = re.compile(rf"^Time = {_NUM}s?\s*$")
_SOLVE = re.compile(rf"Solving for (\S+), Initial residual = {_NUM}, Final residual = {_NUM}")
_COURANT = re.compile(rf"^Courant Number mean: {_NUM} max: {_NUM}")
_CONTINUITY = re.compile(rf"continuity errors : sum local = {_NUM}, global = {_NUM}")
_EXEC = re.compile(rf"^ExecutionTime = {_NUM} s")
_PHASE = re.compile(rf"^Phase-1 volume fraction = {_NUM}")
_ERROR_MAX_LINES = 20


class LogParser:
    def __init__(self) -> None:
        self.times: list[float] = []
        #: field name -> [(time, initial residual)], first solve of each time step
        self.residuals: dict[str, list[tuple[float, float]]] = {}
        self.courant: list[tuple[float, float]] = []
        #: (time, sum local, global)
        self.continuity: list[tuple[float, float, float]] = []
        self.execution_time: float | None = None
        #: (time, share of the domain filled with water) for free-surface runs
        self.water_fraction: list[tuple[float, float]] = []
        self._phase_this_step = False
        self.finished = False
        self.error: str | None = None
        self._seen_this_step: set[str] = set()
        self._continuity_this_step = False
        self._error_lines: list[str] | None = None

    @property
    def time(self) -> float | None:
        return self.times[-1] if self.times else None

    def feed(self, line: str) -> None:
        line = line.rstrip("\r\n")

        if self._error_lines is not None:
            self._collect_error(line)
            return
        if "FOAM FATAL" in line:
            self._error_lines = [line.replace("-->", "").strip()]
            self.error = self._error_lines[0]
            return

        m = _TIME.match(line)
        if m:
            self.times.append(float(m.group(1)))
            self._seen_this_step.clear()
            self._continuity_this_step = False
            self._phase_this_step = False
            return

        m = _COURANT.match(line)
        if m:
            self.courant.append((float(m.group(1)), float(m.group(2))))
            return

        if line.strip() == "End":
            self.finished = True
            return

        m = _EXEC.match(line)
        if m:
            self.execution_time = float(m.group(1))
            return

        if not self.times:
            return
        now = self.times[-1]

        m = _PHASE.match(line)
        if m:
            if not self._phase_this_step:
                self._phase_this_step = True
                self.water_fraction.append((now, float(m.group(1))))
            return

        m = _SOLVE.search(line)
        if m:
            name = m.group(1)
            if name not in self._seen_this_step:
                self._seen_this_step.add(name)
                self.residuals.setdefault(name, []).append((now, float(m.group(2))))
            return

        m = _CONTINUITY.search(line)
        if m and not self._continuity_this_step:
            self._continuity_this_step = True
            self.continuity.append((now, float(m.group(1)), float(m.group(2))))

    def _collect_error(self, line: str) -> None:
        assert self._error_lines is not None
        text = line.strip()
        if text.startswith("FOAM aborting") or text.startswith("FOAM exiting"):
            self._error_lines = None  # block complete; keep self.error
            return
        if text and len(self.error.splitlines()) < _ERROR_MAX_LINES:
            self._error_lines.append(text)
            self.error = "\n".join(self._error_lines)
