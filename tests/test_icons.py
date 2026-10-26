"""The application icon must be usable by the Windows taskbar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_application_icon_offers_small_sizes(qt_app):
    import main

    icon = main._application_icon()

    assert not icon.isNull()
    widths = {size.width() for size in icon.availableSizes()}
    # The taskbar and the title bar ask for 16 to 48 pixels.
    assert {16, 32, 48} <= widths, widths


def test_a_missing_icon_folder_still_gives_an_icon(qt_app, tmp_path, monkeypatch):
    import main

    monkeypatch.setattr(main, "ASSETS_DIR", tmp_path / "nothing")

    icon = main._application_icon()

    assert not icon.isNull()


def test_the_window_shows_the_application_icon(qt_app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    import main
    from database import Database
    from ui.main_window import MainWindow

    monkeypatch.setattr("ui.main_window.db", Database(db_path=tmp_path / "library.db"))
    monkeypatch.setattr(
        "ui.main_window.settings.get_library_root", lambda: str(tmp_path)
    )
    QApplication.instance().setWindowIcon(main._application_icon())

    window = MainWindow(run_startup=False)
    try:
        window.show()
        QApplication.processEvents()
        assert not window.windowIcon().isNull()
        assert window.windowIcon().availableSizes()
    finally:
        window.close()
