"""SVG icons, drawn in any colour and sharp on high-DPI screens.

Most icons come from Lucide (ISC licence, see ``icons/LICENSE-lucide.txt``);
``mesh``, the ``flow-*``, ``shape-*`` and ``structure-*`` icons and the ``easyfoam`` logo are EasyFOAM's own.
"""

from __future__ import annotations

from functools import cache, lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).parent / "icons"
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
    "flow-gate", "flow-float", "shape-cone", "shape-wedge", "shape-outline", "draw", "force", "flow-jump",
    "flow-tank", "timer", "chart-line", "flow-channel", "flow-terrain", "structure-ogee", "structure-stepped",
    "structure-labyrinth", "structure-basin", "structure-culvert", "structure-fishway", "panel-fold-left",
    "panel-fold-right", "panel-fold-down", "panel-fold-up", "chevrons-left", "chevrons-right", "layout", "undo", "redo",
    "search", "moon", "a-large-small", "file-text", "mouse-pointer-click", "picture-in-picture-2", "layout-template",
)  # fmt: skip


def names() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


@cache
def _svg(name: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        raise KeyError(f"there is no icon named '{name}'")
    return path.read_text(encoding="utf-8")


def _colour(color: str | None, disabled: bool = False) -> str:
    """The colour asked for, or the icon colour of the theme in use."""
    if color:
        return color
    from easyfoam.gui import style

    return style.ICON_DISABLED if disabled else style.ICON


@lru_cache(maxsize=4096)
def _render(name: str, side: int, scale: float, color: str) -> QPixmap:
    pixels = max(1, int(round(side * scale)))
    data = QByteArray(_svg(name).replace("currentColor", color).encode("utf-8"))
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(data).render(painter)
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(scale)
    return result


def pixmap(name: str, size: int = 20, color: str | None = None) -> QPixmap:
    """The icon as a pixmap of ``size`` logical pixels, strokes drawn in ``color`` (default: the theme's)."""
    return _render(name, size, float(SCALE), _colour(color))


class _ThemedEngine(QIconEngine):
    """Draws an icon in the icon colour of the theme in use when it is painted, so it follows a change of theme."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:  # noqa: N802
        side = max(1, size.width(), size.height())
        return _render(self._name, side, max(1.0, float(scale)), _colour(None, mode == QIcon.Mode.Disabled))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self.scaledPixmap(size, mode, state, float(SCALE))

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        device = painter.device()
        scale = device.devicePixelRatioF() if device is not None else 1.0
        painter.drawPixmap(rect, self.scaledPixmap(rect.size(), mode, state, scale))

    def clone(self) -> QIconEngine:
        return _ThemedEngine(self._name)

    def key(self) -> str:
        return "easyfoam-themed"


_ENGINES: list[_ThemedEngine] = []  # kept: Qt holds them, and Python must not free them first


@lru_cache(maxsize=512)
def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """A QIcon with a greyed-out variant for disabled controls; without a colour it follows the theme in use."""
    _svg(name)  # an unknown name fails here, not when the icon is first painted
    if color is None:
        engine = _ThemedEngine(name)
        _ENGINES.append(engine)
        return QIcon(engine)
    result = QIcon()
    result.addPixmap(pixmap(name, size, color), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, size, _colour(None, disabled=True)), QIcon.Mode.Disabled)
    return result
