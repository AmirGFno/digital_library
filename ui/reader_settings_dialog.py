"""
Reader settings dialog.

The whole dialog is built around one question: *which application should open my
comics?* Pick a reader from the list, press **Save settings** and it is used from
then on.

A reader can also be overridden per file type (comics / PDF / images), and any
executable can be registered manually when automatic detection misses it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import layout as layout_tools
from ui import theme
from utils import rar_tools
from utils.logger import logger
from utils.reader_manager import (
    FORMAT_GROUPS,
    FORMAT_LABELS,
    ReaderInfo,
    reader_manager,
)
from utils.settings import settings


class CustomReaderDialog(QDialog):
    """Register an external application as a reader."""

    def __init__(self, parent=None, preselect: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add a reader")
        self.setMinimumWidth(560)
        self._reader_data: Optional[Dict] = None
        self._build_ui()
        if preselect:
            self.path_input.setText(preselect)
            self.name_input.setText(Path(preselect).stem)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Choose the .exe of any comic reader — a portable CDisplayEx build in "
            "your Downloads folder works just as well as an installed one."
        )
        intro.setWordWrap(True)
        intro.setObjectName("SubtitleLabel")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)

        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Path to the reader executable")
        path_row.addWidget(self.path_input, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        form.addRow("Executable:", path_row)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Shown in the reader menus")
        form.addRow("Name:", self.name_input)

        self.args_input = QLineEdit()
        self.args_input.setPlaceholderText('Optional, e.g. "{file}" or "--open {file}"')
        form.addRow("Arguments:", self.args_input)

        formats_row = QHBoxLayout()
        self.format_checks: Dict[str, QCheckBox] = {}
        for group in FORMAT_GROUPS:
            check = QCheckBox(group.capitalize())
            check.setChecked(True)
            self.format_checks[group] = check
            formats_row.addWidget(check)
        formats_row.addStretch()
        form.addRow("Opens:", formats_row)

        layout.addLayout(form)

        hint = QLabel(
            "{file} is replaced by the comic path. Leave the arguments empty to have "
            "the file path appended automatically."
        )
        hint.setWordWrap(True)
        hint.setObjectName("SubtitleLabel")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the reader executable", "",
            "Applications (*.exe *.app *.sh);;All files (*)",
        )
        if path:
            self.path_input.setText(path)
            if not self.name_input.text().strip():
                self.name_input.setText(Path(path).stem)

    def _accept(self):
        path = self.path_input.text().strip().strip('"')
        name = self.name_input.text().strip() or Path(path).stem
        if not path:
            QMessageBox.warning(self, "Missing path", "Please choose the reader executable.")
            return
        if not Path(path).exists():
            QMessageBox.warning(self, "Invalid path", f"This file does not exist:\n{path}")
            return
        groups = [group for group, check in self.format_checks.items() if check.isChecked()]
        if not groups:
            QMessageBox.warning(self, "Formats", "Select at least one file type.")
            return
        raw_args = self.args_input.text().strip()
        arguments = raw_args.split() if raw_args else []
        self._reader_data = {"name": name, "path": path, "formats": groups, "arguments": arguments}
        self.accept()

    def reader_data(self) -> Optional[Dict]:
        return self._reader_data


class ReaderSettingsDialog(QDialog):
    """Select the application used to open comics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reader settings")
        self._build_ui()
        self.reload()
        # The list of readers and the per-format overrides do not fit on a
        # laptop screen at 125 % scaling, so the body scrolls and the buttons
        # stay visible at the bottom of the window.
        layout_tools.clamp_window(self, QSize(760, 820), QSize(560, 460))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Which app should open your comics?")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Select a reader below and press Save settings. The chosen application is "
            "used for double-click, the Open menu and the “Open with” submenu."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(subtitle)

        # CBR/RAR status: it is the single most common reason for empty covers,
        # so it is shown here instead of hiding in a log file.
        self.rar_banner = QFrame()
        self.rar_banner.setObjectName("Chip")
        banner_layout = QHBoxLayout(self.rar_banner)
        banner_layout.setContentsMargins(12, 9, 12, 9)
        banner_layout.setSpacing(10)
        self.rar_dot = QLabel("●")
        self.rar_dot.setStyleSheet(f"color: {theme.GREEN}; font-size: 11px;")
        self.rar_label = QLabel(rar_tools.describe_support())
        self.rar_label.setWordWrap(True)
        self.rar_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px;"
        )
        banner_layout.addWidget(self.rar_dot)
        banner_layout.addWidget(self.rar_label, 1)
        if rar_tools.rar_support_available():
            self.rar_banner.setStyleSheet(
                f"QFrame#Chip {{ background-color: {theme.SURFACE};"
                f" border: 1px solid {theme.BORDER}; border-radius: 12px; }}"
            )
        else:
            self.rar_dot.setStyleSheet(f"color: {theme.GOLD}; font-size: 11px;")
            self.rar_banner.setStyleSheet(
                "QFrame#Chip { background-color: rgba(245, 181, 68, 22);"
                " border: 1px solid rgba(245, 181, 68, 90); border-radius: 12px; }"
            )
            self.rar_label.setStyleSheet(
                "color: #ffd79a; font-size: 11px;"
            )
        self.rar_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.rar_banner)

        # Reader list ----------------------------------------------------
        list_group = QGroupBox("Available readers")
        list_layout = QVBoxLayout(list_group)
        self.readers_list = QListWidget()
        self.readers_list.setMinimumHeight(220)
        self.readers_list.setSpacing(2)
        self.readers_list.currentItemChanged.connect(self._on_selection_changed)
        self.readers_list.itemDoubleClicked.connect(lambda _item: self._save())
        list_layout.addWidget(self.readers_list)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("SubtitleLabel")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        list_layout.addWidget(self.detail_label)

        self.add_button = QPushButton("Add custom reader...")
        self.add_button.clicked.connect(self._add_custom_reader)
        self.browse_button = QPushButton("Browse executable...")
        self.browse_button.setToolTip(
            "Point the app directly at CDisplayEx.exe or any other reader"
        )
        self.browse_button.clicked.connect(self._browse_executable)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_custom_reader)
        self.refresh_button = QPushButton("Detect again")
        self.refresh_button.clicked.connect(self._refresh_detection)
        self.test_button = QPushButton("Test launch")
        self.test_button.setToolTip("Start the selected reader to verify it works")
        self.test_button.clicked.connect(self._test_reader)

        primary_row = QHBoxLayout()
        primary_row.addWidget(self.add_button)
        primary_row.addWidget(self.browse_button)
        primary_row.addWidget(self.remove_button)
        primary_row.addStretch()

        secondary_row = QHBoxLayout()
        secondary_row.addStretch()
        secondary_row.addWidget(self.refresh_button)
        secondary_row.addWidget(self.test_button)

        list_layout.addLayout(primary_row)
        list_layout.addLayout(secondary_row)

        # Everything between the header and the buttons lives in a scroll
        # area: on a short screen the list stays usable instead of pushing
        # the Save button below the taskbar.
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        body_layout.addWidget(list_group, 1)

        # Per-format overrides -------------------------------------------
        format_group = QGroupBox("Different reader per file type (optional)")
        grid = QGridLayout(format_group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.format_combos: Dict[str, QComboBox] = {}
        for row, group in enumerate(FORMAT_GROUPS):
            label = QLabel(FORMAT_LABELS[group])
            label.setWordWrap(True)
            combo = QComboBox()
            combo.setMinimumWidth(260)
            self.format_combos[group] = combo
            grid.addWidget(label, row, 0)
            grid.addWidget(combo, row, 1)
        body_layout.addWidget(format_group)

        self.status_label = QLabel("")
        self.status_label.setObjectName("SubtitleLabel")
        body_layout.addWidget(self.status_label)

        self.scroll_area = layout_tools.wrap_in_scroll(body)
        layout.addWidget(self.scroll_area, 1)

        buttons = QDialogButtonBox()
        save_button = QPushButton("Save settings")
        save_button.setObjectName("PrimaryButton")
        save_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        buttons.addButton(save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def reload(self):
        reader_manager.refresh()
        self._fill_list()
        self._fill_format_combos()
        self._select_current_default()

        available = [
            reader
            for reader in reader_manager.readers
            if reader.available and not reader.is_system
        ]
        self.status_label.setText(
            f"{len(available)} reader(s) detected on this computer"
        )

    def _fill_list(self):
        self.readers_list.clear()
        for reader in reader_manager.readers:
            if reader.source == "detected" and not reader.available:
                continue
            if reader.is_system:
                text = "System default  —  let Windows decide"
            else:
                state = "" if reader.available else "   (missing)"
                source = "  •  added manually" if reader.source == "custom" else ""
                text = f"{reader.name}{state}{source}\n{reader.executable}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, reader.id)
            if not reader.available:
                item.setToolTip("This path does not exist any more")
            self.readers_list.addItem(item)

    def _fill_format_combos(self):
        available = [reader for reader in reader_manager.readers if reader.available]
        per_format = settings.get_reader_settings().get("per_format", {})
        for group, combo in self.format_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Use the default reader", "")
            for reader in available:
                if reader.is_system or not reader.supports(group):
                    continue
                combo.addItem(reader.name, reader.id)
            current = per_format.get(group, "") or ""
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _select_current_default(self):
        default_id = settings.get_default_reader_id()
        for row in range(self.readers_list.count()):
            item = self.readers_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == default_id:
                self.readers_list.setCurrentRow(row)
                return
        self.readers_list.setCurrentRow(0)

    def _selected_reader(self) -> Optional[ReaderInfo]:
        item = self.readers_list.currentItem()
        if not item:
            return None
        return reader_manager.get(item.data(Qt.ItemDataRole.UserRole))

    def _on_selection_changed(self, *_args):
        reader = self._selected_reader()
        if reader is None:
            self.detail_label.setText("")
            self.remove_button.setEnabled(False)
            self.test_button.setEnabled(False)
            return

        if reader.is_system:
            self.detail_label.setText(
                "Windows will pick the application registered for each file type."
            )
        elif reader.available:
            self.detail_label.setText(f"Path: {reader.executable}")
        else:
            self.detail_label.setText(
                "This reader is no longer at the saved path. Use “Browse executable...” "
                "to point to it again."
            )
        self.remove_button.setEnabled(reader.source == "custom")
        self.test_button.setEnabled(reader.available and not reader.is_system)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _add_custom_reader(self):
        dialog = CustomReaderDialog(self)
        if not dialog.exec():
            return
        data = dialog.reader_data()
        if not data:
            return
        reader = reader_manager.add_custom_reader(
            data["name"], data["path"], data["formats"], data["arguments"]
        )
        if not reader:
            QMessageBox.warning(self, "Custom reader", "The reader could not be registered.")
            return
        self.reload()
        self._select_reader(reader.id)
        self.status_label.setText(f"Added {reader.name}. Press Save settings to use it.")

    def _browse_executable(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the reader executable", "",
            "Applications (*.exe *.app *.sh);;All files (*)",
        )
        if not path:
            return
        dialog = CustomReaderDialog(self, preselect=path)
        if not dialog.exec():
            return
        data = dialog.reader_data()
        if not data:
            return
        reader = reader_manager.add_custom_reader(
            data["name"], data["path"], data["formats"], data["arguments"]
        )
        if reader:
            self.reload()
            self._select_reader(reader.id)
            self.status_label.setText(
                f"Added {reader.name}. Press Save settings to use it."
            )

    def _select_reader(self, reader_id: str):
        for row in range(self.readers_list.count()):
            item = self.readers_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == reader_id:
                self.readers_list.setCurrentRow(row)
                return

    def _remove_custom_reader(self):
        reader = self._selected_reader()
        if not reader or reader.source != "custom":
            return
        answer = QMessageBox.question(
            self, "Remove reader", f"Remove '{reader.name}' from the list of readers?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        reader_manager.remove_custom_reader(reader.id)
        self.reload()

    def _refresh_detection(self):
        rar_tools.configure_rarfile(force=True)
        self.rar_label.setText(rar_tools.describe_support())
        self.reload()
        QMessageBox.information(
            self,
            "Reader detection",
            "Detection finished. Readers installed on this computer are listed above.",
        )

    def _test_reader(self):
        reader = self._selected_reader()
        if not reader or not reader.available:
            return
        try:
            if reader.app_bundle:
                subprocess.Popen(["open", "-a", reader.executable])
            else:
                subprocess.Popen([reader.executable], close_fds=True)
            self.status_label.setText(f"Launched {reader.name}")
        except Exception as exc:
            logger.error(f"Could not launch {reader.name}: {exc}")
            QMessageBox.warning(
                self, "Launch failed", f"{reader.name} could not be started:\n{exc}"
            )

    def _save(self):
        reader = self._selected_reader()
        if reader is None:
            QMessageBox.warning(self, "Reader", "Select a reader first.")
            return
        if not reader.available:
            QMessageBox.warning(
                self,
                "Reader not found",
                f"{reader.name} is not at its saved path:\n{reader.executable}\n\n"
                "Use “Browse executable...” to point to it again.",
            )
            return

        reader_settings = settings.settings.setdefault("reader", {})
        reader_settings["default"] = reader.id
        reader_settings.setdefault("per_format", {})
        for group, combo in self.format_combos.items():
            reader_settings["per_format"][group] = combo.currentData() or ""

        if not settings.save():
            QMessageBox.critical(self, "Settings", "The settings file could not be written.")
            return

        # Read the file back to prove the choice really persisted.
        from utils.settings import Settings

        on_disk = Settings(settings.settings_file)
        saved_id = on_disk.get_default_reader_id()
        if saved_id != reader.id:
            QMessageBox.critical(
                self,
                "Settings",
                "The reader settings were not saved correctly.\n\n"
                f"Expected: {reader.id}\nFound: {saved_id}",
            )
            return

        self.status_label.setText(f"Saved — {reader.name} will open your comics")
        QMessageBox.information(
            self,
            "Settings saved",
            f"“{reader.name}” is now the default reader.\n\n"
            "Double-click a comic or use “Open” to test it.",
        )
        self.accept()
