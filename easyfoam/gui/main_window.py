"""The main window: workflow steps on the left, 3D view, residuals and log."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from easyfoam import __version__
from easyfoam.casegen.mesh import predicted_patches
from easyfoam.casegen.setup import parse_yplus, reference_speed
from easyfoam.checks import project_issues, step_states
from easyfoam.examples import EXAMPLES
from easyfoam.external import open_in_paraview
from easyfoam.foam.boundaryfile import Patch, read_boundary
from easyfoam.geometry import safe_name
from easyfoam.gui import state
from easyfoam.gui.icons import icon
from easyfoam.gui.jobs import DetectThread, JobThread
from easyfoam.gui.layout import FoldingSplitter
from easyfoam.gui.panels import (
    BoundaryPanel,
    GeometryPanel,
    MeshPanel,
    PhysicsPanel,
    ResultsPanel,
    RunPanel,
)
from easyfoam.gui.sidebar import (
    COMPACT_WIDTH,
    DETAIL_ROLE,
    FULL_WIDTH,
    ICON_ROLE,
    ROW_HEIGHT,
    STATE_ROLE,
    STEP_ICONS,
    StepDelegate,
)
from easyfoam.gui.welcome import EXAMPLES as EXAMPLE_CARDS
from easyfoam.gui.welcome import SHOWN as EXAMPLES_SHOWN
from easyfoam.gui.welcome import NewProjectDialog, WelcomePage
from easyfoam.history import History
from easyfoam.model import PROJECT_FILE, Project
from easyfoam.pace import Pace, in_words, took
from easyfoam.pipeline import (
    JobResult,
    computed_times,
    post_steps_for,
    prepare_mesh,
    prepare_run,
    request_stop,
)
from easyfoam.results import add_cavitation_index
from easyfoam.runtime import Runtime
from easyfoam.solvers import solver_spec

STEPS = ("Geometry", "Mesh", "Physics", "Boundaries", "Run", "Results")
EXAMPLE_LABELS = {
    "empty": "Empty project",
    "sphere": "Example: air flow past a sphere",
    "pipe": "Example: laminar flow in a pipe",
    "weir": "Example: flow over a weir (free surface)",
    "dambreak": "Example: dam break (free surface)",
    "waves": "Example: waves in a flume (free surface)",
    "gate": "Example: lifting sluice gate (moving shape)",
    "floating": "Example: floating box (moved by the water)",
    "jump": "Example: hydraulic jump below a sluice gate",
    "tank": "Example: chlorine contact tank (water age, T10)",
    "ogee": "Example: ogee spillway crest at its design head",
    "basin": "Example: USBR Type III stilling basin",
    "cavity": "Example: lid-driven cavity",
}
MESH_MOTION_RESIDUALS = ("pcorr", "cellDisplacement")
BED_FIELDS = ("bedShearStress", "sedimentMobility")
NO_HYDRAULICS_TEXT = "Choose Long section, Pressure or Loads under Hydraulic results in the Results step."
NO_MOTION_TEXT ="Give a shape a motion in the Geometry step to follow it here."
RESIDUAL_COLOURS = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#b279a2", "#72b7b2", "#9d755d", "#eeca3b"]
_CELLS = re.compile(r"^\s*cells:\s+(\d+)")
MAX_LOG_BLOCKS = 20000
#: panel sizes when nothing is remembered: settings | view and plots, and view | plots and log
DEFAULT_LAYOUT = {"centre": [486, 810], "right": [600, 240]}
ALERT_AFTER = 20.0  # seconds: a task that takes longer is announced when it ends, if no one is looking


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
        self._probe_curves: dict = {}
        self._stop_requested = False
        self._flow_curves: dict = {}
        self._force_curves: dict = {}
        self._pending_field = ""
        self._ticks = 0
        self._pace = Pace()  # how fast the running task goes, for the time it still needs
        self._job_started = 0.0
        self._job_total: float | None = None  # the simulated time the task runs to
        self._tray: QSystemTrayIcon | None = None
        self.history = History()  # the set-up after each change, for undo and redo

        self.resize(1520, 900)
        self.setWindowIcon(icon("easyfoam"))
        self._build_panels()
        self._build_centre(enable_3d)
        self._build_actions()
        self.workspace.folded_changed.connect(self._settings_folded)
        self.right.folded_changed.connect(self._plots_folded)
        self._plots_folded(False)
        self.set_compact_steps(False)
        self._layout_applied = False  # the panels are sized once the workspace is first on screen
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
        self.time_left = QLabel("")  # how long the running task still needs, once its pace is known
        self.time_left.hide()
        self.statusBar().addPermanentWidget(self.time_left)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
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
        self.steps.setObjectName("steps")
        self.steps.addItems(STEPS)
        self.step_delegate = StepDelegate(self.steps)
        self.steps.setItemDelegate(self.step_delegate)
        self.steps.setMouseTracking(True)
        for row, name in enumerate(STEPS):
            self.steps.item(row).setData(ICON_ROLE, STEP_ICONS[name])
            self.steps.item(row).setData(STATE_ROLE, "todo")
            self.steps.item(row).setToolTip(name)
        self.steps.setFixedWidth(FULL_WIDTH)
        self.steps.setMinimumHeight(ROW_HEIGHT * len(STEPS) + 6)
        self.stack = QStackedWidget()
        for panel in self.panels:
            panel.fit_forms()
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
        self.run_panel.continue_requested.connect(self.continue_run)
        self.run_panel.tracer_test_requested.connect(self.run_tracer_test)
        self.geometry_panel.selection_changed.connect(self._highlight)
        self.geometry_panel.channel_requested.connect(self.build_channel)
        self.geometry_panel.terrain_requested.connect(self.bring_in_terrain)
        self.boundary_panel.selection_changed.connect(self._highlight)
        self.results_panel.view_changed.connect(self.refresh_view)
        self.results_panel.refresh_requested.connect(self.reload_results)
        self.results_panel.paraview_requested.connect(self.open_paraview)
        self.results_panel.compute_requested.connect(self.compute_quantity)
        self.results_panel.hydraulics_requested.connect(self.hydraulics)
        self.results_panel.export_requested.connect(lambda: self.export_table())

    def _build_centre(self, enable_3d: bool) -> None:
        # the workflow, full height, in its own column; it narrows to its icons
        self.steps_column = QWidget()
        steps_layout = QVBoxLayout(self.steps_column)
        steps_layout.setContentsMargins(8, 8, 0, 6)
        steps_layout.setSpacing(2)
        steps_layout.addWidget(self.steps, 1)
        self.compact_button = QToolButton()
        self.compact_button.setAutoRaise(True)
        self.compact_button.clicked.connect(lambda _checked=False: self.set_compact_steps(not self.step_delegate.compact))
        steps_layout.addWidget(self.compact_button, 0, Qt.AlignmentFlag.AlignLeft)

        # the settings of the chosen step; they fold away to make the 3D view wider
        panel_column = QWidget()
        left_layout = QVBoxLayout(panel_column)
        left_layout.setContentsMargins(8, 8, 0, 6)
        left_layout.addWidget(self.stack, 1)
        self.back_button = QPushButton(icon("arrow-left"), " Back")
        self.next_button = QPushButton("Next")
        self.next_button.setIcon(icon("arrow-right"))
        self.next_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # icon after the text
        self.back_button.clicked.connect(lambda: self._go(-1))
        self.next_button.clicked.connect(lambda: self._go(+1))
        self.fold_settings_button = QToolButton()
        self.fold_settings_button.setAutoRaise(True)
        self.fold_settings_button.setIcon(icon("panel-fold-left"))
        self.fold_settings_button.setToolTip(
            "Fold the settings away to make the 3D view wider (Ctrl+B). Click a step to bring them back."
        )
        self.fold_settings_button.clicked.connect(lambda _checked=False: self.workspace.set_folded(True))
        nav = QHBoxLayout()
        nav.addWidget(self.fold_settings_button)
        nav.addWidget(self.back_button)
        nav.addStretch(1)
        nav.addWidget(self.next_button)
        left_layout.addLayout(nav)
        panel_column.setMinimumWidth(380)

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
        self.probe_plot = None
        self.flow_plot = None
        self.flow_label = QLabel("List boundaries under Discharge in the Run step to record the flow through them.")
        self.force_plot = None
        self.force_label = QLabel("Switch on the force monitor in the Run step to see drag and lift here.")
        self.motion_plot = None
        self.rotation_plot = None
        self.hydraulics_view = None
        self._table = None  # the numbers behind the last hydraulic plot
        self._shear_wanted = False
        self.motion_label = QLabel(NO_MOTION_TEXT)
        for label in (self.flow_label, self.force_label, self.motion_label):
            label.setWordWrap(True)  # a long line would otherwise set how narrow the plots (and the window) can be
        self._motion_curves: dict = {}
        self._rotation_curves: dict = {}
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
            self.force_plot.getAxis("left").enableAutoSIPrefix(False)  # plain numbers in the stated unit
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
            self.probe_plot = pg.PlotWidget()
            self.probe_plot.getAxis("left").enableAutoSIPrefix(False)  # plain numbers in the stated unit
            self.probe_plot.showGrid(x=True, y=True, alpha=0.25)
            self.probe_plot.setLabel("left", "Pressure p/ρ at the probes [m²/s²]")
            self.probe_plot.setLabel("bottom", "Iteration / time")
            self.probe_plot.addLegend(offset=(-10, 10))
            self.bottom.addTab(self.probe_plot, "Probes")
            self.flow_plot = pg.PlotWidget()
            self.flow_plot.getAxis("left").enableAutoSIPrefix(False)  # plain numbers in the stated unit
            self.flow_plot.showGrid(x=True, y=True, alpha=0.25)
            self.flow_plot.setLabel("left", "Discharge [m³/s], positive = leaving")
            self.flow_plot.setLabel("bottom", "Iteration / time")
            self.flow_plot.addLegend(offset=(-10, 10))
            flow_holder = QWidget()
            flow_layout = QVBoxLayout(flow_holder)
            flow_layout.setContentsMargins(6, 4, 0, 0)
            flow_layout.addWidget(self.flow_label)
            flow_layout.addWidget(self.flow_plot, 1)
            self.bottom.addTab(flow_holder, "Discharge")
            self.motion_plot = pg.PlotWidget()
            self.rotation_plot = pg.PlotWidget()
            for plot, label in (
                (self.motion_plot, "Moved [m]"),
                (self.rotation_plot, "Turned [°]"),
            ):
                plot.getAxis("left").enableAutoSIPrefix(False)  # plain numbers in the stated unit
                plot.showGrid(x=True, y=True, alpha=0.25)
                plot.setLabel("left", label)
                plot.setLabel("bottom", "Time [s]")
                plot.addLegend(offset=(-10, 10))
            self.rotation_plot.hide()  # shown once a floating body turns
            motion_holder = QWidget()
            motion_layout = QVBoxLayout(motion_holder)
            motion_layout.setContentsMargins(6, 4, 0, 0)
            motion_layout.addWidget(self.motion_label)
            motion_plots = QHBoxLayout()
            motion_plots.addWidget(self.motion_plot, 1)
            motion_plots.addWidget(self.rotation_plot, 1)
            motion_layout.addLayout(motion_plots, 1)
            self.bottom.addTab(motion_holder, "Motion")
            self.hydraulics_view = pg.GraphicsLayoutWidget()
            self.hydraulics_view.setBackground("w")
            self.upper_plot = self.hydraulics_view.addPlot(row=0, col=0)
            self.lower_plot = self.hydraulics_view.addPlot(row=1, col=0)
            for plot in (self.upper_plot, self.lower_plot):
                plot.getAxis("left").enableAutoSIPrefix(False)
                plot.showGrid(x=True, y=True, alpha=0.25)
            self.hydraulics_label = QLabel(NO_HYDRAULICS_TEXT)
            self.hydraulics_label.setWordWrap(True)
            hydraulics_holder = QWidget()
            hydraulics_layout = QVBoxLayout(hydraulics_holder)
            hydraulics_layout.setContentsMargins(6, 4, 0, 0)
            hydraulics_layout.addWidget(self.hydraulics_label)
            hydraulics_layout.addWidget(self.hydraulics_view, 1)
            self.bottom.addTab(hydraulics_holder, "Hydraulics")
        except ImportError:  # the window still works without live plots
            pass
        self.bottom.addTab(self.log, "Log")
        # the plots and the log fold down to their tab headers; a click on a tab opens them again
        self.fold_plots_button = QToolButton()
        self.fold_plots_button.setAutoRaise(True)
        self.fold_plots_button.clicked.connect(lambda _checked=False: self.right.toggle())
        self.bottom.setCornerWidget(self.fold_plots_button, Qt.Corner.TopRightCorner)
        self.bottom.tabBarClicked.connect(lambda _index: self.right.set_folded(False))

        self.right = FoldingSplitter(Qt.Orientation.Vertical, fold=1, open_size=DEFAULT_LAYOUT["right"][1],
                                     folded_size=lambda: self.bottom.tabBar().sizeHint().height())  # fmt: skip
        self.right.addWidget(view_widget)
        self.right.addWidget(self.bottom)
        self.right.setStretchFactor(0, 3)
        self.right.setStretchFactor(1, 1)
        self.right.setSizes(DEFAULT_LAYOUT["right"])

        self.workspace = FoldingSplitter(Qt.Orientation.Horizontal, fold=0, open_size=DEFAULT_LAYOUT["centre"][0])
        self.workspace.addWidget(panel_column)
        self.workspace.addWidget(self.right)
        self.workspace.setStretchFactor(0, 0)
        self.workspace.setStretchFactor(1, 1)
        self.workspace.setSizes(DEFAULT_LAYOUT["centre"])
        self.steps.itemClicked.connect(lambda _item: self.workspace.set_folded(False))

        self.workspace_page = QWidget()
        page_layout = QHBoxLayout(self.workspace_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(self.steps_column)
        page_layout.addWidget(self.workspace, 1)
        self.welcome = WelcomePage()
        self.welcome.new_requested.connect(self._new_project_dialog)
        self.welcome.open_requested.connect(self._open_project_dialog)
        self.welcome.recent_requested.connect(self._open_recent)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.welcome)
        self.pages.addWidget(self.workspace_page)
        self.setCentralWidget(self.pages)

    def _build_actions(self) -> None:
        def action(text, slot, icon_name=None, shortcut=None, tip=None) -> QAction:
            act = QAction(text, self)
            act.triggered.connect(slot)
            if icon_name:
                act.setIcon(icon(icon_name))
            if shortcut:
                act.setShortcut(shortcut)
            if tip:
                act.setToolTip(tip)
                act.setStatusTip(tip)
            return act

        self.new_action = action("New", lambda: self._new_project_dialog(), "file-plus",
                                 QKeySequence.StandardKey.New, "Create a new project")  # fmt: skip
        self.open_action = action("Open", self._open_project_dialog, "folder-open",
                                  QKeySequence.StandardKey.Open, "Open an existing project folder")  # fmt: skip
        self.save_action = action("Save", self.save_project, "save", QKeySequence.StandardKey.Save,
                                  "Save the project (it is also saved automatically)")  # fmt: skip
        self.mesh_action = action("Mesh", self.generate_mesh, "mesh", "F5", "Generate the mesh (F5)")
        self.run_action = action("Run", lambda: self.run_solver(), "play", "F6",
                                 "Run the simulation from the start (F6)")  # fmt: skip
        self.continue_action = action("Continue", self.continue_run, "step-forward", "F7",
                                      "Continue from the latest saved result (F7)")  # fmt: skip
        self.stop_action = action("Stop", self.stop_job, "square", "Shift+F6",
                                  "Stop: once to save and finish, twice to end at once")  # fmt: skip
        self.paraview_action = action("ParaView", self.open_paraview, "external-link", None,
                                      "Open the case in ParaView")  # fmt: skip
        self.folder_action = action("Show case folder", self.show_case_folder, "folder")
        self.close_action = action("Close project", self.close_project, "log-out")

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.new_action)
        examples = file_menu.addMenu(icon("book-open"), "New from example")
        for key in EXAMPLES_SHOWN:
            examples.addAction(icon(EXAMPLE_CARDS[key][0]), EXAMPLE_LABELS[key],
                               lambda k=key: self._new_project_dialog(k))  # fmt: skip
        file_menu.addAction(self.open_action)
        self.recent_menu = file_menu.addMenu(icon("history"), "Open recent")
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.folder_action)
        file_menu.addAction(self.close_action)
        file_menu.addSeparator()
        file_menu.addAction(action("Quit", self.close, None, QKeySequence.StandardKey.Quit))

        self.undo_action = action("Undo", lambda _checked=False: self.undo(), "undo", QKeySequence.StandardKey.Undo,
                                  "Undo the last change to the set-up (Ctrl+Z)")  # fmt: skip
        self.redo_action = action("Redo", lambda _checked=False: self.redo(), "redo", QKeySequence.StandardKey.Redo,
                                  "Redo the change you undid (Ctrl+Y)")  # fmt: skip
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        sim_menu = self.menuBar().addMenu("&Simulation")
        for act in (self.mesh_action, self.run_action, self.continue_action, self.stop_action):
            sim_menu.addAction(act)
        sim_menu.addSeparator()
        sim_menu.addAction(self.paraview_action)

        view_menu = self.menuBar().addMenu("&View")
        # the panels: checked = shown. (A slot gets the action's "checked" first, so values come after it.)
        self.compact_action = action("Workflow steps as icons only", lambda checked: self.set_compact_steps(checked),
                                     "chevrons-left", "Ctrl+Shift+B",
                                     "Narrow the list of steps to its icons, to make more room (Ctrl+Shift+B)")  # fmt: skip
        self.settings_action = action("Settings of the step", lambda checked: self.workspace.set_folded(not checked),
                                      "panel-fold-left", "Ctrl+B",
                                      "Show the settings, or fold them away to widen the 3D view (Ctrl+B)")  # fmt: skip
        self.plots_action = action("Plots and log", lambda checked: self.right.set_folded(not checked),
                                   "panel-fold-down", "Ctrl+J",
                                   "Show the plots and the log, or fold them down to their tabs (Ctrl+J)")  # fmt: skip
        for act, checked in ((self.compact_action, False), (self.settings_action, True), (self.plots_action, True)):
            act.setCheckable(True)
            act.setChecked(checked)
            view_menu.addAction(act)
        view_menu.addAction(action("Reset the layout", lambda _checked=False: self.reset_layout(), "layout", None,
                                   "Put every panel back at its first size"))  # fmt: skip
        view_menu.addSeparator()
        self.view_actions: dict[str, QAction] = {}
        for key, text, shortcut in (
            ("fit", "Fit everything", "Ctrl+0"), ("iso", "Three-quarter view", "Ctrl+1"),
            ("+x", "Look along +X", "Ctrl+2"), ("-x", "Look along −X", "Ctrl+3"),
            ("+y", "Look along +Y", "Ctrl+4"), ("-y", "Look along −Y", "Ctrl+5"),
            ("+z", "Look along +Z", "Ctrl+6"), ("-z", "Look along −Z", "Ctrl+7"),
        ):  # fmt: skip
            act = action(text, lambda _checked=False, k=key: self._view(k), None, shortcut)
            view_menu.addAction(act)
            self.view_actions[key] = act
        view_menu.addSeparator()
        self.tab_actions: dict[str, QAction] = {}
        for name, icon_name in (("Residuals", "activity"), ("Forces", "gauge"),
                                ("Probes", "crosshair"), ("Log", "terminal")):  # fmt: skip
            act = action(f"Show {name.lower()}", lambda _checked=False, n=name: self._show_tab(n), icon_name)
            view_menu.addAction(act)
            self.tab_actions[name] = act

        self.runtime_menu = self.menuBar().addMenu("&OpenFOAM")
        self._fill_runtime_menu()

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(action("Getting started", self._getting_started, "circle-help",
                                   QKeySequence.StandardKey.HelpContents))  # fmt: skip
        help_menu.addAction(action("About EasyFOAM", self._about, "info"))

        bar = self.addToolBar("Main")
        bar.setMovable(False)
        bar.setIconSize(QSize(22, 22))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        for act in (self.new_action, self.open_action, self.save_action, self.undo_action, self.redo_action, None,
                    self.mesh_action, self.run_action, self.continue_action, self.stop_action, None,
                    self.paraview_action):  # fmt: skip
            bar.addSeparator() if act is None else bar.addAction(act)
        self._fill_recent_menu()
        self._update_undo()

    # --------------------------------------------------------------- history

    def _snapshot(self) -> str:
        """The set-up as text, for undo and redo (which OpenFOAM it runs with is not part of it)."""
        data = self.project.to_dict()
        data.pop("runtime", None)
        return json.dumps(data, sort_keys=True)

    def undo(self) -> None:
        """Put the set-up back as it was before the last change."""
        self._step_history(back=True)

    def redo(self) -> None:
        """Make the change that was undone again."""
        self._step_history(back=False)

    def _step_history(self, back: bool) -> None:
        if self.project is None or self.case_dir is None:
            return
        self.history.record(self._snapshot())  # a change still waiting to be saved is a step of its own
        snapshot = self.history.step_back() if back else self.history.step_forward()
        if snapshot is None:
            return
        runtime = self.project.runtime
        self.project = Project.from_dict(json.loads(snapshot))
        self.project.runtime = runtime
        self._save_timer.stop()
        self.project.save(self.case_dir)
        row = self.steps.currentRow()
        self._load_panels()
        self.steps.setCurrentRow(row)
        self._step_selected(row)
        self.refresh_status()
        self._update_undo()
        self.statusBar().showMessage("Undid the last change." if back else "Made the change again.", 4000)

    def _update_undo(self) -> None:
        is_open = self.project is not None
        self.undo_action.setEnabled(is_open and self.history.can_undo)
        self.redo_action.setEnabled(is_open and self.history.can_redo)

    # ----------------------------------------------------------------- layout

    def set_compact_steps(self, compact: bool) -> None:
        """Show the workflow steps as icons only, or with their names and summaries."""
        self.step_delegate.compact = compact
        self.steps.setFixedWidth(COMPACT_WIDTH if compact else FULL_WIDTH)
        self.compact_button.setIcon(icon("chevrons-right" if compact else "chevrons-left"))
        self.compact_button.setToolTip("Show the names of the steps (Ctrl+Shift+B)" if compact
                                       else "Show only the icons of the steps, to make more room (Ctrl+Shift+B)")  # fmt: skip
        self._check(self.compact_action, compact)
        self.steps.doItemsLayout()
        self.steps.viewport().update()

    @staticmethod
    def _check(action: QAction, checked: bool) -> None:
        """Tick or untick a menu entry without running it again."""
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def _settings_folded(self, folded: bool) -> None:
        self._check(self.settings_action, not folded)

    def _plots_folded(self, folded: bool) -> None:
        self._check(self.plots_action, not folded)
        self.fold_plots_button.setIcon(icon("panel-fold-up" if folded else "panel-fold-down"))
        self.fold_plots_button.setToolTip("Bring back the plots and the log (Ctrl+J)" if folded
                                          else "Fold the plots and the log down to their tabs (Ctrl+J)")  # fmt: skip

    def reset_layout(self) -> None:
        """Every panel back as it started: the steps with their names, the settings and the plots open."""
        self.set_compact_steps(False)
        self.workspace.set_folded(False)
        self.right.set_folded(False)
        self.workspace.open_size, self.right.open_size = DEFAULT_LAYOUT["centre"][0], DEFAULT_LAYOUT["right"][1]
        self.workspace.setSizes(DEFAULT_LAYOUT["centre"])  # in proportion: the splitter scales them to its size
        self.right.setSizes(DEFAULT_LAYOUT["right"])

    def layout_state(self) -> dict:
        return {"compact_steps": self.step_delegate.compact, "centre": self.workspace.layout_state(),
                "right": self.right.layout_state()}  # fmt: skip

    def _apply_layout(self) -> None:
        """Size the panels as remembered (or as at first), once the workspace is on screen at its real size.

        Sizes given to a hidden splitter are lost when it first grows to the window's size.
        """
        if self._layout_applied or not self.isVisible() or self.pages.currentWidget() is not self.workspace_page:
            return
        self._layout_applied = True
        saved = state.load_layout()
        self.set_compact_steps(bool(saved.get("compact_steps")))
        self.workspace_page.resize(self.pages.size())
        self.workspace_page.layout().activate()
        self.workspace.setSizes(DEFAULT_LAYOUT["centre"])  # in proportion to the space there is
        self.right.setSizes(DEFAULT_LAYOUT["right"])
        for splitter, key in ((self.workspace, "centre"), (self.right, "right")):
            if isinstance(saved.get(key), dict):
                splitter.restore_layout(saved[key])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_layout()

    def _remember_layout(self) -> None:
        """Keep the panel sizes for next time, if they are on screen now (otherwise they mean nothing)."""
        if self.isVisible() and self.pages.currentWidget() is self.workspace_page:
            state.save_layout(self.layout_state())

    # ---------------------------------------------------------------- project

    def _set_project_open(self, is_open: bool) -> None:
        self.pages.setCurrentWidget(self.workspace_page if is_open else self.welcome)
        for act in (self.save_action, self.mesh_action, self.run_action, self.paraview_action,
                    self.folder_action, self.close_action):  # fmt: skip
            act.setEnabled(is_open)
        self.stop_action.setEnabled(False)
        self.continue_action.setEnabled(False)
        if is_open:
            self._apply_layout()
        else:
            self.welcome.set_recent(state.load_recent())

    def notify(self, title: str, text: str, level: str = "info") -> None:
        """Tell the user something in a dialog (tests replace this to stay non-blocking)."""
        box = {"error": QMessageBox.critical, "warning": QMessageBox.warning}.get(level, QMessageBox.information)
        box(self, title, text)

    def _update_title(self) -> None:
        name = f"{self.project.name} — " if self.project else ""
        self.setWindowTitle(f"{name}EasyFOAM {__version__}")

    def new_project(self, case_dir: Path, example: str = "empty") -> None:
        case_dir = Path(case_dir)
        EXAMPLES[example](case_dir.name).save(case_dir)
        self.open_project(case_dir)

    def create_project(self, name: str, parent: Path, example: str = "empty") -> None:
        """Create ``parent/name`` as a new project folder and open it."""
        name = name.strip()
        if not name:
            raise ValueError("the project needs a name")
        case_dir = Path(parent) / name
        if case_dir.exists() and any(case_dir.iterdir()):
            raise ValueError(f"{case_dir} already exists and is not empty")
        EXAMPLES[example](safe_name(name)).save(case_dir)
        state.remember_projects_folder(Path(parent))
        self.open_project(case_dir)

    def close_project(self) -> None:
        if self.thread is not None:
            self.notify("Close project", "A task is still running. Stop it first.")
            return
        self.save_project()
        self._remember_layout()
        self.project, self.case_dir, self._results = None, None, None
        self.history.reset(None)
        self._update_undo()
        self._set_project_open(False)
        self._update_title()

    def _open_recent(self, folder: str) -> None:
        if (Path(folder) / PROJECT_FILE).is_file():
            self.open_project(Path(folder))
        else:
            self.notify("Open project", f"{folder} is no longer an EasyFOAM project.")
            self._fill_recent_menu()

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = state.load_recent()
        for folder in recent:
            path = Path(folder)
            self.recent_menu.addAction(icon("folder"), f"{path.name}    ({path.parent})",
                                       lambda f=folder: self._open_recent(f))  # fmt: skip
        if not recent:
            self.recent_menu.addAction("No recent projects").setEnabled(False)

    def open_project(self, case_dir: Path) -> None:
        case_dir = Path(case_dir)
        self.project = Project.load(case_dir)
        self.case_dir = case_dir
        self.history.reset(self._snapshot())
        self._update_undo()
        if self.project.runtime:
            self.runtime = Runtime.from_json(self.project.runtime)
        self._results = None
        self._mesh_cells = self._logged_mesh_cells()
        state.add_recent(case_dir)
        self._fill_recent_menu()
        self._set_project_open(True)
        self._update_title()
        self._show_runtime()
        self.log.clear()
        self._reset_plot()
        self._load_panels()
        self._load_residual_history()
        self._update_forces()
        self.reload_results(show=False)
        if solver_spec(self.project.physics.solver).multiphase and self.results_panel.field.count():
            self.results_panel.select_field("U", "water")  # free-surface cases open on the water surface
        self.steps.setCurrentRow(0)
        self._step_selected(0)
        self.refresh_status()
        self.statusBar().showMessage(f"Opened {case_dir}", 5000)

    def _load_panels(self) -> None:
        self.geometry_panel.load(self.project, self.case_dir)
        self.mesh_panel.load(self.project, self.case_dir)
        self.physics_panel.load(self.project)
        self.run_panel.load(self.project, self.case_dir)
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
            if self.history.record(self._snapshot()):
                self._update_undo()

    def _project_changed(self, shape: bool = False, physics: bool = False) -> None:
        self._save_timer.start()
        if shape:
            if not self.mesh_patches():
                self._load_boundaries()
            if self.current_step() in ("Geometry", "Mesh"):
                self._view_timer.start()
        if physics:
            self.run_panel.load(self.project, self.case_dir)
        self.refresh_status()

    def _logged_mesh_cells(self) -> int | None:
        """Cell count of the current mesh, taken from the checkMesh log."""
        log = self.case_dir / "log.checkMesh"
        try:
            found = [m.group(1) for line in log.read_text(errors="replace").splitlines()
                     if (m := _CELLS.match(line))]  # fmt: skip
        except OSError:
            return None
        return int(found[-1]) if found and self.mesh_patches() else None

    def refresh_status(self) -> None:
        """Update the step badges, the pre-run checklist and what can be continued."""
        if self.project is None or self.case_dir is None:
            return
        real = self.mesh_patches()
        patches = real or predicted_patches(self.project)
        times = computed_times(self.case_dir)
        states = step_states(self.project, patches, bool(real), self._mesh_cells, [0.0, *times] if times else [])
        for row, name in enumerate(STEPS):
            item = self.steps.item(row)
            item.setData(STATE_ROLE, states[name].state)
            item.setData(DETAIL_ROLE, states[name].detail)
            item.setToolTip(f"{name}: {states[name].detail}")
        self.run_panel.show_issues(project_issues(self.project, patches, bool(real)))
        can_continue = bool(times) and bool(real) and self.thread is None
        self.continue_action.setEnabled(can_continue)
        self.run_panel.continue_button.setEnabled(can_continue)
        self.steps.viewport().update()

    def _new_project_dialog(self, example: str | None = None) -> None:
        dialog = NewProjectDialog(state.projects_folder(), example or "empty", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, location, chosen = dialog.values()
        try:
            self.create_project(name, location, chosen)
        except (ValueError, OSError) as exc:
            self.notify("New project", str(exc), "error")

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
        self._update_nav()
        if self.viewer is not None:
            self.viewer._highlighted = self._selected_name()  # drawn by the refresh below
        if STEPS[row] == "Boundaries" and self.project is not None:
            self._load_boundaries()
        if STEPS[row] == "Mesh" and self.project is not None:
            self.mesh_panel.load(self.project, self.case_dir)
        self.refresh_view()

    def _go(self, delta: int) -> None:
        row = self.steps.currentRow() + delta
        if 0 <= row < len(STEPS):
            self.steps.setCurrentRow(row)

    def _update_nav(self) -> None:
        row = self.steps.currentRow()
        self.back_button.setEnabled(row > 0)
        last = row >= len(STEPS) - 1
        self.next_button.setEnabled(not last)
        self.next_button.setText("Next" if last else f"Next: {STEPS[row + 1]}")

    def _highlight(self, name: str) -> None:
        """Mark the shape or boundary selected in the list, on the steps where that helps."""
        if self.viewer is not None:
            self.viewer.highlight(name if self.current_step() in ("Geometry", "Boundaries") else "")
            if self.current_step() == "Geometry":
                self._view_timer.start()  # the handles belong to the selected shape

    def _selected_name(self) -> str:
        step = self.current_step()
        chosen = None
        if step == "Geometry":
            chosen = self.geometry_panel.selected()
        elif step == "Boundaries":
            chosen = self.boundary_panel.selected()
        return chosen.name if chosen is not None else ""

    def _view(self, key: str) -> None:
        if self.viewer is not None:
            self.viewer.fit() if key == "fit" else self.viewer.set_view(key)

    def _show_tab(self, name: str) -> None:
        self.right.set_folded(False)  # asked for: show it, even if the plots were folded away
        for index in range(self.bottom.count()):
            if self.bottom.tabText(index) == name:
                self.bottom.setCurrentIndex(index)

    def show_progress(self, done: float | None, total: float | None, left: float | None = None) -> None:
        """Show how far a run is and, once its pace is known, how long it still needs (``None`` hides the bar)."""
        if done is None or not total:
            self.progress.hide()
            self.time_left.hide()
            return
        self.progress.setValue(max(0, min(100, int(100 * done / total))))
        self.progress.show()
        self.time_left.setText(f"{in_words(left)} left" if left is not None else "estimating the time left…")
        self.time_left.show()

    def _point_dragged(self, point: list[float]) -> None:
        """The user dragged the point-inside-the-fluid ball in the 3D view."""
        self.project.mesh.location_in_mesh = [round(c, 6) for c in point]
        self.mesh_panel.load(self.project, self.case_dir)
        self._save_timer.start()

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

    def _start(self, name: str, steps, parse_step: str | None = None, case_dir: Path | None = None,
               total: float | None = None) -> None:  # fmt: skip
        self.save_project()
        self._stop_requested = False
        self._pace.reset()
        self._job_started, self._job_total = time.monotonic(), total
        self.log.appendPlainText(f"\n=== {name} — {self.runtime.label} ===")
        self.thread = JobThread(case_dir or self.case_dir, self.runtime, name, steps, parse_step, parent=self)
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
        self.continue_action.setEnabled(False)
        self.run_panel.continue_button.setEnabled(False)
        if not running:
            self.show_progress(None, None)
            self.refresh_status()

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

    def run_solver(self, resume: bool = False) -> None:
        """Run from the start, or carry on from the latest saved result."""
        if not self._can_start():
            return
        patches = self.mesh_patches()
        blocking = [i.text for i in project_issues(self.project, patches, bool(patches))
                    if i.level in ("error", "todo")]  # fmt: skip
        if blocking:
            self.notify("Not ready to run",
                        "Please sort this out first:\n\n" + "\n".join(f"•  {text}" for text in blocking), "error")  # fmt: skip
            return
        self._results = None
        try:
            steps = prepare_run(self.case_dir, self.project, resume=resume)
        except (RuntimeError, OSError, ValueError) as exc:
            self.notify("Run", str(exc), "warning")
            return
        if not resume:
            self._reset_plot()
        if self.plot is not None:
            self.bottom.setCurrentWidget(self.plot)
        self._start("run", steps, parse_step=self.project.physics.solver, total=self.project.run.end_time)

    def continue_run(self) -> None:
        self.run_solver(resume=True)

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
        if function == "wallShearStress" and self._shear_wanted:
            self._shear_wanted = False
            self.results_panel.select_field("bedShearStress", "surface")
            return
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
        """Stop the running task.

        A solver run is first asked to save its state and finish; a second
        Stop (or any other task) is ended at once.
        """
        thread = self.thread
        if thread is None:
            return
        graceful = thread.name == "run" and not self._stop_requested and self.case_dir is not None
        if graceful and request_stop(self.case_dir):
            self._stop_requested = True
            self.statusBar().showMessage("Saving the current state… (Stop again to end at once)")
            self.run_panel.status.setText("Saving the current state… Press Stop again to end at once.")
            return
        self.statusBar().showMessage("Stopping…")
        thread.stop()

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
        parser = thread.job.parser
        left = None
        if parser.time is not None and self._job_total:
            self._pace.add(parser.time)
            left = self._pace.seconds_left(self._job_total)
            self.show_progress(parser.time, self._job_total, left)
        if thread.name == "run":
            self._update_plot(parser)
            self._ticks += 1
            if self._ticks % 7 == 0:
                self._update_forces()
            if parser.time is not None and not self._stop_requested:
                steady = solver_spec(self.project.physics.solver).steady
                unit = "iteration" if steady else "time"
                water = (
                    f" — water fills {100 * parser.water_fraction[-1][1]:.2f} % of the domain"
                    if parser.water_fraction
                    else ""
                )
                eta = f" — {in_words(left)} left" if left is not None else ""
                self.run_panel.status.setText(
                    f"Running — {unit} {parser.time:g} of {self.project.run.end_time:g}{water}{eta}"
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
        seconds = time.monotonic() - self._job_started
        spent = took(seconds)

        if isinstance(result, Exception):
            self._set_running(False, f"{name} could not start: {result}")
            QMessageBox.critical(self, name, str(result))
            return
        assert isinstance(result, JobResult)
        if result.stopped:
            message = f"{name.capitalize()} stopped after {spent}."
        elif not result.ok:
            message = f"{name.capitalize()} failed in step '{result.failed_step}' after {spent}."
        elif name == "mesh":
            cells = f" ({self._mesh_cells:,} cells)" if self._mesh_cells else ""
            message = f"Mesh ready{cells} in {spent}."
        elif name == "compute":
            message = f"Computed {self._pending_field} in {spent}."
        elif name == "tracer test":
            message = f"Tracer test finished in {spent}."
        elif self._stop_requested:
            message = "Stopped; the current state was saved. Use Continue to carry on."
        else:
            message = f"Run finished in {spent}."
        self._set_running(False, message)
        self._announce(message, result.ok, seconds)
        if not result.ok and not result.stopped:
            reason = result.parser.error or "see the Log tab for the tool's message"
            self.bottom.setCurrentWidget(self.log)
            QMessageBox.warning(self, f"{name} failed", f"Step '{result.failed_step}' failed.\n\n{reason}")

        self._load_boundaries()
        self.reload_results(show=False)
        self._update_forces()
        if result.ok and name == "compute":
            self._show_computed()
        if result.ok and name == "tracer test":
            self.hydraulics("residence")
        if result.ok and name == "run":
            if solver_spec(self.project.physics.solver).multiphase:
                self.results_panel.select_field("U", "water")  # the water surface, coloured by speed
            self.steps.setCurrentRow(STEPS.index("Results"))
        self.refresh_view()

    def _announce(self, text: str, ok: bool, seconds: float) -> None:
        """Tell someone who has turned to something else that a long task has ended."""
        if seconds < ALERT_AFTER or self.isActiveWindow():
            return
        QApplication.alert(self, 0)  # the taskbar button flashes until the window is looked at
        tray = self._tray_icon()
        if tray is not None:
            kind = QSystemTrayIcon.MessageIcon.Information if ok else QSystemTrayIcon.MessageIcon.Warning
            tray.showMessage("EasyFOAM", text, kind, 10000)
            QTimer.singleShot(15000, tray.hide)

    def _tray_icon(self) -> QSystemTrayIcon | None:
        """The icon in the notification area that carries the message, while it is shown."""
        if self._tray is None:
            if not (QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()):
                return None
            self._tray = QSystemTrayIcon(icon("easyfoam"), self)
            self._tray.setToolTip("EasyFOAM")
            self._tray.messageClicked.connect(self._bring_to_front)
            self._tray.activated.connect(lambda _reason: self._bring_to_front())
        self._tray.show()
        return self._tray

    def _bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------ plots

    def _reset_plot(self) -> None:
        self._curves = {}
        self._force_curves = {}
        if self.plot is not None:
            self.plot.clear()
        if self.force_plot is not None:
            self.force_plot.clear()
        self._probe_curves = {}
        if self.probe_plot is not None:
            self.probe_plot.clear()
        self._flow_curves = {}
        if self.flow_plot is not None:
            self.flow_plot.clear()
        self._motion_curves = {}
        self._rotation_curves = {}
        if self.motion_plot is not None:
            self.motion_plot.clear()
            self.rotation_plot.clear()
            self.rotation_plot.hide()
            self.motion_label.setText(NO_MOTION_TEXT)

    def _update_forces(self) -> None:
        """Refresh the force-coefficient plot and the drag / lift read-out."""
        self._update_probes()
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

    def _update_probes(self) -> None:
        """Refresh the probe plot and the discharge plot.

        In free-surface runs the probe points act as gauges and the plot shows the water depth
        there; otherwise it shows the pressure.
        """
        if self.case_dir is None or self.project is None:
            return
        import pyqtgraph as pg

        from easyfoam.foam.monitors import read_discharge, read_water_levels
        from easyfoam.foam.probes import read_probes
        from easyfoam.solvers import SOLVERS

        if self.probe_plot is not None:
            spec = SOLVERS.get(self.project.physics.solver)
            if spec is not None and spec.multiphase:
                times, series = read_water_levels(self.case_dir)
                label, name = "Water depth at the gauges [m]", "gauge"
            else:
                times, series = read_probes(self.case_dir).get("p", ([], []))
                label, name = "Pressure p/ρ at the probes [m²/s²]", "probe"
            self.probe_plot.setLabel("left", label)
            for index, values in enumerate(series):
                if index not in self._probe_curves:
                    pen = pg.mkPen(RESIDUAL_COLOURS[index % len(RESIDUAL_COLOURS)], width=2)
                    self._probe_curves[index] = self.probe_plot.plot(name=f"{name} {index + 1}", pen=pen)
                self._probe_curves[index].setData(times, values)

        if self.flow_plot is not None:
            latest = []
            for index, (patch, (times, values)) in enumerate(read_discharge(self.case_dir).items()):
                if patch not in self._flow_curves:
                    pen = pg.mkPen(RESIDUAL_COLOURS[index % len(RESIDUAL_COLOURS)], width=2)
                    self._flow_curves[patch] = self.flow_plot.plot(name=patch, pen=pen)
                self._flow_curves[patch].setData(times, values)
                latest.append(f"{patch}: {values[-1]:.4g} m³/s")
            if latest:
                self.flow_label.setText("    ".join(latest) + f"    (at {times[-1]:g})")

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

    def _update_motion(self, parser) -> None:
        """Refresh the Motion tab: where each moving shape is, and how far a floating body has turned.

        A floating body is followed from what the solver reports; a shape with a set motion is
        drawn from its settings, at the times the run has reached.
        """
        if self.motion_plot is None or self.project is None:
            return
        import pyqtgraph as pg

        from easyfoam.casegen.motion import displacement_at, moving_shapes

        def draw(plot, curves, name, times, values):
            if name not in curves:
                pen = pg.mkPen(RESIDUAL_COLOURS[len(curves) % len(RESIDUAL_COLOURS)], width=2)
                curves[name] = plot.plot(name=name, pen=pen)
            curves[name].setData(times, values)

        notes = []
        for shape in moving_shapes(self.project):
            turned: list[list[float]] = []
            if shape.motion.kind == "floating":
                track = list(parser.body_positions.get(shape.name, []))
                if not track:
                    continue
                times = [t for t, _ in track]
                start = track[0][1]
                moved = [[p[axis] - start[axis] for axis in range(3)] for _, p in track]
                rotations = list(parser.body_rotations.get(shape.name, []))[: len(track)]
                turned = [angles for _, angles in rotations]
                centre = ", ".join(f"{c:.4g}" for c in track[-1][1])
                notes.append(f"{shape.name}: centre at ({centre}) m")
            else:
                times = list(parser.times)
                if not times:
                    continue
                moved = [displacement_at(shape.motion, t) for t in times]
                notes.append(f"{shape.name}: moved ({', '.join(f'{c:.4g}' for c in moved[-1])}) m")
            for axis, letter in enumerate("xyz"):
                values = [m[axis] for m in moved]
                name = f"{shape.name} {letter}"
                if name in self._motion_curves or max(abs(v) for v in values) > 1e-9:
                    draw(self.motion_plot, self._motion_curves, name, times, values)
            for axis, word in enumerate(("roll", "pitch", "yaw")):
                values = [angles[axis] for angles in turned]
                name = f"{shape.name} {word}"
                if values and (name in self._rotation_curves or max(abs(v) for v in values) > 1e-6):
                    draw(self.rotation_plot, self._rotation_curves, name, times[: len(values)], values)
        if notes:
            self.motion_label.setText("    ".join(notes) + f"    (at {parser.times[-1]:g} s)")
        self.rotation_plot.setVisible(bool(self._rotation_curves))

    def _update_plot(self, parser) -> None:
        if self.plot is None:
            return
        import pyqtgraph as pg

        self._update_motion(parser)
        for name, points in list(parser.residuals.items()):
            if name.startswith(MESH_MOTION_RESIDUALS):
                continue  # bookkeeping of a moving mesh, not a sign of how well the flow is solved
            points = [(t, r) for t, r in list(points) if r > 0]
            if not points:
                continue
            if name not in self._curves:
                colour = RESIDUAL_COLOURS[len(self._curves) % len(RESIDUAL_COLOURS)]
                self._curves[name] = self.plot.plot(name=name, pen=pg.mkPen(colour, width=2))
            xs, ys = zip(*points)
            self._curves[name].setData(list(xs), list(ys))

    # ------------------------------------------------------------------- view

    def _results_dir(self) -> Path:
        """The folder whose results are shown: the flow run, or the tracer test that followed it."""
        from easyfoam.tracertest import subcase

        test = subcase(self.case_dir)
        if self.results_panel.source.currentData() == "tracer-test" and (test / "system").is_dir():
            return test
        return self.case_dir

    def _case_results(self):
        if self._results is None and self.case_dir is not None and self.mesh_patches():
            from easyfoam.results import CaseResults

            self._results = CaseResults(self._results_dir(), self.project.name)
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
                if fields and solver_spec(self.project.physics.solver).multiphase and {"p", "U"} <= set(fields):
                    fields = [*fields, "cavitationIndex"]  # computed here from pressure and speed
                if "wallShearStress" in fields:
                    fields = [*fields, *BED_FIELDS]  # computed here from the shear stress on the walls
        except Exception as exc:  # a broken or half-written case must not take the window down
            self.statusBar().showMessage(f"Could not read results: {exc}", 8000)
        self.results_panel.set_available(times, fields)
        from easyfoam.tracertest import subcase

        self.results_panel.show_source_choice(bool(self.case_dir) and (subcase(self.case_dir) / "system").is_dir())
        walls = [p.name for p in self.mesh_patches() if p.type == "wall"] if self.case_dir else []
        shapes = {s.name for s in self.project.shapes} if self.project else set()
        walls.sort(key=lambda name: (name.split("_")[0] not in shapes, name))  # the structures first
        free_surface = bool(self.project) and solver_spec(self.project.physics.solver).multiphase
        self.results_panel.set_structures(walls, free_surface and bool(fields))
        if show:
            self.refresh_view()

    def refresh_view(self) -> None:
        if self.viewer is None or self.project is None or self.case_dir is None:
            return
        step = self.current_step()
        try:
            has_mesh = bool(self.mesh_patches())
            if step == "Geometry" or not has_mesh:
                handles = None
                selected = self.geometry_panel.selected()
                if step == "Geometry" and selected is not None and self.geometry_panel.handles.isChecked():
                    handles = (selected, self.geometry_panel)  # move and resize it with the mouse
                self.viewer.show_geometry(
                    self.project, self.case_dir, self._point_dragged if step == "Mesh" else None, handles
                )
                return
            types = {p.name: p.type for p in self.mesh_patches()}
            results = self._case_results()
            if step == "Results" and self.results_panel.field.count():
                sel = self.results_panel.selection()
                data = results.read(sel["time"])
                if sel["field"] in BED_FIELDS:
                    self._add_bed_shear(data)
                if sel["field"] == "cavitationIndex":
                    ph = self.project.physics
                    lowest = add_cavitation_index(data.internal, ph.rho, ph.ambient_pressure, ph.vapour_pressure)
                    if lowest is not None:
                        verdict = (
                            "cavitation damage is likely" if lowest < 0.2
                            else "cavitation may start" if lowest < 1.8
                            else "no cavitation risk"
                        )  # fmt: skip
                        self.results_panel.info.setText(
                            f"Lowest cavitation index in the water: {lowest:.3g} ({verdict}).\n"
                            "Below about 0.2 surfaces get damaged; above about 1.8 there is no risk. "
                            "The colour scale stops at 20."
                        )
                self.viewer.show_results(data, types, sel["field"], sel["mode"], sel["normal"],
                                         sel["position"], sel["edges"], sel["time"])  # fmt: skip
            else:
                self.viewer.show_mesh(results.read(0.0 if 0.0 in results.times else None), types)
        except Exception as exc:
            self.statusBar().showMessage(f"3D view: {exc}", 8000)

    # ------------------------------------------------------------- hydraulics

    def hydraulics(self, kind: str) -> None:
        """Work out a hydraulic result for the saved time chosen in the Results step."""
        records = {"rating": self._rating, "residence": self._residence}  # from what the runs recorded as they went
        results = None
        if kind not in records:
            results = self._case_results() if self.project else None
            if results is None or not results.times:
                self.notify("Hydraulic results", "There are no results yet. Run the simulation first.")
                return
        elif self.project is None or self.case_dir is None:
            return
        if kind == "shear":
            self._bed_shear()
            return
        time = self.results_panel.time.currentData()
        try:
            if kind in records:
                records[kind]()
            elif kind == "long":
                self._long_section(results, time)
            elif kind == "pressure":
                self._pressure(results, time)
            elif kind == "loads":
                self._loads(results, time)
        except (ValueError, KeyError) as exc:
            self.notify("Hydraulic results", str(exc), "warning")
            return
        self.results_panel.export_button.setEnabled(self._table is not None)
        self._show_tab("Hydraulics")

    def _plots_ready(self, upper: str, lower: str | None, bottom: str):
        import pyqtgraph as pg

        for plot in (self.upper_plot, self.lower_plot):
            plot.clear()
            if plot.legend is not None:
                plot.legend.scene().removeItem(plot.legend)
                plot.legend = None
        self.upper_plot.addLegend(offset=(-10, 10))
        self.upper_plot.setLabel("left", upper)
        self.upper_plot.setLabel("bottom", bottom)
        self.lower_plot.setVisible(lower is not None)
        if lower is not None:
            self.lower_plot.setLabel("left", lower)
            self.lower_plot.setLabel("bottom", bottom)
            self.lower_plot.setXLink(self.upper_plot)
        return pg

    def _long_section(self, results, time) -> None:
        from easyfoam import hydraulics as hy

        count = self.results_panel.average.value()
        chosen = [t for t in results.times if 0 < t <= time + 1e-9][-count:] or [time]
        sections = [hy.long_section(results.read(t), self.project, self.case_dir, time=t) for t in chosen]
        section = hy.average_sections(sections)
        self._table = section
        lines = hy.summary(section)
        self.results_panel.hydraulics_info.setText("\n".join(lines))
        when = f"at {time:g} s" if len(chosen) == 1 else f"averaged from {chosen[0]:g} to {chosen[-1]:g} s"
        self.hydraulics_label.setText(f"Long section {when}. " + lines[0])
        if self.hydraulics_view is None:
            return
        pg = self._plots_ready("Level [m]", "Froude number", "Chainage [m]")
        s = section.chainage
        floor = float(min(np.nanmin(section.bed), self.project.mesh.base.min[2]))
        bed = self.upper_plot.plot(s, section.bed, pen=pg.mkPen("#8d6e4a", width=2), name="bed",
                                   fillLevel=floor, brush=pg.mkBrush(141, 110, 74, 90))  # fmt: skip
        water = self.upper_plot.plot(s, section.water_level, pen=pg.mkPen("#1f77b4", width=2), name="water level")
        self.upper_plot.addItem(pg.FillBetweenItem(bed, water, brush=pg.mkBrush(31, 119, 180, 60)))
        self.upper_plot.plot(s, section.energy_level, name="energy line",
                             pen=pg.mkPen("#d62728", width=1.5, style=Qt.PenStyle.DashLine))  # fmt: skip
        n, width = self._bed_manning()
        if n:  # a rough bed: compare with a 1D backwater calculation using the same Manning's n
            profile = hy.backwater(section, n, width)
            if np.isfinite(profile).sum() > 2:
                self.upper_plot.plot(s, profile, name=f"1D profile, n = {n:.3g}",
                                     pen=pg.mkPen("#2ca02c", width=1.5, style=Qt.PenStyle.DotLine))  # fmt: skip
        self.lower_plot.plot(s, section.froude, pen=pg.mkPen("#2563eb", width=2))
        self.lower_plot.addItem(pg.InfiniteLine(1.0, angle=0, pen=pg.mkPen("#888", style=Qt.PenStyle.DashLine),
                                                label="critical", labelOpts={"position": 0.95}))  # fmt: skip
        for jump in hy.find_jumps(section):
            for at, text in ((jump.toe, "jump"), (jump.end, "")):
                self.upper_plot.addItem(pg.InfiniteLine(at, pen=pg.mkPen("#9467bd", style=Qt.PenStyle.DotLine),
                                                        label=text, labelOpts={"position": 0.9}))  # fmt: skip
        for control in hy.find_controls(section):
            self.upper_plot.addItem(pg.InfiniteLine(control.chainage, pen=pg.mkPen("#2ca02c", style=Qt.PenStyle.DotLine),
                                                    label="critical", labelOpts={"position": 0.8}))  # fmt: skip

    def _bed_manning(self) -> tuple[float, float | None]:
        """Manning's n of the bed (0 if it is smooth) and the channel width if its sides are walls."""
        from easyfoam.model import manning_from_ks, roughness_height

        base = self.project.mesh.base
        bed = self.project.boundary_for(base.faces["zMin"].name, base.faces["zMin"].type)
        ks = roughness_height(bed)
        if ks <= 0:
            return 0.0, None
        n = bed.manning if bed.roughness == "manning" else manning_from_ks(ks)
        side = base.faces["yMin"]
        walls = self.project.boundary_for(side.name, side.type).kind == "wall"
        return n, (base.max[1] - base.min[1]) if walls else None

    def _pressure(self, results, time) -> None:
        from easyfoam import hydraulics as hy

        name = self.results_panel.structure.currentText()
        data = results.read(time)
        if name not in data.patches:
            raise ValueError(f"there is no boundary called '{name}' in the results")
        profile = hy.pressure_profile(data.patches[name], self.project)
        self._table = profile
        lowest = int(np.nanargmin(profile.head))
        text = (
            f"Pressure along {name} at {time:g} s: lowest pressure head {profile.head[lowest]:.3g} m at "
            f"x = {profile.x[lowest]:.3g} m, z = {profile.z[lowest]:.3g} m"
            + (" (below atmospheric)." if profile.head[lowest] < 0 else ".")
        )
        self.results_panel.hydraulics_info.setText(text)
        self.hydraulics_label.setText(text)
        if self.hydraulics_view is None:
            return
        pg = self._plots_ready("Pressure head [m of water]", None, "Distance along the surface [m]")
        self.upper_plot.plot(profile.distance, profile.head, pen=pg.mkPen("#2563eb", width=2), name=name)
        self.upper_plot.addItem(pg.InfiniteLine(0.0, angle=0, pen=pg.mkPen("#888", style=Qt.PenStyle.DashLine),
                                                label="atmospheric", labelOpts={"position": 0.95}))  # fmt: skip

    def _loads(self, results, time) -> None:
        from easyfoam import hydraulics as hy

        name = self.results_panel.structure.currentText()
        point = self.results_panel.chosen_point()
        times = [t for t in results.times if t > 0]
        history, chosen = [], None
        for t in times:
            data = results.read(t)
            if name not in data.patches:
                raise ValueError(f"there is no boundary called '{name}' in the results")
            loads = hy.structure_loads([data.patches[name]], self.project, point)
            history.append((t, loads))
            if t == time:
                chosen = loads
        chosen = chosen or history[-1][1]
        per = chosen.width or 1.0
        unit = "kN/m" if chosen.width else "kN"
        self._table = hy.Table(
            f"Loads on {name}",
            ["time [s]", f"force along the flow [{unit}]", f"force across [{unit}]", f"vertical force [{unit}]",
             f"moment about the flow axis [{unit}·m]", f"overturning moment [{unit}·m]", f"moment about z [{unit}·m]"],
            [[t, *(loads.force / per / 1000), *(loads.moment / per / 1000)] for t, loads in history],
        )  # fmt: skip
        lines = [f"Loads on {name} at {time:g} s (pressure only; friction is usually below 1 %):", *chosen.lines()]
        self.results_panel.hydraulics_info.setText("\n".join(lines))
        self.hydraulics_label.setText(" ".join(lines[:2]))
        if self.hydraulics_view is None:
            return
        pg = self._plots_ready(f"Force [{unit}]", f"Overturning moment [{unit}·m]", "Time [s]")
        ts = [t for t, _ in history]
        self.upper_plot.plot(ts, [h.force[0] / per / 1000 for _, h in history], name="along the flow",
                             pen=pg.mkPen("#2563eb", width=2), symbol="o", symbolSize=5)  # fmt: skip
        self.upper_plot.plot(ts, [h.force[2] / per / 1000 for _, h in history], name="vertical (up +)",
                             pen=pg.mkPen("#f58518", width=2), symbol="o", symbolSize=5)  # fmt: skip
        self.lower_plot.plot(ts, [h.moment[1] / per / 1000 for _, h in history],
                             pen=pg.mkPen("#54a24b", width=2), symbol="o", symbolSize=5)  # fmt: skip

    def build_channel(self) -> None:
        """Ask for the section, slope and centreline of a channel, then build it."""
        if self.project is None:
            return
        from easyfoam.gui.channel_dialog import ChannelDialog

        dialog = ChannelDialog(self.project.channel, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_channel(dialog.channel())

    def apply_channel(self, channel) -> None:
        """Make the project model a channel: its mesh, the water in it at the start, its boundaries."""
        from easyfoam import channel as chm

        try:
            done = chm.use_channel(self.project, channel)
        except ValueError as exc:
            self.notify("Channel", str(exc), "warning")
            return
        self._load_panels()
        self._project_changed(shape=True, physics=True)
        if self.current_step() == "Geometry":
            self.refresh_view()
        what = "; ".join(done)
        self.notify("Channel", "The channel is set up" + (f": {what}" if what else "") +
                    ". Generate its mesh in the Mesh step.")  # fmt: skip

    def bring_in_terrain(self) -> None:
        """Read a survey file and model the flow over that ground."""
        if self.project is None or self.case_dir is None:
            return
        from easyfoam.gui.terrain_dialog import TerrainDialog

        dialog = TerrainDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                ground = dialog.ground()
            except ValueError as exc:
                self.notify("Terrain", str(exc), "warning")
                return
            self.apply_terrain(ground, **dialog.settings())

    def apply_terrain(self, ground, cell_size: float, water_level: float | None, top: float | None = None,
                      discharge: float = 1.0) -> None:  # fmt: skip
        """Model the flow over a ground: its solid, the base mesh above it, the water and the boundaries."""
        from easyfoam import terrain as tr

        try:
            done = tr.use_terrain(self.project, self.case_dir, ground, cell_size, water_level, top, discharge)
        except (ValueError, OSError) as exc:
            self.notify("Terrain", str(exc), "warning")
            return
        self._load_panels()
        self._project_changed(shape=True, physics=True)
        if self.current_step() == "Geometry":
            self.refresh_view()
        self.notify("Terrain", "The ground is in: " + "; ".join(done) + ". Generate the mesh in the Mesh step.")

    def run_tracer_test(self) -> None:
        """Feed a tracer into the finished steady flow and follow it to the outlet (its own case folder)."""
        if not self._can_start():
            return
        from easyfoam import tracertest as tt
        from easyfoam.results import CaseResults

        try:
            settings = self.run_panel.test_settings()
            flow = CaseResults(self.case_dir, self.project.name)
            if not [t for t in flow.times if t > 0]:
                raise ValueError("run the flow first: the tracer test starts from its result")
            volume, inflow = tt.volume_and_flow(flow.read(flow.times[-1]), self.project, [settings.inlet])
            if inflow <= 0:
                raise ValueError(f"no water enters through {settings.inlet} in the result")
            residence = volume / inflow
            target, steps = tt.prepare(self.case_dir, self.project, settings, residence)
        except (ValueError, RuntimeError, OSError) as exc:
            self.notify("Tracer test", str(exc), "warning")
            return
        self._test = (settings, residence, settings.pulse or residence / 50.0)
        self.run_panel.test_status.setText(
            f"Water volume {volume:.4g} m³, inflow {inflow:.4g} m³/s: theoretical residence time V/Q = "
            f"{residence:.4g} s. Following the tracer for {settings.duration or 3 * residence:.4g} s."
        )
        self._start("tracer test", steps, parse_step="pimpleFoam", case_dir=target,
                    total=settings.duration or 3 * residence)  # fmt: skip

    def _residence(self) -> None:
        from easyfoam import tracertest as tt

        test = getattr(self, "_test", None) or tt.load_test(self.case_dir)  # also after reopening the project
        if test is None:
            raise ValueError("run a tracer test first (Run step)")
        settings, residence, pulse = test
        times, concentration = tt.read_test(self.case_dir, settings.outlet)
        result = tt.residence_times(times, concentration, settings.kind, residence, pulse)
        self._table = result
        lines = [f"Tracer test ({settings.kind}) from {settings.inlet} to {settings.outlet}:", *result.lines(),
                 *tt.decay_lines(result, self.project, settings.inlet)]  # fmt: skip
        self.results_panel.hydraulics_info.setText("\n".join(lines))
        self.hydraulics_label.setText(" ".join(lines[2:4]))
        if self.hydraulics_view is None:
            return
        pg = self._plots_ready("Share of the tracer [-]", "E(t) [1/s]", "Time [s]")
        self.upper_plot.plot(result.times, result.cumulative, name="F(t): has left",
                             pen=pg.mkPen("#2563eb", width=2))  # fmt: skip
        if settings.kind == "pulse":
            self.upper_plot.plot(result.times, result.concentration, name="outlet concentration",
                                 pen=pg.mkPen("#f58518", width=1.5))  # fmt: skip
        for at, label in ((result.t10, "T10"), (result.theoretical, "V/Q")):
            if np.isfinite(at):
                self.upper_plot.addItem(pg.InfiniteLine(at, pen=pg.mkPen("#888", style=Qt.PenStyle.DashLine),
                                                        label=label, labelOpts={"position": 0.9}))  # fmt: skip
        self.lower_plot.plot(result.times, result.density, pen=pg.mkPen("#54a24b", width=2))

    def _rating(self) -> None:
        from easyfoam import hydraulics as hy

        points = hy.rating_curve(self.project, self.case_dir)
        if not points:
            raise ValueError("the run has not reached the end of the first discharge yet")
        self._table = hy.Table(
            "Rating curve", hy.RATING_HEADER,
            [[p.discharge, p.level, p.head, p.outflow, p.coefficient, p.discharge_coefficient, p.drift,
              1.0 if p.steady else 0.0] for p in points],
        )  # fmt: skip
        lines = ["Rating curve (head at the gauge over the crest; Q = C·B·H^1.5):"]
        for p in points:
            note = "" if p.steady else "  (not settled: hold it longer)"
            lines.append(f"Q {p.discharge:.4g} m³/s: head {p.head:.3g} m, C = {p.coefficient:.3g}, "
                         f"Cd = {p.discharge_coefficient:.3g}{note}")  # fmt: skip
        self.results_panel.hydraulics_info.setText("\n".join(lines))
        self.hydraulics_label.setText(lines[0] + " " + "; ".join(line.split(":")[0] for line in lines[1:]))
        if self.hydraulics_view is None:
            return
        pg = self._plots_ready("Head over the crest [m]", "Weir coefficient C [m^0.5/s]", "Discharge [m³/s]")
        q = [p.discharge for p in points]
        self.upper_plot.plot(q, [p.head for p in points], name="measured", pen=pg.mkPen("#2563eb", width=2),
                             symbol="o", symbolSize=7)  # fmt: skip
        self.lower_plot.plot(q, [p.coefficient for p in points], pen=pg.mkPen("#f58518", width=2),
                             symbol="o", symbolSize=7)  # fmt: skip

    def _bed_shear(self) -> None:
        results = self._case_results()
        if "wallShearStress" in results.fields:
            self.results_panel.select_field("bedShearStress", "surface")
            return
        self._shear_wanted = True
        self.compute_quantity("wallShearStress")

    def _add_bed_shear(self, data) -> None:
        from easyfoam import hydraulics as hy

        d50 = self.results_panel.d50.value() / 1000.0
        physics = self.project.physics
        critical = hy.critical_shear_stress(d50, rho_water=physics.rho) if d50 > 0 else None
        largest = 0.0
        for surface in data.patches.values():
            found = hy.add_bed_shear(surface, self.project, critical)
            largest = max(largest, found or 0.0)
        if critical:
            self.results_panel.info.setText(
                f"Largest shear stress in the water: {largest:.3g} Pa. A bed of {d50 * 1000:g} mm grains starts to "
                f"move above {critical:.3g} Pa (Shields): sediment mobility above 1 means the bed would move there."
            )

    def export_table(self, path: Path | None = None) -> Path | None:
        """Save the numbers behind the last hydraulic plot as CSV (asks where when no path is given)."""
        if self._table is None:
            return None
        if path is None:
            chosen, _ = QFileDialog.getSaveFileName(self, "Save the table", str(self.case_dir / "table.csv"),
                                                    "CSV (*.csv)")  # fmt: skip
            if not chosen:
                return None
            path = Path(chosen)
        self._table.write_csv(Path(path))
        self.statusBar().showMessage(f"Saved {path}", 5000)
        return Path(path)

    def open_paraview(self) -> None:
        if self.case_dir is None:
            return
        if not open_in_paraview(self.case_dir / f"{self.project.name}.foam"):
            QMessageBox.information(
                self, "ParaView",
                "ParaView was not found. Install it from paraview.org, then try again.",
            )  # fmt: skip

    # ------------------------------------------------------------------- misc

    def _getting_started(self) -> None:
        self.notify(
            "Getting started",
            "Work through the steps on the left, top to bottom:\n\n"
            "1. Geometry: draw shapes (box, sphere, cylinder, cone, wedge, or an outline of your own) "
            "or import a file (STL, STEP).\n"
            "2. Mesh: size the base mesh, then press Generate mesh.\n"
            "3. Physics: choose steady or transient flow, the turbulence model and the fluid.\n"
            "4. Boundaries: say what each boundary is (inlet, outlet, wall).\n"
            "5. Run: set the iterations and cores, then press Run.\n"
            "6. Results: look at slices and surfaces, or open ParaView.\n\n"
            "Each step shows a tick when it is complete and a warning when something needs attention. "
            "Hover over any input to see what it means. To see it all working, try File > New from example.",
        )

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
        self._remember_layout()
        if self._detect_thread is not None:
            self._detect_thread.wait(3000)
        if self.viewer is not None:
            self.viewer.close_view()
        super().closeEvent(event)
