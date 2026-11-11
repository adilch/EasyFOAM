import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")
# never touch the real list of recent projects while testing
os.environ["EASYFOAM_STATE_FILE"] = os.path.join(tempfile.mkdtemp(prefix="easyfoam-test-"), "state.json")


@pytest.fixture(scope="session")
def qapp():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
