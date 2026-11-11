"""The start page and the New project dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from easyfoam.gui.icons import icon, pixmap
from easyfoam.gui.style import ACCENT, set_primary

#: key -> (icon, title, one-line description)
EXAMPLES = {
    "empty": ("file-plus", "Empty project", "Bring your own geometry"),
    "sphere": ("flow-body", "Air flow past a sphere", "External flow with drag and lift"),
    "pipe": ("flow-pipe", "Laminar flow in a pipe", "Internal flow, checked against theory"),
    "cavity": ("flow-cavity", "Lid-driven cavity", "A stirred box that runs in seconds"),
    "weir": ("flow-weir", "Flow over a weir", "Free surface in an open channel"),
    "dambreak": ("flow-dam", "Dam break", "A water column collapses in a tank"),
    "waves": ("waves", "Waves in a flume", "Wave maker and absorbing outlet"),
}


class WelcomePage(QWidget):
    new_requested = Signal(str)  # example key ("empty" for a blank project)
    open_requested = Signal()
    recent_requested = Signal(str)  # project folder

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        logo = QLabel()
        logo.setPixmap(pixmap("easyfoam", 56))
        title = QLabel("EasyFOAM")
        title.setProperty("role", "title")
        subtitle = QLabel("Set up, run and look at OpenFOAM simulations, step by step.")
        subtitle.setProperty("role", "subtitle")
        words = QVBoxLayout()
        words.addWidget(title)
        words.addWidget(subtitle)
        header = QHBoxLayout()
        header.addWidget(logo)
        header.addSpacing(10)
        header.addLayout(words)
        header.addStretch(1)

        self.new_button = QPushButton(icon("file-plus", "#ffffff"), "  New project")
        set_primary(self.new_button)
        self.new_button.clicked.connect(lambda: self.new_requested.emit("empty"))
        self.open_button = QPushButton(icon("folder-open"), "  Open project…")
        self.open_button.clicked.connect(self.open_requested)
        actions = QHBoxLayout()
        actions.addWidget(self.new_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)

        examples_heading = QLabel("Start from an example")
        examples_heading.setProperty("role", "heading")
        self.example_buttons: dict[str, QPushButton] = {}
        cards = QGridLayout()
        cards.setSpacing(12)
        for index, key in enumerate(("sphere", "pipe", "cavity", "weir", "dambreak", "waves")):
            name, label, text = EXAMPLES[key]
            card = QPushButton(icon(name, ACCENT, 34), f"  {label}\n  {text}")
            card.setIconSize(QSize(34, 34))
            card.setProperty("card", True)
            card.setMinimumHeight(74)
            card.clicked.connect(lambda _checked=False, k=key: self.new_requested.emit(k))
            cards.addWidget(card, index // 3, index % 3)
            self.example_buttons[key] = card

        recent_heading = QLabel("Recent projects")
        recent_heading.setProperty("role", "heading")
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(300)
        self.recent_list.itemActivated.connect(self._recent_chosen)
        self.recent_list.itemClicked.connect(self._recent_chosen)
        self.no_recent = QLabel("Projects you open will be listed here.")
        self.no_recent.setProperty("role", "subtitle")

        column = QVBoxLayout()
        column.setSpacing(14)
        column.addLayout(header)
        column.addSpacing(6)
        column.addLayout(actions)
        column.addSpacing(10)
        column.addWidget(examples_heading)
        column.addLayout(cards)
        column.addSpacing(10)
        column.addWidget(recent_heading)
        column.addWidget(self.recent_list)
        column.addWidget(self.no_recent)
        column.addStretch(1)
        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(980)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(40, 36, 40, 30)
        outer.addStretch(1)
        outer.addWidget(holder, 6)
        outer.addStretch(1)
        self.set_recent([])

    def set_recent(self, folders: list[str]) -> None:
        self.recent_list.clear()
        for folder in folders:
            path = Path(folder)
            item = QListWidgetItem(icon("folder"), f"{path.name}\n{path.parent}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.recent_list.addItem(item)
        self.recent_list.setVisible(bool(folders))
        self.no_recent.setVisible(not folders)

    def _recent_chosen(self, item: QListWidgetItem) -> None:
        self.recent_requested.emit(item.data(Qt.ItemDataRole.UserRole))


class NewProjectDialog(QDialog):
    """Asks for a name, a location and a starting point."""

    def __init__(self, location: Path, example: str = "empty", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.setMinimumWidth(520)
        self.name = QLineEdit("my-case")
        self.name.selectAll()
        self.location = QLineEdit(str(location))
        browse = QPushButton(icon("folder-open"), "")
        browse.setToolTip("Choose another folder")
        browse.clicked.connect(self._browse)
        where = QHBoxLayout()
        where.addWidget(self.location, 1)
        where.addWidget(browse)
        self.example = QComboBox()
        for key, (name, label, text) in EXAMPLES.items():
            self.example.addItem(icon(name), f"{label}  —  {text}", key)
        self.example.setCurrentIndex(max(0, self.example.findData(example)))
        self.path_hint = QLabel()
        self.path_hint.setProperty("role", "subtitle")
        self.path_hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Create in", where)
        form.addRow("Start from", self.example)
        form.addRow(self.path_hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Create project")
        set_primary(self.ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.name.textChanged.connect(self._update)
        self.location.textChanged.connect(self._update)
        self._update()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Create the project in", self.location.text())
        if folder:
            self.location.setText(folder)

    def _update(self) -> None:
        name = self.name.text().strip()
        target = Path(self.location.text().strip() or ".") / name
        taken = bool(name) and target.exists() and any(target.iterdir())
        self.ok.setEnabled(bool(name) and not taken)
        if not name:
            self.path_hint.setText("Give the project a name.")
        elif taken:
            self.path_hint.setText(f"{target} already exists and is not empty. Choose another name.")
        else:
            self.path_hint.setText(f"The project folder will be {target}")

    def values(self) -> tuple[str, Path, str]:
        return self.name.text().strip(), Path(self.location.text().strip()), self.example.currentData()
