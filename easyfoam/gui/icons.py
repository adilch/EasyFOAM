"""SVG icons, drawn in any colour and sharp on high-DPI screens.

Most icons come from Lucide (ISC licence, see ``icons/LICENSE-lucide.txt``);
``mesh``, the ``flow-*`` icons and the ``easyfoam`` logo are EasyFOAM's own.
"""

from __future__ import annotations

from functools import cache, lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).parent / "icons"
NORMAL = "#3d4a5c"
DISABLED = "#b3bcc8"
SCALE = 2  # icons are rendered at twice their logical size

#: every icon name the interface refers to (checked by the tests)
USED = (
    "easyfoam", "file-plus", "folder-open", "save", "history", "folder", "log-out",
    "shapes", "mesh", "wind", "frame", "play", "square", "circle-stop", "step-forward", "eye",
    "activity", "external-link", "import", "box", "circle", "cylinder", "trash-2", "plus", "pencil",
    "maximize", "rotate-3d", "camera", "grid-2x2", "arrow-right-to-line", "arrow-right-from-line",
    "brick-wall", "move-horizontal", "waves", "flip-horizontal", "circle-check", "triangle-alert",
    "circle-x", "circle-dashed", "info", "circle-help", "terminal", "refresh-cw", "calculator",
    "gauge", "crosshair", "locate-fixed", "arrow-right", "arrow-left", "wand", "ruler", "layers",
    "flow-body", "flow-pipe", "flow-cavity", "flow-weir", "flow-dam", "droplet", "book-open", "cpu",
    "flow-gate", "flow-float",
)  # fmt: skip


def names() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


@cache
def _svg(name: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        raise KeyError(f"there is no icon named '{name}'")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=512)
def pixmap(name: str, size: int = 20, color: str = NORMAL) -> QPixmap:
    """The icon as a pixmap of ``size`` logical pixels, strokes drawn in ``color``."""
    data = QByteArray(_svg(name).replace("currentColor", color).encode("utf-8"))
    renderer = QSvgRenderer(data)
    image = QImage(size * SCALE, size * SCALE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(SCALE)
    return result


@lru_cache(maxsize=512)
def icon(name: str, color: str = NORMAL, size: int = 20) -> QIcon:
    """A QIcon with a greyed-out variant for disabled controls."""
    result = QIcon()
    result.addPixmap(pixmap(name, size, color), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, size, DISABLED), QIcon.Mode.Disabled)
    return result
