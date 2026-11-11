"""Background threads so meshing, solving and detection never freeze the window."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from easyfoam.pipeline import Job
from easyfoam.runtime import Runtime, Step, detect_runtimes


class JobThread(QThread):
    """Runs a :class:`~easyfoam.pipeline.Job`.

    Output lines are queued in ``lines`` (the window drains them on a timer,
    which keeps the UI responsive when a tool prints thousands of lines).
    """

    step_started = Signal(str)
    finished_with = Signal(object)  # JobResult or Exception

    def __init__(
        self,
        case_dir: Path,
        runtime: Runtime,
        name: str,
        steps: Sequence[Step],
        parse_step: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.lines: deque[str] = deque()
        self.job = Job(case_dir, runtime, name, steps, on_line=self.lines.append,
                       on_step=self._on_step, parse_step=parse_step)  # fmt: skip

    def _on_step(self, step: str) -> None:
        self.lines.append(f"━━━ {step} ━━━")
        self.step_started.emit(step)

    def run(self) -> None:
        try:
            result = self.job.run()
        except Exception as exc:  # reported to the user by the window
            result = exc
        self.finished_with.emit(result)

    def stop(self) -> None:
        self.job.stop()


class DetectThread(QThread):
    found = Signal(list)

    def run(self) -> None:
        self.found.emit(detect_runtimes())
