"""The workflow list on the left: icon, step name, one-line summary and a state badge."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from easyfoam.gui.icons import pixmap
from easyfoam.gui.style import ACCENT, MUTED, SELECTED, STATE_COLOURS, STATE_ICONS, TEXT

ICON_ROLE = Qt.ItemDataRole.UserRole + 1
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 2
STATE_ROLE = Qt.ItemDataRole.UserRole + 3

ROW_HEIGHT = 52
STEP_ICONS = {
    "Geometry": "shapes",
    "Mesh": "mesh",
    "Physics": "wind",
    "Boundaries": "frame",
    "Run": "play",
    "Results": "eye",
}


class StepDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(200, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect: QRect = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)

        if selected or hovered:
            path = QPainterPath()
            path.addRoundedRect(rect, 8, 8)
            painter.fillPath(path, QColor(SELECTED if selected else "#e9edf2"))
        if selected:
            painter.fillRect(QRect(rect.left(), rect.top() + 10, 3, rect.height() - 20), QColor(ACCENT))

        name = index.data(ICON_ROLE)
        colour = ACCENT if selected else (TEXT if enabled else "#aab4c0")
        if name:
            painter.drawPixmap(rect.left() + 14, rect.center().y() - 10, pixmap(name, 21, colour))

        state = index.data(STATE_ROLE) or "todo"
        badge_x = rect.right() - 28
        painter.drawPixmap(badge_x, rect.center().y() - 8, pixmap(STATE_ICONS[state], 17, STATE_COLOURS[state]))

        text_left = rect.left() + 48
        text_width = badge_x - text_left - 6
        title_font = QFont(option.font)
        title_font.setPointSizeF(option.font.pointSizeF() + 0.5)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(TEXT if enabled else "#aab4c0"))
        painter.drawText(QRect(text_left, rect.top() + 7, text_width, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, index.data() or "")  # fmt: skip

        detail_font = QFont(option.font)
        detail_font.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.0))
        painter.setFont(detail_font)
        painter.setPen(QColor(STATE_COLOURS[state] if state in ("warning", "error") else MUTED))
        detail = painter.fontMetrics().elidedText(index.data(DETAIL_ROLE) or "", Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRect(text_left, rect.top() + 26, text_width, 18),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, detail)  # fmt: skip
        painter.restore()
