"""Start the EasyFOAM desktop application."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")


def grab_window(window):
    """A picture of the window (a ``QPixmap``), with the 3D view composited in.

    The 3D view is drawn by OpenGL, which a plain widget grab does not capture,
    so its image is rendered separately and painted into place.
    """
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QImage, QPainter

    pixmap = window.grab()
    viewer = window.viewer
    if viewer is not None and viewer.isVisible():
        image = viewer.screenshot()
        height, width = image.shape[:2]
        data = image[:, :, :3].copy().tobytes()
        frame = QImage(data, width, height, 3 * width, QImage.Format.Format_RGB888)
        target = QRect(viewer.plotter.mapTo(window, QPoint(0, 0)), viewer.plotter.size())
        painter = QPainter(pixmap)
        painter.drawImage(target, frame)
        painter.end()
    return pixmap


def save_snapshot(window, path: Path) -> None:
    """Save a picture of the window to a file."""
    grab_window(window).save(str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="easyfoam-gui", description="EasyFOAM desktop application")
    parser.add_argument("case", nargs="?", help="project folder to open")
    parser.add_argument("--step", help="workflow step to show (Geometry, Mesh, …)")
    parser.add_argument("--tab", help="bottom tab to show (Residuals, Forces, Log)")
    parser.add_argument("--field", help="result quantity to show")
    parser.add_argument("--mode", help="result display: slice, surface, water or mesh")
    parser.add_argument("--time", type=float, help="saved time to show (the nearest one is taken)")
    parser.add_argument("--snapshot", help="save a picture of the window to this file and quit")
    parser.add_argument("--delay", type=int, default=2500, help="milliseconds to wait before --snapshot")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from easyfoam.gui.main_window import STEPS, MainWindow
    from easyfoam.model import PROJECT_FILE

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("EasyFOAM")
    from easyfoam.gui.style import apply_style

    apply_style(app)
    window = MainWindow()
    window.show()
    if args.case:
        case = Path(args.case)
        if (case / PROJECT_FILE).is_file():
            window.open_project(case)
        else:
            window.statusBar().showMessage(f"{case} has no {PROJECT_FILE}")
    if args.step and args.step in STEPS:
        window.steps.setCurrentRow(STEPS.index(args.step))
    if args.time is not None:
        times = window.results_panel.time
        saved = [times.itemData(i) for i in range(times.count())]
        if saved:
            times.setCurrentIndex(min(range(len(saved)), key=lambda i: abs(saved[i] - args.time)))
    if args.field:
        window.results_panel.select_field(args.field, args.mode)
    if args.tab:
        for index in range(window.bottom.count()):
            if window.bottom.tabText(index) == args.tab:
                window.bottom.setCurrentIndex(index)
    if args.snapshot:
        def snap() -> None:
            save_snapshot(window, Path(args.snapshot))
            window.close()

        QTimer.singleShot(args.delay, snap)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
