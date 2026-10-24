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
    reported: set = set()

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

        # A timer that keeps failing must not bury the window under dialogs:
        # every distinct problem is reported once per run.
        signature = (exc_type.__name__, str(exc_value))
        if signature in reported:
            return
        reported.add(signature)

        try:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(f"{APP_NAME} - unexpected error")
            box.setText("Something went wrong, but your library is safe.")
            box.setInformativeText(
                f"{exc_type.__name__}: {exc_value}\n\n"
                "Details were written to the logs folder. The application keeps "
                "running, so you can save your work and restart it if the "
                "problem comes back."
            )
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
        except Exception:
            pass

    sys.excepthook = handle_exception


def _run_self_test() -> bool:
    """Prove the packaged application can really read comics and PDFs.

    Importing a module is not enough: the PDF engine keeps working with a stub
    when its native library is missing, so a broken bundle would only show up
    later as missing covers. This renders an actual page.
    """
    ok = True

    try:
        import tempfile
        from pathlib import Path

        import pdf_engine

        if not pdf_engine.HAS_PDFIUM:
            logger.error("Self-test: the bundled PDF library is not available")
            ok = False
        else:
            import pypdfium2 as pdfium

            folder = Path(tempfile.mkdtemp(prefix="dl-self-test-"))
            sample = folder / "sample.pdf"
            document = pdfium.PdfDocument.new()
            document.new_page(400, 600)
            document.save(str(sample))
            document.close()

            pages = pdf_engine.get_page_count(str(sample))
            image = pdf_engine.render_first_page(str(sample), max_width=200)
            if pages != 1 or image is None or image.width < 10:
                logger.error(
                    "Self-test: PDF rendering failed (pages=%s, cover=%s)", pages, image
                )
                ok = False
            else:
                logger.info("Self-test: PDF page rendered at %sx%s", *image.size)

            for path in folder.iterdir():
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                folder.rmdir()
            except OSError:
                pass
    except Exception:
        logger.exception("Self-test: PDF check raised an error")
        ok = False

    try:
        from utils.reader_manager import reader_manager

        available = reader_manager.available_readers()
        logger.info("Self-test: %d reader(s) available", len(available))
        if not available:
            logger.error("Self-test: no readers were detected")
            ok = False
    except Exception:
        logger.exception("Self-test: reader detection raised an error")
        ok = False

    try:
        from database import db

        logger.info("Self-test: %d book(s) in the library", db.get_total_book_count())
    except Exception:
        logger.exception("Self-test: database check raised an error")
        ok = False

    if ok:
        logger.info("Self-test: all checks passed")
    return ok


def _apply_windows_app_id():
    """Give the running process its own taskbar identity.

    Only the source checkout needs this: there the process image is python.exe
    and Windows would otherwise group the window under the interpreter. The
    packaged executable already owns its identity (and its icon), and an
    AppUserModelID that no shortcut is registered for can make Windows fall back
    to a generic icon, which is exactly what must not happen.
    """
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "AmirGFno.DigitalLibrary"
        )
        logger.info("Windows application id set for the source run")
    except Exception:
        logger.debug("Could not set the Windows application id", exc_info=True)


def _fallback_icon() -> QIcon:
    """Draw a simple app icon so the window never ends up without one."""
    icon = QIcon()
    try:
        from PyQt6.QtGui import QColor, QPainter, QPixmap

        for size in (16, 24, 32, 48, 64, 128, 256):
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e8552d"))
            painter.drawRoundedRect(0, 0, size, size, size // 4, size // 4)
            painter.setBrush(QColor("#ffffff"))
            inset = max(3, size // 5)
            painter.drawRoundedRect(
                inset, inset // 2 + size // 6,
                size - 2 * inset, size - inset * 2 - size // 6,
                max(1, size // 16), max(1, size // 16),
            )
            painter.end()
            icon.addPixmap(pixmap)
    except Exception:
        logger.debug("Could not draw the fallback icon", exc_info=True)
    return icon


def _application_icon() -> QIcon:
    """Icon with every size the shell may ask for (taskbar, alt-tab, dialogs)."""
    icon = QIcon()
    names = ("icon.ico", "icon.png") if sys.platform == "win32" else ("icon.png", "icon.ico")
    for name in names:
        path = ASSETS_DIR / name
        if not path.exists():
            continue
        before = len(icon.availableSizes())
        icon.addFile(str(path))
        if len(icon.availableSizes()) != before or not icon.isNull():
            logger.info("Icon loaded from %s", path)
    if icon.isNull():
        logger.warning("Application icon missing in %s, using the drawn one", ASSETS_DIR)
        icon = _fallback_icon()
    return icon


def main() -> int:
    """Start the application and return the exit code."""
    logger.info("Starting %s %s", APP_NAME, APP_VERSION)
    _apply_windows_app_id()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("DigitalLibrary")

    icon = _application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    else:
        logger.warning("Application icon not found in %s", ASSETS_DIR)

    apply_theme(app)
    _install_exception_hook()

    # The self-test must never block on the first-run welcome dialog.
    window = MainWindow(run_startup=not SELF_TEST)
    window.show()
    logger.info("Application window displayed")

    # Headless self-test used by CI (and for troubleshooting a packaged build).
    if SELF_TEST:
        if not _run_self_test():
            os._exit(4)
        logger.info("Self-test mode: closing automatically")
        QTimer.singleShot(300, app.quit)

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
