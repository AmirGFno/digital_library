"""The update prompt: the dialog itself and the window that opens it."""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PyQt6 import QtWidgets

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config import APP_VERSION  # noqa: E402
from utils import updater  # noqa: E402


def next_version(version, step=1):
    """2.4.2 + 1 -> 2.4.3, so the tests follow the shipped version."""
    parts = [int(part) for part in str(version).split(".")]
    parts[-1] += step
    return ".".join(str(part) for part in parts)


def step(version, from_version, size=2 * 1024 * 1024, notes=""):
    return updater.UpdateInfo(
        version=version,
        tag=f"v{version}",
        notes=notes or f"Notes for {version}\nsecond line",
        page_url=f"https://example.test/releases/{version}",
        asset_url=f"https://example.test/{version}.zip",
        asset_name=f"DigitalLibrary-{version}-from-{from_version}-windows-x64-update.zip",
        asset_size=size,
        checksum_url="https://example.test/SHA256.txt",
        from_version=from_version,
    )


def chain_plan(count=2, first_from=APP_VERSION):
    steps = []
    current = first_from
    for index in range(1, count + 1):
        target = next_version(first_from, index)
        steps.append(step(target, current))
        current = target
    return updater.UpdatePath(target=steps[-1].version, steps=steps)


def full_plan(version=None):
    version = version or next_version(APP_VERSION, 30)
    package = updater.UpdateInfo(
        version=version,
        tag=f"v{version}",
        notes="Everything at once",
        page_url=f"https://example.test/releases/{version}",
        asset_url="https://example.test/full.zip",
        asset_name=f"DigitalLibrary-{version}-windows-x64-update.zip",
        asset_size=50 * 1024 * 1024,
        checksum_url="https://example.test/SHA256.txt",
    )
    return updater.UpdatePath(target=version, steps=[], full_package=package)


def empty_plan(version=None):
    version = version or next_version(APP_VERSION, 30)
    return updater.UpdatePath(target=version, steps=[], missing_from="2.0.0")


# ----------------------------------------------------------------------
# The dialog
# ----------------------------------------------------------------------
def test_the_dialog_counts_the_waiting_updates(qt_app):
    from ui.update_dialog import UpdateDialog

    plan = chain_plan(3)
    dialog = UpdateDialog(plan)

    assert dialog.pages.count() == 3
    assert dialog.pages.currentIndex() == 0
    assert dialog.download_button.text() == "Download and install"
    assert dialog.later_button.text() == "Later"
    assert plan.target in dialog.version_title.text()
    texts = " | ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
    assert "3 updates" in texts
    # the notes come from the newest release
    assert f"Notes for {plan.target}" in dialog.notes_browser.toPlainText()


def test_the_dialog_says_how_many_packages_and_how_big(qt_app):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(chain_plan(3))

    labels = [
        label.text()
        for label in dialog.findChildren(type(dialog.error_label))
    ]
    joined = " | ".join(labels)
    assert "3 packages" in joined
    assert "6.0 MB" in joined  # 3 × 2 MB


def test_confirming_downloads_all_steps_and_installs_once(qt_app):
    from ui.update_dialog import UpdateDialog

    downloaded = []
    installed = []

    def download(report):
        downloaded.append(True)
        report(1 * 1024 * 1024, 4 * 1024 * 1024)
        report(4 * 1024 * 1024, 4 * 1024 * 1024)
        return Path("/tmp/merged-update.zip")

    dialog = UpdateDialog(
        chain_plan(2), download=download, install=lambda path: installed.append(path)
    )
    dialog.start_download(inline=True)

    assert downloaded == [True]
    assert installed == [Path("/tmp/merged-update.zip")]
    assert dialog.applying is True
    assert dialog.result() == dialog.DialogCode.Accepted


def test_the_progress_bar_follows_the_whole_chain(qt_app):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(chain_plan(2))
    dialog._on_progress(1024 * 1024, 4 * 1024 * 1024)
    assert dialog.progress_bar.value() == 25
    dialog._on_progress(2 * 1024 * 1024, 0)  # unknown size -> busy bar
    assert dialog.progress_bar.maximum() == 0


def test_a_failed_download_keeps_the_current_version_installed(qt_app):
    from ui.update_dialog import UpdateDialog

    def broken(report):
        raise updater.UpdateError("no internet")

    dialog = UpdateDialog(chain_plan(2), download=broken)
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
        chain_plan(2),
        download=lambda report: Path("/tmp/merged.zip"),
        install=broken_install,
    )
    dialog.start_download(inline=True)

    assert dialog.pages.currentIndex() == 2
    assert "locked" in dialog.error_label.text()
    assert dialog.applying is False


def test_a_full_package_is_offered_like_any_other_update(qt_app):
    from ui.update_dialog import UpdateDialog

    plan = full_plan()
    dialog = UpdateDialog(plan)

    assert dialog.download_button.text() == "Download and install"
    assert dialog.plan.target in dialog.version_title.text()
    assert dialog.plan.count == 1


def test_a_full_package_says_that_it_is_the_whole_program(qt_app):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(full_plan())
    texts = " | ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))

    assert f"complete {dialog.plan.target} program" in texts
    assert "complete program, one download" in texts
    assert "only replaces the files that changed" not in texts


def test_a_plan_without_a_package_opens_the_download_page(qt_app):
    from ui.update_dialog import UpdateDialog

    opened = []
    dialog = UpdateDialog(empty_plan())
    dialog._open_page = opened.append

    assert dialog.download_button.text() == "Open download page"
    dialog.download_button.click()

    assert opened == ["https://github.com/AmirGFno/digital_library/releases/latest"]
    assert dialog.applying is False


def test_the_window_cannot_be_closed_mid_download(qt_app):
    from ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(chain_plan(2))
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


def test_a_chain_reaches_the_dialog(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "deferred_update", lambda: ("", ""))
    monkeypatch.setattr(
        main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog)
    )

    plan = chain_plan(3)
    window._on_update_checked(plan, manual=True)

    assert shown and len(shown[0].plan.steps) == 3
    assert shown[0].plan.target == plan.target


def test_an_old_answer_never_opens_the_dialog(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog))
    toasts = []
    monkeypatch.setattr(window, "_toast", lambda message, kind="info": toasts.append(message))

    window._on_update_checked(updater.UpdatePath(target=APP_VERSION), manual=True)

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
        lambda: (chain_plan(2).target, datetime.now(timezone.utc).isoformat()),
    )

    window._on_update_checked(chain_plan(2), manual=False)

    assert shown == []


def test_a_manual_check_ignores_the_postponement(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog))
    monkeypatch.setattr(
        main_window.settings,
        "deferred_update",
        lambda: (chain_plan(2).target, datetime.now(timezone.utc).isoformat()),
    )

    window._on_update_checked(chain_plan(2), manual=True)

    assert shown


def test_a_broken_chain_sends_the_user_to_the_setup_program(window, monkeypatch):
    offered = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(window, "_offer_full_download", offered.append)

    plan = empty_plan()
    window._on_update_checked(plan, manual=True)

    assert offered == [plan]


def test_the_portable_edition_gets_a_link_instead_of_an_update(window, monkeypatch):
    offered = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: False)
    monkeypatch.setattr(window, "_offer_portable_download", offered.append)

    window._on_update_checked(chain_plan(2), manual=True)

    assert offered == [chain_plan(2).target]


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

    window._on_update_checked(chain_plan(2), manual=False)

    assert deferred == [chain_plan(2).target]


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

    window._on_update_checked(chain_plan(2), manual=False)

    assert quit_called == [True]


def test_the_offer_waits_while_another_dialog_is_open(window, monkeypatch):
    import ui.main_window as main_window

    shown = []
    monkeypatch.setattr(updater, "is_installed_copy", lambda: True)
    monkeypatch.setattr(main_window.settings, "deferred_update", lambda: ("", ""))
    monkeypatch.setattr(main_window.UpdateDialog, "exec", lambda dialog: shown.append(dialog))
    monkeypatch.setattr(window, "_busy_with_a_dialog", lambda: True)

    window._on_update_checked(chain_plan(2), manual=False)

    assert shown == []
    assert window._pending_update is not None

    monkeypatch.setattr(window, "_busy_with_a_dialog", lambda: False)
    window._resume_pending_update()

    assert shown and shown[0].plan.target == chain_plan(2).target
    assert window._pending_update is None


def test_the_background_check_plans_the_whole_chain(window, monkeypatch):
    from PyQt6.QtTest import QTest

    from config import APP_VERSION

    current = [int(part) for part in APP_VERSION.split(".")]
    second = list(current)
    second[-1] += 1
    third = list(second)
    third[-1] += 1
    second_version = ".".join(str(part) for part in second)
    third_version = ".".join(str(part) for part in third)

    def payload(version, from_version):
        return {
            "tag_name": f"v{version}",
            "html_url": f"https://example.test/v{version}",
            "body": "notes",
            "assets": [
                {
                    "name": (
                        f"DigitalLibrary-{version}-from-{from_version}"
                        "-windows-x64-update.zip"
                    ),
                    "browser_download_url": f"https://example.test/{version}.zip",
                    "size": 10,
                }
            ],
        }

    payloads = [
        payload(third_version, second_version),
        payload(second_version, APP_VERSION),
    ]
    real_fetch = updater.fetch_releases
    opener = _opener(payloads, updater.RELEASES_API)
    monkeypatch.setattr(updater, "fetch_releases", lambda: real_fetch(opener=opener))
    seen = []
    monkeypatch.setattr(
        window, "_on_update_checked", lambda plan, manual: seen.append((plan, manual))
    )

    window._check_for_updates(manual=True)
    for _ in range(100):
        QTest.qWait(20)
        if seen:
            break

    plan, manual = seen[0]
    assert manual is True
    assert plan.target == third_version
    assert [step.version for step in plan.steps] == [second_version, third_version]
    assert plan.steps[0].from_version == APP_VERSION


def _opener(payload, url):
    import io
    import json

    class Response:
        headers = {}

        def read(self, *args):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout=10):
        return Response()

    return opener


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
