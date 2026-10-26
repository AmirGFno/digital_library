"""Toasts must survive their own life cycle.

The reported crash was ``RuntimeError: wrapped C/C++ object of type Toast has
been deleted``: the manager kept a reference to a toast that had already
deleted itself, and the next notification touched that dead wrapper.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def host(qt_app):
    from PyQt6.QtWidgets import QWidget

    window = QWidget()
    window.resize(900, 700)
    window.show()
    yield window
    window.close()


def _wait(_window, msecs):
    """Pump the event loop: timers, animations and deleteLater all need it."""
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    QTest.qWait(msecs)
    for _ in range(5):
        QApplication.processEvents()


def test_a_new_toast_after_a_closed_one(qt_app, host):
    from ui.widgets import ToastManager

    manager = ToastManager(host)
    manager.show("first", "info", msecs=120)
    _wait(host, 500)
    assert manager._toasts == []

    manager.show("second", "success", msecs=4000)  # used to raise RuntimeError
    _wait(host, 60)
    assert len(manager._toasts) == 1


def test_many_toasts_in_a_row(qt_app, host):
    from ui.widgets import ToastManager

    manager = ToastManager(host)
    for index in range(6):
        manager.show(f"message {index}", "info", msecs=80)
        _wait(host, 30)
    _wait(host, 600)
    assert manager._toasts == []


def test_toasts_of_a_destroyed_window_are_ignored(qt_app):
    from PyQt6.QtWidgets import QWidget

    from ui.widgets import ToastManager

    window = QWidget()
    window.show()
    manager = ToastManager(window)
    manager.show("before closing", "info", msecs=2000)
    _wait(window, 60)
    window.close()
    window.deleteLater()
    _wait(window, 60)

    assert manager.show("after closing", "info") is None


def test_at_most_three_toasts_are_kept(qt_app, host):
    from ui.widgets import ToastManager

    manager = ToastManager(host)
    for index in range(5):
        manager.show(f"message {index}", "info", msecs=4000)
        _wait(host, 40)
    assert len(manager._toasts) == ToastManager.MAX_VISIBLE
