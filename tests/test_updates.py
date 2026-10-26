"""The update prompt: the dialog itself and the window that opens it."""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils import updater  # noqa: E402


def make_info(version="2.5.0", installable=True):
    return updater.UpdateInfo(
        version=version,
        tag=f"v{version}",
        notes="First line of the notes\nSecond line",
        page_url=f"https://example.test/releases/{version}",
        asset_url="https://example.test/update.zip" if installable else "",
        asset_name=(
            f"DigitalLibrary-{version}-windows-x64-update.zip" if installable else ""
        ),
        asset_size=2 * 1024 * 1024 if installable else 0,
        checksum_url="https://example.test/SHA256.txt" if installable else "",
    )


# ----------------------------------------------------------------------
# The dialog
# ----------------------------------------------------------------------
def test_the_dialog_shows_the_new_version_and_its_notes(qt_app):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(make_info())

    assert dialog.pages.count() == 3
    assert dialog.pages.currentIndex() == 0
    assert dialog.download_button.text() == "Download and install"
    assert dialog.later_button.text() == "Later"
    assert "First line of the notes" in dialog.notes_browser.toPlainText()
    assert "2.5.0" in dialog.version_title.text()


def test_confirming_downloads_and_installs_in_place(qt_app):
    from ui.update_dialog import UpdateDialog

    progress = []
    installed = []

    def download(report):
        report(512 * 1024, 2 * 1024 * 1024)
        report(2 * 1024 * 1024, 2 * 1024 * 1024)
        return Path("/tmp/DigitalLibrary-update.zip")

    dialog = UpdateDialog(
        make_info(), download=download, install=lambda path: installed.append(path)
    )
    dialog.start_download(inline=True)

    assert installed == [Path("/tmp/DigitalLibrary-update.zip")]
    assert dialog.applying is True
    assert dialog.result() == dialog.DialogCode.Accepted
    assert progress == []  # the dialog's own bar was fed through the callback


def test_the_progress_bar_follows_the_download(qt_app):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(make_info())
    dialog._on_progress(1024 * 1024, 4 * 1024 * 1024)
    assert dialog.progress_bar.value() == 25
    dialog._on_progress(2 * 1024 * 1024, 0)  # unknown size -> busy bar
    assert dialog.progress_bar.maximum() == 0


def test_a_failed_download_keeps_the_current_version_installed(qt_app):
    from ui.update_dialog import UpdateDialog

    def broken(report):
        raise updater.UpdateError("no internet")

    dialog = UpdateDialog(make_info(), download=broken)
    dialog.start_download(inline=True)

    assert dialog.pages.currentIndex() == 2
    assert "no internet" in dialog.error_label.text()
    assert dialog.applying is False
    assert dialog.result() != dialog.DialogCode.Accepted


def test_a_failed_install_is_reported_and_the_app_keeps_running(qt_app):
    from ui.update_dialog import UpdateDialog

    def broken_install(path):
        raise updater.UpdateError("the files are locked")

    dialog = UpdateDialog(
        make_info(),
        download=lambda report: Path("/tmp/update.zip"),
        install=broken_install,
    )
    dialog.start_download(inline=True)

    assert dialog.pages.currentIndex() == 2
    assert "locked" in dialog.error_label.text()
    assert dialog.applying is False


def test_a_release_without_a_package_opens_the_download_page(qt_app):
    from ui.update_dialog import UpdateDialog

    opened = []
    dialog = UpdateDialog(make_info(installable=False))
    dialog._open_page = opened.append

    assert dialog.download_button.text() == "Open download page"
    dialog.download_button.click()

    assert opened == ["https://example.test/releases/2.5.0"]
    assert dialog.applying is False


def test_the_window_cannot_be_closed_mid_download(qt_app):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(make_info())
    rejected = []
    dialog.rejected.connect(lambda: rejected.append(True))
    dialog._downloading = True

    dialog.reject()
    dialog.close()

    assert rejected == []
    assert dialog._downloading is True


# ----------------------------------------------------------------------
# The window
# ----------------------------------------------------------------------
@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from database import Database
    from ui.theme import apply_theme

    apply_theme(qt_app)

    database = Database(db_path=tmp_path / "library.db")
    import ui.main_window as main_window

    monkeypatch.setattr(main_window, "db", database)
    monkeypatch.setattr(
        main_window.settings, "get_library_root", lambda: str(tmp_path / "Comics")
    )
    monkeypatch.setattr(main_window.settings, "has_library_root", lambda: False)

    from ui.main_window import MainWindow

    window = MainWindow(run_startup=False)
    window.resize(1200, 800)
    window.show()
    yield window
    window.close()


def test_the_portable_copy_is_never_checked_automatically(window, monkeypatch):
    monkeypatch.setattr(updater, "is_installed_copy", lambda: False)
    called = []
    monkeypatch.setattr(
        window, "_check_for_updates", lambda manual=False: called.append(manual)
    )

    window._auto_check_updates()

    assert called == []


def test_the_setting_can_turn_the_automatic_check_off(window, monkeypatch):
    import ui.main_window as main_window

    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "get_check_updates", lambda: False)
    called = []
    monkeypatch.setattr(
        window, "_check_for_updates", lambda manual=False: called.append(manual)
    )

    window._auto_check_updates()

    assert called == []


def test_the_installed_copy_asks_once_at_start(window, monkeypatch):
    import ui.main_window as main_window

    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "get_check_updates", lambda: True)
    called = []
    monkeypatch.setattr(
        window, "_check_for_updates", lambda manual=False: called.append(manual)
    )

    window._auto_check_updates()

    assert called == [False]


def test_a_newer_version_reaches_the_dialog(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "deferred_update", lambda: ("", ""))

    def fake_exec(dialog):
        shown.append(dialog)
        return 0

    monkeypatch.setattr(main_window.UpdateDialog, "exec", fake_exec)

    window._on_update_checked(make_info("2.5.0"), manual=True)

    assert shown and shown[0].info.version == "2.5.0"


def test_an_old_answer_never_opens_the_dialog(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog))
    toasts = []
    monkeypatch.setattr(window, "_toast", lambda message, kind="info": toasts.append(message))

    window._on_update_checked(make_info("2.4.0"), manual=True)

    assert shown == []
    assert toasts and "newest version" in toasts[0]


def test_a_postponed_version_is_not_shown_again(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog))
    monkeypatch.setattr(
        main_window.settings,
        "deferred_update",
        lambda: ("2.5.0", datetime.now(timezone.utc).isoformat()),
    )

    window._on_update_checked(make_info("2.5.0"), manual=False)

    assert shown == []


def test_a_manual_check_ignores_the_postponement(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog))
    monkeypatch.setattr(
        main_window.settings,
        "deferred_update",
        lambda: ("2.5.0", datetime.now(timezone.utc).isoformat()),
    )

    window._on_update_checked(make_info("2.5.0"), manual=True)

    assert shown and shown[0].info.version == "2.5.0"


def test_the_portable_edition_gets_a_link_instead_of_an_update(window, monkeypatch):
    offered = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: False)
    monkeypatch.setattr(window, "_offer_portable_download", offered.append)

    window._on_update_checked(make_info("2.5.0"), manual=True)

    assert offered and offered[0].version == "2.5.0"


def test_an_offline_check_only_warns_when_the_user_asked(window, monkeypatch):
    toasts = []
    monkeypatch.setattr(
        window, "_toast", lambda message, kind="info": toasts.append((message, kind))
    )

    window._on_update_failed("timeout", manual=False)
    assert toasts == []

    window._on_update_failed("timeout", manual=True)
    assert toasts and toasts[0][1] == "warning"


def test_closing_the_dialog_postpones_that_version(window, monkeypatch):
    import ui.main_window as main_window

    deferred = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "deferred_update", lambda: ("", ""))
    monkeypatch.setattr(main_window.settings, "defer_update", deferred.append)
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: 0)

    window._on_update_checked(make_info("2.5.0"), manual=False)

    assert deferred == ["2.5.0"]


def test_accepting_the_update_closes_the_app_for_the_helper(window, monkeypatch):
    import ui.main_window as main_window

    quit_called = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "deferred_update", lambda: ("", ""))
    monkeypatch.setattr(window, "_quit_for_update", lambda: quit_called.append(True))

    def fake_exec(dialog):
        dialog.applying = True
        return 1

    monkeypatch.setattr(main_window.UpdateDialog, "exec", fake_exec)

    window._on_update_checked(make_info("2.5.0"), manual=False)

    assert quit_called == [True]


def test_the_offer_waits_while_another_dialog_is_open(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "deferred_update", lambda: ("", ""))
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog))
    monkeypatch.setattr(window, "_busy_with_a_dialog", lambda: True)

    window._on_update_checked(make_info("2.5.0"), manual=False)

    assert shown == []
    assert window._pending_update is not None

    # Once the other dialog is gone the offer appears by itself.
    monkeypatch.setattr(window, "_busy_with_a_dialog", lambda: False)
    window._resume_pending_update()

    assert shown and shown[0].info.version == "2.5.0"
    assert window._pending_update is None


def test_the_background_check_clears_its_thread(window, monkeypatch):
    from PyQt6.QtTest import QTest

    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(updater, "fetch_latest_release", lambda: make_info("2.4.0"))
    seen = []
    monkeypatch.setattr(
        window, "_on_update_checked", lambda info, manual: seen.append((info, manual))
    )

    window._check_for_updates(manual=True)
    assert window._update_thread is not None
    for _ in range(50):
        QTest.qWait(20)
        if seen:
            break

    assert seen and seen[0][1] is True


def test_the_help_menu_offers_a_manual_check(window):
    actions = [action.text() for action in window.menuBar().actions()]
    assert "&Help" in actions
    help_menu = next(
        action.menu() for action in window.menuBar().actions() if action.text() == "&Help"
    )
    texts = [action.text() for action in help_menu.actions()]
    assert "Check for updates…" in texts
    assert "Check for updates automatically" in texts


def test_the_automatic_check_can_be_switched_off_from_the_menu(window, monkeypatch):
    import ui.main_window as main_window

    saved = []
    monkeypatch.setattr(main_window.settings, "set_check_updates", saved.append)
    toasts = []
    monkeypatch.setattr(window, "_toast", lambda message, kind="info": toasts.append(message))

    window.auto_update_action.setChecked(False)
    window.auto_update_action.setChecked(True)

    assert saved == [False, True]
    assert len(toasts) == 2
