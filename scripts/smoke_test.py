"""
GUI smoke test.

Runs the real Qt widgets with the offscreen platform plugin, imports a comic and
opens the details/reader dialogs. Used by CI to catch wiring errors that unit
tests cannot see.
"""
import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from database import db  # noqa: E402
from ui.theme import apply_theme  # noqa: E402


def main() -> int:
    app = QApplication([])
    apply_theme(app)

    from importer import importer
    from ui.details_dialog import DetailsDialog
    from ui.main_window import MainWindow
    from ui.reader_settings_dialog import ReaderSettingsDialog

    window = MainWindow()
    window.show()
    app.processEvents()

    settings_dialog = ReaderSettingsDialog(window)
    app.processEvents()
    settings_dialog.close()

    comic_dir = Path(tempfile.mkdtemp(prefix="dl-smoke-"))
    comic_path = comic_dir / "Demo 001.cbz"
    with zipfile.ZipFile(comic_path, "w") as archive:
        archive.writestr(
            "ComicInfo.xml",
            "<ComicInfo><Series>Smoke Test</Series><Number>1</Number>"
            "<Title>Demo issue</Title><Writer>CI</Writer><Year>2026</Year></ComicInfo>",
        )
        archive.writestr("001.jpg", b"not-a-real-image")

    result = importer.import_files([str(comic_path)])
    assert result.added == 1, result.summary()

    window.refresh_books()
    app.processEvents()
    assert len(window.book_cards) == 1, "book card was not created"

    book = db.get_all_books()[0]
    details = DetailsDialog(book["id"], window)
    app.processEvents()
    details.close()

    window.close()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
