"""The main window: workflow steps on the left, 3D view, residuals and log."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from easyfoam import __version__
from easyfoam.casegen.mesh import predicted_patches
from easyfoam.casegen.setup import parse_yplus, reference_speed
from easyfoam.examples import EXAMPLES
from easyfoam.external import open_in_paraview
from easyfoam.foam.boundaryfile import Patch, read_boundary
from easyfoam.gui.jobs import DetectThread, JobThread
from easyfoam.gui.panels import (
    BoundaryPanel,
    GeometryPanel,
    MeshPanel,
    PhysicsPanel,
    ResultsPanel,
    RunPanel,
)
from easyfoam.model import PROJECT_FILE, Project
from easyfoam.pipeline import JobResult, post_steps_for, prepare_mesh, prepare_run
from easyfoam.runtime import Runtime
from easyfoam.solvers import solver_spec

STEPS = ("Geometry", "Mesh", "Physics", "Boundaries", "Run", "Results")
EXAMPLE_LABELS = {
    "empty": "Empty project",
    "sphere": "Example: air flow past a sphere",
    "pipe": "Example: laminar flow in a pipe",
    "cavity": "Example: lid-driven cavity",
}
RESIDUAL_COLOURS = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#b279a2", "#72b7b2", "#9d755d", "#eeca3b"]
_CELLS = re.compile(r"^\s*cells:\s+(\d+)")
MAX_LOG_BLOCKS = 20000


class MainWindow(QMainWindow):
    def __init__(self, enable_3d: bool = True, detect: bool = True) -> None:
        super().__init__()
        self.case_dir: Path | None = None
        self.project: Project | None = None
        self.runtime: Runtime | None = None
        self.runtimes: list[Runtime] = []
        self.thread: JobThread | None = None
        self._results = None
        self._mesh_cells: int | None = None
        self._curves: dict = {}
        self._force_curves: dict = {}
        self._pending_field = ""
        self._ticks = 0

        self.resize(1400, 860)
        self._build_panels()
        self._build_centre(enable_3d)
        self._build_actions()
        self._set_project_open(False)
        self._update_title()

        self._save_timer = QTimer(self, singleShot=True, interval=800)
        self._save_timer.timeout.connect(self.save_project)
        self._view_timer = QTimer(self, singleShot=True, interval=350)
        self._view_timer.timeout.connect(self.refresh_view)
        self._pump = QTimer(self, interval=150)
        self._pump.timeout.connect(self._drain_job_output)

        self.runtime_label = QLabel("OpenFOAM: searching…" if detect else "OpenFOAM: not selected")
        self.statusBar().addPermanentWidget(self.runtime_label)
        self._detect_thread: DetectThread | None = None
        if detect:
            self.detect_runtimes()

    # ------------------------------------------------------------------ build

    def _build_panels(self) -> None:
        self.geometry_panel = GeometryPanel()
        self.mesh_panel = MeshPanel()
        self.physics_panel = PhysicsPanel()
        self.boundary_panel = BoundaryPanel()
        self.run_panel = RunPanel()
        self.results_panel = ResultsPanel()
        self.panels = [self.geometry_panel, self.mesh_panel, self.physics_panel,
                       self.boundary_panel, self.run_panel, self.results_panel]  # fmt: skip

        self.steps = QListWidget()
        self.steps.addItems(STEPS)
        font = QFont(self.steps.font())
        font.setPointSize(font.pointSize() + 1)
        self.steps.setFont(font)
        self.steps.setFixedHeight(self.steps.sizeHintForRow(0) * len(STEPS) + 8)
        self.stack = QStackedWidget()
        for panel in self.panels:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(panel)
            self.stack.addWidget(scroll)
        self.steps.currentRowChanged.connect(self._step_selected)

        self.geometry_panel.changed.connect(lambda: self._project_changed(shape=True))
        self.mesh_panel.changed.connect(lambda: self._project_changed(shape=True))
        self.physics_panel.changed.connect(lambda: self._project_changed(physics=True))
        self.boundary_panel.changed.connect(self._project_changed)
        self.run_panel.changed.connect(self._project_changed)
        self.mesh_panel.generate_requested.connect(self.generate_mesh)
        self.run_panel.run_requested.connect(self.run_solver)
        self.run_panel.stop_requested.connect(self.stop_job)
        self.results_panel.view_changed.connect(self.refresh_view)
        self.results_panel.refresh_requested.connect(self.reload_results)
        self.results_panel.paraview_requested.connect(self.open_paraview)
        self.results_panel.compute_requested.connect(self.compute_quantity)

    def _build_centre(self, enable_3d: bool) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 0, 6)
        left_layout.addWidget(self.steps)
        left_layout.addWidget(self.stack, 1)
        left.setMinimumWidth(430)

        self.viewer = None
        if enable_3d:
            from easyfoam.gui.viewer import Viewer

            self.viewer = Viewer()
            view_widget: QWidget = self.viewer
        else:
            view_widget = QLabel("3D view is switched off")
            view_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(MAX_LOG_BLOCKS)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.plot = None
        self.force_plot = None
        self.force_label = QLabel("Switch on the force monitor in the Run step to see drag and lift here.")
        self.bottom = QTabWidget()
        try:
            import pyqtgraph as pg

            pg.setConfigOptions(antialias=True, background="w", foreground="#27313b")
            self.plot = pg.PlotWidget()
            self.plot.setLogMode(y=True)
            self.plot.showGrid(x=True, y=True, alpha=0.25)
            self.plot.setLabel("left", "Initial residual")
            self.plot.setLabel("bottom", "Iteration / time")
            self.plot.addLegend(offset=(-10, 10))
            self.bottom.addTab(self.plot, "Residuals")
            self.force_plot = pg.PlotWidget()
            self.force_plot.showGrid(x=True, y=True, alpha=0.25)
            self.force_plot.setLabel("left", "Coefficient")
            self.force_plot.setLabel("bottom", "Iteration / time")
            self.force_plot.addLegend(offset=(-10, 10))
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(6, 4, 0, 0)
            holder_layout.addWidget(self.force_label)
            holder_layout.addWidget(self.force_plot, 1)
            self.bottom.addTab(holder, "Forces")
        except ImportError:  # the window still works without live plots
            pass
        self.bottom.addTab(self.log, "Log")

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(view_widget)
        right.addWidget(self.bottom)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 1)
        right.setSizes([600, 240])

        centre = QSplitter(Qt.Orientation.Horizontal)
        centre.addWidget(left)
        centre.addWidget(right)
        centre.setStretchFactor(0, 0)
        centre.setStretchFactor(1, 1)
        centre.setSizes([480, 920])
        self.setCentralWidget(centre)

    def _build_actions(self) -> None:
        def action(text, slot, shortcut=None) -> QAction:
            act = QAction(text, self)
            act.triggered.connect(slot)
            if shortcut:
                act.setShortcut(shortcut)
            return act

        self.new_action = action("New project…", lambda: self._new_project_dialog(), QKeySequence.StandardKey.New)
        self.open_action = action("Open project…", self._open_project_dialog, QKeySequence.StandardKey.Open)
        self.save_action = action("Save", self.save_project, QKeySequence.StandardKey.Save)
        self.mesh_action = action("Generate mesh", self.generate_mesh, "F5")
        self.run_action = action("Run", self.run_solver, "F6")
        self.stop_action = action("Stop", self.stop_job, "Shift+F6")
        self.paraview_action = action("Open in ParaView", self.open_paraview)
        self.folder_action = action("Show case folder", self.show_case_folder)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.new_action)
        examples = file_menu.addMenu("New from example")
        for key in ("sphere", "pipe", "cavity"):
            examples.addAction(EXAMPLE_LABELS[key], lambda k=key: self._new_project_dialog(k))
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.folder_action)
        file_menu.addSeparator()
        file_menu.addAction(action("Quit", self.close, QKeySequence.StandardKey.Quit))

        sim_menu = self.menuBar().addMenu("&Simulation")
        for act in (self.mesh_action, self.run_action, self.stop_action, self.paraview_action):
            sim_menu.addAction(act)

        self.runtime_menu = self.menuBar().addMenu("&OpenFOAM")
        self._fill_runtime_menu()

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(action("About EasyFOAM", self._about))

        bar = self.addToolBar("Main")
        bar.setMovable(False)
        for act in (self.new_action, self.open_action, None, self.mesh_action, self.run_action,
                    self.stop_action, None, self.paraview_action):  # fmt: skip
            bar.addSeparator() if act is None else bar.addAction(act)

    # ---------------------------------------------------------------- project

    def _set_project_open(self, is_open: bool) -> None:
        self.stack.setEnabled(is_open)
        self.steps.setEnabled(is_open)
        for act in (self.save_action, self.mesh_action, self.run_action, self.paraview_action, self.folder_action):
            act.setEnabled(is_open)
        self.stop_action.setEnabled(False)
        if not is_open and self.viewer:
            self.viewer.show_message("Create or open a project to begin  (File menu)")

    def _update_title(self) -> None:
        name = f"{self.project.name} — " if self.project else ""
        self.setWindowTitle(f"{name}EasyFOAM {__version__}")

    def new_project(self, case_dir: Path, example: str = "empty") -> None:
        case_dir = Path(case_dir)
        EXAMPLES[example](case_dir.name).save(case_dir)
        self.open_project(case_dir)

    def open_project(self, case_dir: Path) -> None:
        case_dir = Path(case_dir)
        self.project = Project.load(case_dir)
        self.case_dir = case_dir
        if self.project.runtime:
            self.runtime = Runtime.from_json(self.project.runtime)
        self._results = None
        self._mesh_cells = None
        self._set_project_open(True)
        self._update_title()
        self._show_runtime()
        self.log.clear()
        self._reset_plot()
        self._load_panels()
        self._load_residual_history()
        self._update_forces()
        self.reload_results(show=False)
        self.steps.setCurrentRow(0)
        self._step_selected(0)
        self.statusBar().showMessage(f"Opened {case_dir}", 5000)

    def _load_panels(self) -> None:
        self.geometry_panel.load(self.project, self.case_dir)
        self.mesh_panel.load(self.project, self.case_dir)
        self.physics_panel.load(self.project)
        self.run_panel.load(self.project)
        self.results_panel.project = self.project
        self._load_boundaries()

    def mesh_patches(self) -> list[Patch]:
        return read_boundary(self.case_dir) if self.case_dir else []

    def _load_boundaries(self) -> None:
        real = self.mesh_patches()
        self.boundary_panel.load(self.project, real or predicted_patches(self.project), from_mesh=bool(real))

    def save_project(self) -> None:
        if self.project is not None and self.case_dir is not None:
            self._save_timer.stop()
            self.project.save(self.case_dir)

    def _project_changed(self, shape: bool = False, physics: bool = False) -> None:
        self._save_timer.start()
        if shape:
            if not self.mesh_patches():
                self._load_boundaries()
            if self.current_step() in ("Geometry", "Mesh"):
                self._view_timer.start()
        if physics:
            self.run_panel.load(self.project)

    def _new_project_dialog(self, example: str | None = None) -> None:
        if example is None:
            labels = [EXAMPLE_LABELS[k] for k in ("empty", "sphere", "pipe", "cavity")]
            choice, ok = QInputDialog.getItem(self, "New project", "Start from", labels, 0, False)
            if not ok:
                return
            example = next(k for k, v in EXAMPLE_LABELS.items() if v == choice)
        folder = QFileDialog.getExistingDirectory(self, "Choose an empty folder for the new project")
        if not folder:
            return
        case_dir = Path(folder)
        if (case_dir / PROJECT_FILE).exists():
            self.open_project(case_dir)
            return
        if any(case_dir.iterdir()):
            answer = QMessageBox.question(
                self, "New project",
                f"{case_dir} is not empty. Create the project there anyway?\n"
                "Existing OpenFOAM files in it may be overwritten when you mesh or run.",
            )  # fmt: skip
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.new_project(case_dir, example)

    def _open_project_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open project folder")
        if not folder:
            return
        if not (Path(folder) / PROJECT_FILE).is_file():
            QMessageBox.information(
                self, "Open project",
                f"That folder has no {PROJECT_FILE}. Use File > New project to start one there.",
            )  # fmt: skip
            return
        self.open_project(Path(folder))

    def show_case_folder(self) -> None:
        if self.case_dir:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.case_dir)))

    # ---------------------------------------------------------------- runtime

    def detect_runtimes(self) -> None:
        self._detect_thread = DetectThread(self)
        self._detect_thread.found.connect(self._runtimes_found)
        self._detect_thread.start()

    def _runtimes_found(self, found: list) -> None:
        self.runtimes = list(found)
        if self.runtime is None and self.runtimes:
            self.runtime = self.runtimes[0]
        self._fill_runtime_menu()
        self._show_runtime()

    def _fill_runtime_menu(self) -> None:
        self.runtime_menu.clear()
        group = QActionGroup(self)
        known = list(self.runtimes)
        if self.runtime is not None and self.runtime not in known:
            known.insert(0, self.runtime)
        for rt in known:
            act = QAction(rt.label, self, checkable=True, checked=(rt == self.runtime))
            act.triggered.connect(lambda _checked, rt=rt: self._choose_runtime(rt))
            group.addAction(act)
            self.runtime_menu.addAction(act)
        if not known:
            self.runtime_menu.addAction("No OpenFOAM installation found").setEnabled(False)
        self.runtime_menu.addSeparator()
        self.runtime_menu.addAction("Search again", self.detect_runtimes)

    def _choose_runtime(self, runtime: Runtime) -> None:
        self.runtime = runtime
        if self.project is not None:
            self.project.runtime = runtime.to_json()
            self._save_timer.start()
        self._show_runtime()

    def _show_runtime(self) -> None:
        if hasattr(self, "runtime_label"):
            self.runtime_label.setText(
                f"OpenFOAM: {self.runtime.label}" if self.runtime else "OpenFOAM: not found"
            )

    # ------------------------------------------------------------------- jobs

    def current_step(self) -> str:
        row = self.steps.currentRow()
        return STEPS[row] if 0 <= row < len(STEPS) else ""

    def _step_selected(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        if STEPS[row] == "Boundaries" and self.project is not None:
            self._load_boundaries()
        if STEPS[row] == "Mesh" and self.project is not None:
            self.mesh_panel.load(self.project, self.case_dir)
        self.refresh_view()

    def _can_start(self) -> bool:
        if self.project is None or self.case_dir is None:
            return False
        if self.thread is not None:
            QMessageBox.information(self, "Busy", "Another task is still running. Stop it first.")
            return False
        if self.runtime is None:
            QMessageBox.warning(
                self, "OpenFOAM not found",
                "No OpenFOAM installation was found.\n\nOn Windows, install OpenFOAM inside WSL "
                "(Ubuntu) and choose OpenFOAM > Search again. See the README for the commands.",
            )  # fmt: skip
            return False
        return True

    def _start(self, name: str, steps, parse_step: str | None = None) -> None:
        self.save_project()
        self.log.appendPlainText(f"\n=== {name} — {self.runtime.label} ===")
        self.thread = JobThread(self.case_dir, self.runtime, name, steps, parse_step, parent=self)
        self.thread.step_started.connect(lambda step: self.statusBar().showMessage(f"{name}: {step}…"))
        self.thread.finished_with.connect(self._job_finished)
        self._set_running(True, f"{name} running…")
        self.thread.start()
        self._pump.start()

    def _set_running(self, running: bool, status: str = "") -> None:
        for act in (self.mesh_action, self.run_action, self.new_action, self.open_action):
            act.setEnabled(not running)
        self.mesh_panel.generate.setEnabled(not running)
        self.stop_action.setEnabled(running)
        self.run_panel.set_running(running, status)
        if status:
            self.statusBar().showMessage(status)

    def generate_mesh(self) -> None:
        if not self._can_start():
            return
        if self.mesh_patches() and QMessageBox.question(
            self, "Generate mesh", "This replaces the current mesh and deletes its results. Continue?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._results = None
        self._mesh_cells = None
        try:
            steps = prepare_mesh(self.case_dir, self.project)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Generate mesh", str(exc))
            return
        self.bottom.setCurrentWidget(self.log)
        self._start("mesh", steps)

    def run_solver(self) -> None:
        if not self._can_start():
            return
        self._results = None
        try:
            steps = prepare_run(self.case_dir, self.project)
        except (RuntimeError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Run", str(exc))
            return
        self._reset_plot()
        if self.plot is not None:
            self.bottom.setCurrentWidget(self.plot)
        self._start("run", steps, parse_step=self.project.physics.solver)

    def compute_quantity(self, function: str) -> None:
        """Compute a derived quantity (y+, vorticity, …) for the latest result."""
        if not self._can_start():
            return
        try:
            steps = post_steps_for(self.case_dir, self.project, function)
        except (RuntimeError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Compute", str(exc))
            return
        self._results = None
        self._pending_field = function
        self.bottom.setCurrentWidget(self.log)
        self._start("compute", steps)

    def _show_computed(self) -> None:
        function = self._pending_field
        on_walls = function in ("yPlus", "wallShearStress")
        self.results_panel.select_field(function, "surface" if on_walls else None)
        if function == "yPlus":
            log = self.case_dir / "log.yPlus"
            report = parse_yplus(log.read_text(errors="replace")) if log.is_file() else {}
            lines = [f"{patch}: {low:.3g} to {high:.3g}, mean {mean:.3g}"
                     for patch, (low, high, mean) in report.items()]  # fmt: skip
            if lines:
                self.results_panel.info.setText("y+ on walls\n" + "\n".join(lines))

    def stop_job(self) -> None:
        if self.thread is not None:
            self.statusBar().showMessage("Stopping…")
            self.thread.stop()

    def _drain_job_output(self) -> None:
        thread = self.thread
        if thread is None:
            return
        lines = []
        while thread.lines:
            line = thread.lines.popleft()
            match = _CELLS.match(line)
            if match:
                self._mesh_cells = int(match.group(1))
            lines.append(line)
        if lines:
            self.log.appendPlainText("\n".join(lines))
        if thread.name == "run":
            self._update_plot(thread.job.parser)
            self._ticks += 1
            if self._ticks % 7 == 0:
                self._update_forces()
            parser = thread.job.parser
            if parser.time is not None:
                steady = solver_spec(self.project.physics.solver).steady
                unit = "iteration" if steady else "time"
                self.run_panel.status.setText(
                    f"Running — {unit} {parser.time:g} of {self.project.run.end_time:g}"
                )

    def _job_finished(self, result) -> None:
        thread, self.thread = self.thread, None
        self._pump.stop()
        if thread is not None:
            self.thread = thread  # drain what is left with the normal code path
            self._drain_job_output()
            self.thread = None
            thread.wait(2000)
        name = thread.name if thread else "task"

        if isinstance(result, Exception):
            self._set_running(False, f"{name} could not start: {result}")
            QMessageBox.critical(self, name, str(result))
            return
        assert isinstance(result, JobResult)
        if result.stopped:
            self._set_running(False, f"{name} stopped.")
        elif not result.ok:
            reason = result.parser.error or "see the Log tab for the tool's message"
            self._set_running(False, f"{name} failed in step '{result.failed_step}'.")
            self.bottom.setCurrentWidget(self.log)
            QMessageBox.warning(self, f"{name} failed", f"Step '{result.failed_step}' failed.\n\n{reason}")
        elif name == "mesh":
            cells = f" ({self._mesh_cells:,} cells)" if self._mesh_cells else ""
            self._set_running(False, f"Mesh ready{cells}.")
        elif name == "compute":
            self._set_running(False, f"Computed {self._pending_field}.")
        else:
            self._set_running(False, "Run finished.")

        self._load_boundaries()
        self.reload_results(show=False)
        self._update_forces()
        if result.ok and name == "compute":
            self._show_computed()
        if result.ok and name == "run":
            self.steps.setCurrentRow(STEPS.index("Results"))
        self.refresh_view()

    # ------------------------------------------------------------------ plots

    def _reset_plot(self) -> None:
        self._curves = {}
        self._force_curves = {}
        if self.plot is not None:
            self.plot.clear()
        if self.force_plot is not None:
            self.force_plot.clear()

    def _update_forces(self) -> None:
        """Refresh the force-coefficient plot and the drag / lift read-out."""
        if self.force_plot is None or self.case_dir is None or self.project is None:
            return
        import pyqtgraph as pg

        from easyfoam.foam.coeffs import read_coefficients

        history = read_coefficients(self.case_dir)
        times = history.get("Time")
        if not times or "Cd" not in history:
            return
        for index, name in enumerate(("Cd", "Cl")):
            if name not in history:
                continue
            if name not in self._force_curves:
                pen = pg.mkPen(RESIDUAL_COLOURS[index], width=2)
                self._force_curves[name] = self.force_plot.plot(name=name, pen=pen)
            self._force_curves[name].setData(times, history[name])
        cd = history["Cd"][-1]
        cl = history["Cl"][-1] if "Cl" in history else 0.0
        speed = reference_speed(self.project, self.mesh_patches() or predicted_patches(self.project))
        pressure = 0.5 * self.project.physics.rho * speed**2 * self.project.forces.ref_area
        self.force_label.setText(
            f"Cd = {cd:.4g}    Cl = {cl:.4g}    drag = {cd * pressure:.4g} N    "
            f"lift = {cl * pressure:.4g} N    (at {times[-1]:g})"
        )

    def _load_residual_history(self) -> None:
        """Plot the residuals of the last run from its log file, if there is one."""
        log = self.case_dir / f"log.{self.project.physics.solver}"
        if not log.is_file():
            return
        from easyfoam.foam.logparser import LogParser

        parser = LogParser()
        try:
            with log.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    parser.feed(line)
        except OSError:
            return
        self._update_plot(parser)

    def _update_plot(self, parser) -> None:
        if self.plot is None:
            return
        import pyqtgraph as pg

        for name, points in list(parser.residuals.items()):
            points = [(t, r) for t, r in list(points) if r > 0]
            if not points:
                continue
            if name not in self._curves:
                colour = RESIDUAL_COLOURS[len(self._curves) % len(RESIDUAL_COLOURS)]
                self._curves[name] = self.plot.plot(name=name, pen=pg.mkPen(colour, width=2))
            xs, ys = zip(*points)
            self._curves[name].setData(list(xs), list(ys))

    # ------------------------------------------------------------------- view

    def _case_results(self):
        if self._results is None and self.case_dir is not None and self.mesh_patches():
            from easyfoam.results import CaseResults

            self._results = CaseResults(self.case_dir, self.project.name)
        return self._results

    def reload_results(self, show: bool = True) -> None:
        self._results = None
        times: list[float] = []
        fields: list[str] = []
        try:
            results = self._case_results()
            if results is not None:
                times = [t for t in results.times]
                fields = results.fields if any(t > 0 for t in times) else []
        except Exception as exc:  # a broken or half-written case must not take the window down
            self.statusBar().showMessage(f"Could not read results: {exc}", 8000)
        self.results_panel.set_available(times, fields)
        if show:
            self.refresh_view()

    def refresh_view(self) -> None:
        if self.viewer is None or self.project is None or self.case_dir is None:
            return
        step = self.current_step()
        try:
            has_mesh = bool(self.mesh_patches())
            if step == "Geometry" or not has_mesh:
                self.viewer.show_geometry(self.project, self.case_dir)
                return
            types = {p.name: p.type for p in self.mesh_patches()}
            results = self._case_results()
            if step == "Results" and self.results_panel.field.count():
                sel = self.results_panel.selection()
                data = results.read(sel["time"])
                self.viewer.show_results(data, types, sel["field"], sel["mode"], sel["normal"],
                                         sel["position"], sel["edges"], sel["time"])  # fmt: skip
            else:
                self.viewer.show_mesh(results.read(0.0 if 0.0 in results.times else None), types)
        except Exception as exc:
            self.statusBar().showMessage(f"3D view: {exc}", 8000)

    def open_paraview(self) -> None:
        if self.case_dir is None:
            return
        if not open_in_paraview(self.case_dir / f"{self.project.name}.foam"):
            QMessageBox.information(
                self, "ParaView",
                "ParaView was not found. Install it from paraview.org, then try again.",
            )  # fmt: skip

    # ------------------------------------------------------------------- misc

    def _about(self) -> None:
        QMessageBox.about(
            self, "About EasyFOAM",
            f"<b>EasyFOAM {__version__}</b><br>An open-source front-end for OpenFOAM.<br><br>"
            "Licensed under the GNU General Public License v3 or later.<br>"
            "Not affiliated with OpenCFD Ltd, the OpenFOAM Foundation or any commercial GUI vendor.<br>"
            "OPENFOAM® is a registered trademark of OpenCFD Ltd.",
        )  # fmt: skip

    def closeEvent(self, event) -> None:
        if self.thread is not None:
            answer = QMessageBox.question(self, "Quit", "A task is still running. Stop it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.thread.stop()
            self.thread.wait(5000)
        self.save_project()
        if self._detect_thread is not None:
            self._detect_thread.wait(3000)
        if self.viewer is not None:
            self.viewer.close_view()
        super().closeEvent(event)
