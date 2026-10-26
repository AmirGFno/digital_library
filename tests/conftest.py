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


# The window restores the filters, the view mode and the colour mode of the
# previous session. A test suite must not inherit (or destroy) the settings of
# the machine it runs on, so every test starts from the shipping defaults.
_VIEW_DEFAULTS = {
    "columns": 4,
    "theme": "light",
    "sort": "series",
    "filter": "all",
    "format": "all",
    "favorites_only": False,
    "view_mode": "grid",
}


@pytest.fixture(autouse=True)
def pinned_view_settings():
    from utils.settings import settings

    saved = {key: settings.get_view(key) for key in _VIEW_DEFAULTS}
    settings.set_many_view(dict(_VIEW_DEFAULTS))
    yield
    settings.set_many_view(
        {key: value for key, value in saved.items() if value is not None}
    )


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


def pytest_runtest_logreport(report):
    """Surface a failing test as an annotation on the GitHub run page.

    The Actions log download is not always reachable, while the annotations of
    a check run are; this turns every failure into one readable line there.
    """
    import os as _os

    if not _os.environ.get("GITHUB_ACTIONS"):
        return
    if report.failed and report.when == "call":
        message = str(report.longrepr).strip().splitlines()
        detail = message[-1] if message else "failed"
        print(f"::error title={report.nodeid}::{detail[:400]}")
