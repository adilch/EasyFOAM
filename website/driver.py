"""Operate the real application through a tutorial and take its pictures.

The driver does what the tutorial tells the reader to do (create the project,
set values, generate the mesh, run), so every picture shows the program exactly
as the reader will see it at that point, and a tutorial that no longer works
fails here instead of misleading someone.
"""

from __future__ import annotations

import io
import os
import shutil
import time
from pathlib import Path

from website.sitegen import OUT, ROOT, Step, Tutorial

WORK = ROOT / "runs" / "tutorials"
MARK_COLOUR = "#e8590c"
RADIUS = 12  # of a numbered marker, in window units
COVER_SIZE = (960, 600)
QUALITY = 84


class Driver:
    def __init__(self, tutorial: Tutorial, out: Path = OUT, work: Path = WORK) -> None:
        self.tutorial = tutorial
        self.out = out / "tutorials" / "img" / tutorial.slug
        self.work = work / "cases"  # where the tutorial's projects are created
        self.work.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
        memory = work / "state" / f"{tutorial.slug}.json"
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.unlink(missing_ok=True)
        os.environ["EASYFOAM_STATE_FILE"] = str(memory)  # a clean start page; nothing of the user's own shows up

        from PySide6.QtWidgets import QApplication, QMessageBox

        from easyfoam.gui import state
        from easyfoam.gui.main_window import MainWindow
        from easyfoam.gui.style import apply_style
        from easyfoam.runtime import detect_runtimes

        self.app = QApplication.instance() or QApplication([])
        self.app.setApplicationName("EasyFOAM")
        apply_style(self.app)
        self.problems: list[str] = []
        for name in ("warning", "critical", "information"):  # a dialog would wait for a click that never comes
            setattr(QMessageBox, name, staticmethod(lambda _parent, title, text, *a, n=name: self._said(n, title, text)))
        state.remember_projects_folder(self.work)
        self.w = MainWindow(detect=False)
        self.w.notify = lambda title, text, level="info": self._said(level, title, text)
        found = detect_runtimes()
        if found:
            self.w.runtimes = found
            self.w.runtime = found[0]
            self.w._fill_runtime_menu()
            self.w._show_runtime()
        self.w.resize(1520, 900)
        self.w.show()
        self.dialog = None
        self.settle(1.0)

    # -- what a tutorial can ask for (used in Step.before) -------------------------

    def create(self, example: str, name: str | None = None) -> None:
        """Create a new project from an example, as the New project dialog does."""
        self.close_dialog()
        name = name or self.tutorial.slug
        shutil.rmtree(self.work / name, ignore_errors=True)
        self.w.create_project(name, self.work, example)
        self.settle(0.6)

    def show_dialog(self, example: str, name: str) -> None:
        """Open the New project dialog (without blocking) so that it can be pictured."""
        from easyfoam.gui import state
        from easyfoam.gui.welcome import NewProjectDialog

        self.dialog = NewProjectDialog(state.projects_folder(), example, self.w)
        self.dialog.name.setText(name)
        self.dialog.setModal(False)
        self.dialog.show()
        self.settle(0.4)

    def open_sketch(self) -> None:
        """Open the pad on which the selected outline is drawn (without blocking), to be pictured."""
        from easyfoam.gui.sketch import SketchDialog

        panel = self.w.geometry_panel
        shape = panel.selected()
        self.dialog = SketchDialog(shape.points, shape.plane, panel.outline_reference(shape), self.w)
        self.dialog.setModal(False)
        self.dialog.show()
        self.settle(0.5)

    def accept_sketch(self) -> None:
        """Press "Use this outline"."""
        self.w.geometry_panel.set_outline(self.dialog.values())
        self.close_dialog()
        self.settle(0.6)

    def open_channel(self, channel) -> None:
        """Open the channel builder (without blocking), filled in as given, so that it can be pictured."""
        from easyfoam.gui.channel_dialog import ChannelDialog

        self.dialog = ChannelDialog(channel, self.w)
        self.dialog.setModal(False)
        self.dialog.show()
        self.settle(0.5)

    def build_channel(self) -> None:
        """Press "Build the channel"."""
        channel = self.dialog.channel()
        self.close_dialog()
        self.w.apply_channel(channel)
        self.settle(0.8)

    def open_terrain(self, path, origin, angle, region, spacing, cell, water, top, discharge) -> None:
        """Open the terrain dialog (without blocking) on a survey, filled in as given, so that it can be pictured."""
        from easyfoam.gui.terrain_dialog import TerrainDialog

        self.dialog = TerrainDialog(path, self.w)
        dlg = self.dialog
        for edit, value in zip((dlg.origin_x, dlg.origin_y, dlg.angle), (*origin, angle)):
            edit.set_value(value)
        dlg._whole()
        for edit, value in zip((dlg.x_from, dlg.y_from, dlg.x_to, dlg.y_to, dlg.spacing, dlg.cell_size, dlg.water,
                                dlg.top, dlg.discharge), (*region, spacing, cell, water, top, discharge)):  # fmt: skip
            edit.set_value(value)
        dlg._update()
        dlg.setModal(False)
        dlg.show()
        self.settle(0.6)

    def use_terrain(self) -> None:
        """Press "Use this ground"."""
        ground, settings = self.dialog.ground(), self.dialog.settings()
        self.close_dialog()
        self.w.apply_terrain(ground, **settings)
        self.settle(0.8)

    def open_structure(self, structure) -> None:
        """Open the structure designer (without blocking), filled in as given, so that it can be pictured."""
        from easyfoam.gui.structure_dialog import StructureDialog

        base = self.w.project.mesh.base
        self.dialog = StructureDialog(structure, (list(base.min), list(base.max)), self.w)
        self.dialog.setModal(False)
        self.dialog.show()
        self.settle(0.6)

    def use_structure(self) -> None:
        """Press "Use this structure": a new structure is added, a selected one is changed."""
        structure = self.dialog.structure()
        self.close_dialog()
        panel = self.w.geometry_panel
        selected = panel.selected()
        if selected is not None and selected.kind == "structure":
            panel.set_structure(structure)
        else:
            panel.add_structure(structure)
        self.settle(0.6)

    def open_series(self, attribute: str, series) -> None:
        """Open the time-series table of the selected boundary (without blocking), filled in, to be pictured.

        ``attribute`` is ``flow_series`` (an inflow hydrograph) or ``level_series`` (a tailwater that changes).
        """
        from easyfoam.gui.series import SeriesDialog

        panel = self.w.boundary_panel
        if attribute == "flow_series":
            title, unit, constant, positive = "Inflow hydrograph", "m³/s", panel.flow_rate.value(), True
        else:
            title, unit, constant, positive = "Tailwater level in time", "m", panel.level.value(), False
        self.dialog = SeriesDialog(series, title, unit, constant, positive, self.w.project.run.end_time, self.w)
        self.dialog.setModal(False)
        self.dialog.show()
        self.settle(0.5)

    def accept_series(self, attribute: str) -> None:
        """Press "Use this series"."""
        values = self.dialog.values()
        self.close_dialog()
        getattr(self.w.boundary_panel, f"set_{attribute}")(values)
        self.settle(0.4)

    def close_dialog(self) -> None:
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

    def set(self, widget, value) -> None:
        """Enter a value the way a user would: type it, pick it or tick it."""
        from PySide6.QtWidgets import QAbstractSpinBox, QCheckBox, QComboBox, QLineEdit

        from easyfoam.gui.widgets import VectorEdit

        if isinstance(widget, VectorEdit):
            widget.set_value(value)
            widget.changed.emit()
        elif isinstance(widget, QComboBox):
            index = widget.findData(value)
            index = index if index >= 0 else widget.findText(str(value))
            if index < 0:
                raise ValueError(f"{value!r} is not offered")
            widget.setCurrentIndex(index)
        elif isinstance(widget, QAbstractSpinBox):
            widget.setValue(value)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QLineEdit):  # includes the number inputs
            widget.setText(f"{value:g}" if isinstance(value, float) else str(value))
            widget.editingFinished.emit()
        else:
            raise TypeError(f"cannot set a {type(widget).__name__}")
        self.settle(0.05)

    def shape(self, name: str) -> None:
        names = [s.name for s in self.w.project.shapes]
        self.w.geometry_panel.shape_list.setCurrentRow(names.index(name))

    def boundary(self, name: str) -> None:
        self.w.steps.setCurrentRow(3)
        self.settle(0.2)
        names = [p.name for p in self.w.boundary_panel.patches]
        self.w.boundary_panel.patch_list.setCurrentRow(names.index(name))

    def mesh(self) -> None:
        self.w.generate_mesh()
        self.wait()

    def run(self, until: float | None = None) -> None:
        """Start the run; return when it is done, or already at a share of the way through."""
        self.w.run_solver()
        if until is None:
            self.wait()
            return
        end = self.w.project.run.end_time
        while self.w.thread is not None:
            now = self.w.thread.job.parser.time
            if now is not None and now >= until * end:
                break
            self._pump()
        self.settle(0.5)

    def wait(self, timeout: float = 3600.0) -> None:
        deadline = time.time() + timeout
        while self.w.thread is not None:
            self._pump()
            if time.time() > deadline:
                raise TimeoutError("the task did not finish in time")
        self.settle(0.5)
        if self.problems:
            raise RuntimeError("; ".join(self.problems))

    def results(self, field: str, mode: str | None = None, time_: float | None = None) -> None:
        panel = self.w.results_panel
        if time_ is not None:
            saved = [panel.time.itemData(i) for i in range(panel.time.count())]
            panel.time.setCurrentIndex(min(range(len(saved)), key=lambda i: abs(saved[i] - time_)))
        panel.select_field(field, mode)

    def go(self, step: str) -> None:
        """Show a workflow step now (a picture's own step is otherwise shown after ``before``)."""
        from easyfoam.gui.main_window import STEPS

        self.w.steps.setCurrentRow(STEPS.index(step))
        self.settle(0.6)

    def view(self, key: str) -> None:
        """Press a button of the view bar: fit, iso, +x, -x, +y, -y, +z or -z."""
        self.settle(0.7)  # let the view catch up with what was just typed, as a person would
        self.w._view(key)
        self.settle(0.2)

    def flat(self, on: bool = True) -> None:
        button = self.w.viewer.parallel_button
        if button.isChecked() != on:
            button.click()
        self.settle(0.2)

    # -- pictures ------------------------------------------------------------------

    def _said(self, level: str, title: str, text: str):
        if level in ("warning", "critical", "error"):
            self.problems.append(f"{title}: {text}")

    def _pump(self) -> None:
        self.app.processEvents()
        time.sleep(0.02)

    def settle(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self._pump()

    def _root(self):
        return self.dialog if self.dialog is not None else self.w

    def _rect(self, target):
        """The rectangle of a control, in the coordinates of the pictured window."""
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QToolBar, QWidget

        if isinstance(target, QRect):
            return target
        if isinstance(target, QAction):
            target = self.w.findChild(QToolBar).widgetForAction(target)
        if not isinstance(target, QWidget):
            raise TypeError(f"cannot point at a {type(target).__name__}")
        if not target.isVisible():
            raise ValueError(f"{target!r} is not on screen")
        return QRect(target.mapTo(self._root(), QPoint(0, 0)), target.size())

    def _namespace(self) -> dict:
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QTableWidget

        from easyfoam.gui.main_window import STEPS

        w = self.w

        def in_view(view, rect) -> QRect:
            return QRect(view.viewport().mapTo(self._root(), rect.topLeft()), rect.size())

        def step(name: str) -> QRect:
            return in_view(w.steps, w.steps.visualItemRect(w.steps.item(STEPS.index(name))))

        def tab(name: str) -> QRect:
            bar = w.bottom.tabBar()
            index = [w.bottom.tabText(i) for i in range(w.bottom.count())].index(name)
            return QRect(bar.mapTo(w, bar.tabRect(index).topLeft()), bar.tabRect(index).size())

        def item(listing, text: str) -> QRect:
            for row in range(listing.count()):
                if listing.item(row).text().startswith(text):
                    return in_view(listing, listing.visualItemRect(listing.item(row)))
            raise ValueError(f"no item {text!r}")

        def cell(table: QTableWidget, row: int, column: int) -> QRect:
            return in_view(table, table.visualRect(table.model().index(row, column)))

        def viewbutton(text: str):
            from PySide6.QtWidgets import QToolButton

            for button in w.viewer.findChildren(QToolButton):
                if button.text() == text:
                    return button
            raise ValueError(f"no view button {text!r}")

        def button(parent, text: str):
            from PySide6.QtWidgets import QPushButton

            for candidate in parent.findChildren(QPushButton):
                if candidate.text().strip() == text and candidate.isVisible():
                    return candidate
            raise ValueError(f"no button {text!r}")

        return {"w": w, "d": self, "dlg": self.dialog, "step": step, "tab": tab, "item": item, "cell": cell,
                "viewbutton": viewbutton, "button": button}  # fmt: skip

    def _targets(self, step: Step) -> list:
        namespace = self._namespace()
        return [eval(mark.at, namespace) for mark in step.marks]  # noqa: S307 - our own tutorial files

    def shot(self, number: int, step: Step) -> None:
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import QScrollArea, QWidget

        from easyfoam.gui.app import grab_window
        from easyfoam.gui.main_window import STEPS

        if step.before is not None:
            step.before(self)
        if not step.screen:
            return
        if step.screen == "Welcome":
            if self.w.project is not None:
                self.w.close_project()
        elif step.screen != "Dialog":
            self.close_dialog()
            row = STEPS.index(step.screen)
            if self.w.steps.currentRow() != row:
                self.w.steps.setCurrentRow(row)
        if step.tab:
            self.w._show_tab(step.tab)
        self.settle(0.9)

        scroll = self.w.stack.currentWidget()
        widgets = [t for t in self._targets(step) if isinstance(t, QWidget)]
        if isinstance(scroll, QScrollArea) and step.screen in STEPS:
            inside = [t for t in widgets if scroll.widget().isAncestorOf(t)]
            for target in reversed(inside):  # the first marked control wins if they do not all fit
                scroll.ensureWidgetVisible(target, 40, 70)
            if not inside:
                scroll.verticalScrollBar().setValue(0)
            self.settle(0.3)
            hidden = [m.at for m, t in zip(step.marks, self._targets(step))
                      if isinstance(t, QWidget) and t.visibleRegion().boundingRect().height() < t.height() - 2]  # fmt: skip
            if hidden:
                raise ValueError(f"step {number}: not all marked controls fit in one picture: {hidden}")
        self.settle(0.5)
        self.w.statusBar().clearMessage() if self.dialog is None else None
        self.settle(0.1)

        root = self._root()
        pixmap = root.grab() if self.dialog is not None else grab_window(self.w)
        self._paint_marks(pixmap, step, [self._rect(t) for t in self._targets(step)])
        area = QRect(QPoint(0, 0), root.size())
        if self.dialog is None and step.crop in ("left", "right"):
            split = self.w.workspace.widget(1).mapTo(self.w, QPoint(0, 0)).x()
            left = QRect(0, 0, split, root.height())
            area = left if step.crop == "left" else QRect(split, 0, root.width() - split, root.height())
        self._save(pixmap, area, self.out / f"{number:02d}.webp")
        if step.cover and self.w.viewer is not None:
            plotter = self.w.viewer.plotter
            clean = grab_window(self.w)  # without the markers
            self._save(clean, QRect(plotter.mapTo(self.w, QPoint(0, 0)), plotter.size()), self.out / "cover.webp", COVER_SIZE)
        print(f"  {self.tutorial.slug} {number:02d}  {step.title}", flush=True)

    def _paint_marks(self, pixmap, step: Step, rects: list) -> None:
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QFont, QPainter, QPen

        if not rects:
            return
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(MARK_COLOUR)
        width = pixmap.width() / pixmap.devicePixelRatio()
        height = pixmap.height() / pixmap.devicePixelRatio()
        font = QFont(painter.font())
        font.setBold(True)
        font.setPixelSize(15)
        painter.setFont(font)
        for number, (mark, rect) in enumerate(zip(step.marks, rects), start=1):
            if mark.where != "centre" and rect.height() <= 70:
                outline = QColor(colour)
                outline.setAlpha(210)
                painter.setPen(QPen(outline, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(rect).adjusted(-2, -2, 2, 2), 6, 6)
            centre = {
                "corner": QPointF(rect.left() - 5, rect.top() - 1),  # on the top-left corner: hides no text
                "left": QPointF(rect.left() - RADIUS - 3, rect.center().y()),
                "right": QPointF(rect.right() + 5, rect.top() - 1),
                "top": QPointF(rect.center().x(), rect.top() - 3),
                "centre": QPointF(rect.center()),
            }[mark.where]
            centre.setX(max(RADIUS + 2, min(width - RADIUS - 2, centre.x())))
            centre.setY(max(RADIUS + 2, min(height - RADIUS - 2, centre.y())))
            painter.setPen(QPen(QColor("#ffffff"), 2.5))
            painter.setBrush(colour)
            painter.drawEllipse(centre, RADIUS, RADIUS)
            painter.setPen(QColor("#ffffff"))
            box = QRectF(centre.x() - RADIUS, centre.y() - RADIUS, 2 * RADIUS, 2 * RADIUS)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, str(number))
        painter.end()

    @staticmethod
    def _save(pixmap, area, path: Path, cover: tuple[int, int] | None = None) -> None:
        from PIL import Image
        from PySide6.QtCore import QBuffer, QIODevice, QRect

        ratio = pixmap.devicePixelRatio()
        pixels = QRect(int(area.x() * ratio), int(area.y() * ratio), int(area.width() * ratio), int(area.height() * ratio))
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.copy(pixels).save(buffer, "PNG")
        picture = Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGB")
        if cover:
            wanted = cover[0] / cover[1]
            w, h = picture.size
            if w / h > wanted:
                cut = int((w - h * wanted) / 2)
                picture = picture.crop((cut, 0, w - cut, h))
            else:
                cut = int((h - w / wanted) / 2)
                picture = picture.crop((0, cut, w, h - cut))
            picture = picture.resize(cover, Image.Resampling.LANCZOS)
        picture.save(path, "WEBP", quality=QUALITY, method=6)

    def close(self) -> None:
        self.close_dialog()
        if self.w.thread is not None:
            self.w.stop_job()
            self.w.stop_job()
            self.settle(2.0)
        self.w.close()
        self.settle(0.3)


def take(tutorial: Tutorial, out: Path = OUT) -> None:
    """Go through a tutorial in the real application and save its pictures."""
    driver = Driver(tutorial, out)
    try:
        for number, step in enumerate(tutorial.steps, start=1):
            driver.shot(number, step)
            if driver.problems:
                raise RuntimeError("; ".join(driver.problems))
    finally:
        driver.close()
