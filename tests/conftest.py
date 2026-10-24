"""Shared pytest fixtures."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_db(tmp_path):
    from database import Database

    return Database(db_path=tmp_path / "library.db")


@pytest.fixture
def temp_settings(tmp_path):
    from utils.settings import Settings

    return Settings(tmp_path / "settings.json")


@pytest.fixture(scope="session")
def qt_app():
    """One offscreen QApplication for the widget tests."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    app = QtWidgets.QApplication.instance()
    if app is None:
        try:
            app = QtWidgets.QApplication([])
        except Exception as exc:  # no display / missing platform plugin
            pytest.skip(f"Qt cannot start here: {exc}")
    return app
