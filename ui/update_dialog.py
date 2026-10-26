"""
update_dialog.py - the "a new version is ready" screen.

The window is opened with an :class:`UpdatePath` - every small per-version
package between the installed release and the newest one. Pressing the main
button downloads all of them, merges them into a single archive, verifies the
checksums and hands the result to the PowerShell helper that swaps the files and
restarts the app. Both the download and the installer call are injected, so the
tests can exercise the whole flow without a network or a Windows machine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QSize, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from config import APP_VERSION
from ui import layout as layout_tools
from ui import theme
from utils import updater
from utils.logger import logger


class UpdateCheckWorker(QThread):
    """Ask GitHub which releases exist and what it takes to reach the newest."""

    checked = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, current_version: str = APP_VERSION, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):  # noqa: D401 - Qt entry point
        try:
            releases = updater.fetch_releases()
        except Exception as exc:  # UpdateError or any network problem
            logger.info("Update check failed: %s", exc)
            self.failed.emit(str(exc))
            return
        try:
            plan = updater.plan_update_chain(self.current_version, releases)
        except Exception as exc:  # a broken plan must never break the window
            logger.warning("Could not plan the update: %s", exc)
            self.failed.emit(str(exc))
            return
        self.checked.emit(plan)


class UpdateDownloadWorker(QThread):
    """Download the patch package in the background."""

    progressed = pyqtSignal(int, int)
    downloaded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, download: Callable[[Callable[[int, int], None]], Path], parent=None):
        super().__init__(parent)
        self._download = download

    def run(self):  # noqa: D401 - Qt entry point
        try:
            path = self._download(self.progressed.emit)
        except Exception as exc:
            logger.warning("Update download failed: %s", exc)
            self.failed.emit(str(exc))
            return
        self.downloaded.emit(str(path))


class UpdateDialog(QDialog):
    """Offer the new version, then download and install it in place.

    *plan* says how many packages stand between the installed version and the
    newest release; they are downloaded one by one, merged into a single
    archive and installed in one go.
    """

    def __init__(
        self,
        plan: updater.UpdatePath,
        parent: Optional[QWidget] = None,
        *,
        download: Optional[Callable[[Callable[[int, int], None]], Path]] = None,
        install: Optional[Callable[[Path], None]] = None,
    ):
        super().__init__(parent)
        self.plan = plan
        self.info = self._target_info(plan)
        self.applying = False
        self._downloading = False
        self._thread: Optional[UpdateDownloadWorker] = None
        self._download = download or self._default_download
        self._install = install or self._default_install

        self.setWindowTitle("Update Digital Library")
        self.setModal(True)
        self._build_ui()
        # Resize before show() so the taller error page does not stretch the
        # offer page with empty space. The dialog still has to fit the screen.
        layout_tools.clamp_window(self, QSize(620, 440), QSize(420, 340))

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_offer_page())
        self.pages.addWidget(self._build_progress_page())
        self.pages.addWidget(self._build_error_page())
        layout.addWidget(self.pages)

    def _build_offer_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        badge = QLabel("UPDATE AVAILABLE")
        badge.setObjectName("SectionLabel")
        badge.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 700;")
        layout.addWidget(badge)

        title = QLabel(f"Digital Library {self.info.version} is ready")
        title.setObjectName("TitleLabel")
        title.setWordWrap(True)
        self.version_title = title
        layout.addWidget(title)

        can_install = bool(self.plan.steps) or self.plan.full_package is not None
        if can_install and len(self.plan.steps) > 1:
            subtitle_text = (
                f"You are running {APP_VERSION}. {len(self.plan.steps)} updates are "
                f"waiting ({self.plan.versions_text}). They are downloaded one by one, "
                "packed together and installed in one go, so only the changed files "
                "travel over the network and your library and settings stay where "
                "they are."
            )
        elif can_install and self.plan.full_package is not None:
            subtitle_text = (
                f"You are running {APP_VERSION}. The small per-version packages do "
                f"not reach this install, so this update takes the complete "
                f"{self.info.version} program once. Your library, readers and "
                "settings stay exactly where they are."
            )
        elif can_install:
            subtitle_text = (
                f"You are running {APP_VERSION}. The new version only replaces the "
                "files that changed, so the download stays small and your library, "
                "readers and settings stay exactly where they are."
            )
        else:
            subtitle_text = (
                f"You are running {APP_VERSION}, and {self.info.version} is available "
                "on the releases page."
            )
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.notes_browser = None
        notes = updater.release_notes_summary(self.plan.latest_notes or self.info.notes)
        if notes:
            browser = QTextBrowser()
            self.notes_browser = browser
            browser.setObjectName("UpdateNotes")
            browser.setOpenExternalLinks(True)
            browser.setPlainText(notes)
            browser.setMinimumHeight(140)
            browser.setMaximumHeight(210)
            browser.setStyleSheet(
                f"QTextBrowser {{ background: {theme.SURFACE};"
                f" border: 1px solid {theme.BORDER}; border-radius: 12px;"
                f" color: {theme.TEXT_MUTED}; padding: 10px; }}"
            )
            layout.addWidget(browser)

        details = []
        if self.plan.steps:
            packages = len(self.plan.steps)
            details.append(f"{packages} package{'s' if packages > 1 else ''}")
        elif can_install:
            details.append("complete program, one download")
        if self.plan.size_text:
            details.append(f"download size {self.plan.size_text}")
        details.append("SHA-256 checked before installing")
        if can_install:
            details.append("the app restarts by itself when the files are in place")
            if updater.needs_elevation():
                # The setup program installs under Program Files, so Windows
                # asks for administrator permission right after the download.
                details.append("Windows asks for administrator permission")
        hint = QLabel("  ·  ".join(details))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.later_button = QPushButton("Later")
        self.later_button.setObjectName("GhostButton")
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.later_button)

        self.download_button = QPushButton(
            "Download and install" if can_install else "Open download page"
        )
        self.download_button.setObjectName("PrimaryButton")
        self.download_button.setMinimumWidth(190)
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self._on_primary_clicked)
        buttons.addWidget(self.download_button)
        layout.addLayout(buttons)
        return page

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel(f"Downloading {self.info.version}…")
        if self.plan.steps and len(self.plan.steps) > 1:
            title.setText(f"Downloading {len(self.plan.steps)} updates…")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        self.progress_label = QLabel("Starting the download…")
        self.progress_label.setObjectName("SubtitleLabel")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        hint = QLabel(
            "Keep the window open. When the download is finished the app closes "
            "for a moment, replaces the changed files and opens again."
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_error_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("The update could not be installed")
        title.setObjectName("TitleLabel")
        title.setWordWrap(True)
        layout.addWidget(title)

        self.error_label = QLabel("")
        self.error_label.setObjectName("SubtitleLabel")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        hint = QLabel(
            "Your current version keeps working. You can try again, or download "
            "the installer from the releases page later."
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        self.page_button = QPushButton("Download the setup program")
        self.page_button.setObjectName("GhostButton")
        # A refused administrator prompt, a locked file or a full disk: the
        # setup program installs the same version without the in-place step.
        self.page_button.clicked.connect(
            lambda: self._open_page(updater.RELEASE_PAGE)
        )
        buttons.addWidget(self.page_button)
        buttons.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("GhostButton")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.retry_button = QPushButton("Try again")
        self.retry_button.setObjectName("PrimaryButton")
        self.retry_button.clicked.connect(self.start_download)
        buttons.addWidget(self.retry_button)
        layout.addLayout(buttons)
        return page

    @staticmethod
    def _target_info(plan: updater.UpdatePath) -> updater.UpdateInfo:
        if plan.steps:
            return plan.steps[-1]
        if plan.full_package is not None:
            return plan.full_package
        # No package to install: the dialog only offers the download page.
        return updater.UpdateInfo(
            version=plan.target or "",
            tag=f"v{plan.target}" if plan.target else "",
            notes="",
            page_url=updater.RELEASE_PAGE,
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _default_download(self, progress) -> Path:
        updater.cleanup_downloads()
        return updater.download_and_merge(self.plan, progress=progress)

    def _default_install(self, archive: Path) -> None:
        updater.install_update(archive)

    def _open_page(self, url: str):
        QDesktopServices.openUrl(QUrl(url or updater.RELEASE_PAGE))

    def _on_primary_clicked(self):
        if not self.plan.steps and self.plan.full_package is None:
            self._open_page(self.info.page_url)
            self.accept()
            return
        self.start_download()

    def start_download(self, inline: bool = False):
        """Download the package; ``inline`` is used by the headless tests."""
        if self._downloading:
            return
        self._downloading = True
        self.pages.setCurrentIndex(1)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting the download…")

        if inline:
            try:
                archive = self._download(self._on_progress)
            except Exception as exc:
                self._on_download_failed(str(exc))
                return
            self._on_downloaded(str(archive))
            return

        self._thread = UpdateDownloadWorker(self._download, self)
        self._thread.progressed.connect(self._on_progress)
        self._thread.downloaded.connect(self._on_downloaded)
        self._thread.failed.connect(self._on_download_failed)
        self._thread.start()

    def _on_progress(self, downloaded: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, 100)
            percent = max(0, min(100, int(downloaded * 100 / total)))
            self.progress_bar.setValue(percent)
            self.progress_label.setText(
                f"{downloaded / (1024 * 1024):.1f} of {total / (1024 * 1024):.1f} MB"
            )
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText(f"{downloaded / (1024 * 1024):.1f} MB downloaded")

    def _on_downloaded(self, archive: str):
        self._downloading = False
        self._thread = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText("Installing…")
        try:
            self._install(Path(archive))
        except Exception as exc:
            self._on_download_failed(str(exc))
            return
        self.applying = True
        self.accept()

    def _on_download_failed(self, message: str):
        self._downloading = False
        self._thread = None
        self.error_label.setText(message or "The download did not finish.")
        self.pages.setCurrentIndex(2)

    # ------------------------------------------------------------------
    # Window behaviour
    # ------------------------------------------------------------------
    def reject(self):  # noqa: D401 - Qt override
        if self._downloading:
            # Closing in the middle of a download would leave a helper without
            # a running app; the short download finishes first.
            return
        super().reject()

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        if self._downloading:
            event.ignore()
            return
        super().closeEvent(event)

