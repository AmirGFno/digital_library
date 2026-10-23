#!/usr/bin/env python3
"""
Digital Library - entry point.

A desktop comic & digital book library built with PyQt6 and SQLite.
"""
import os
import sys
import traceback

# When running from source, make the project importable from any cwd.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from config import APP_NAME, APP_VERSION, ASSETS_DIR
from utils.logger import logger
from ui.main_window import MainWindow
from ui.theme import apply_theme

SELF_TEST = "--self-test" in sys.argv


def _install_exception_hook():
    """Log uncaught exceptions and show a friendly message instead of dying."""

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        details = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )
        logger.critical("Unhandled exception:\n%s", details)
        if SELF_TEST:
            # Never block a headless CI run with a modal dialog.
            os._exit(3)
        try:
            QMessageBox.critical(
                None,
                f"{APP_NAME} - unexpected error",
                "Something went wrong, but your library is safe.\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                "Details were written to the logs folder.",
            )
        except Exception:
            pass

    sys.excepthook = handle_exception


def main() -> int:
    """Start the application and return the exit code."""
    logger.info("Starting %s %s", APP_NAME, APP_VERSION)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("DigitalLibrary")

    icon_file = ASSETS_DIR / ("icon.ico" if sys.platform == "win32" else "icon.png")
    if not icon_file.exists():
        icon_file = ASSETS_DIR / "icon.png"
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    apply_theme(app)
    _install_exception_hook()

    window = MainWindow()
    window.show()
    logger.info("Application window displayed")

    # Headless self-test used by CI (and for troubleshooting a packaged build).
    if SELF_TEST:
        logger.info("Self-test mode: closing automatically")
        QTimer.singleShot(700, app.quit)

    return app.exec()


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}")
        sys.exit(0)
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error during startup:\n%s", traceback.format_exc())
        if SELF_TEST:
            os._exit(3)
        raise
