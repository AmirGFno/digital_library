"""
Reader settings dialog.

Lets the user choose the application used to open comics, override the choice
per file type, and register custom readers (any executable that accepts a file
path).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
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
    QRadioButton,
    QVBoxLayout,
)

from utils.logger import logger
from utils.reader_manager import (
    FORMAT_GROUPS,
    FORMAT_LABELS,
    SYSTEM_READER_ID,
    ReaderInfo,
    reader_manager,
)
from utils.settings import settings


class CustomReaderDialog(QDialog):
    """Small dialog to register an external application as a reader."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add custom reader")
        self.setMinimumWidth(520)
        self._reader_data: Optional[Dict] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Point to the executable of any comic reader (for example a portable "
            "CDisplayEx / ComicRack build) and choose which files it should open."
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
        filters = "Applications (*.exe *.app *.sh);;All files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Select reader executable", "", filters)
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
    """Configure the application used to open comic files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reader settings")
        self.setMinimumSize(640, 620)
        self._readers: List[ReaderInfo] = reader_manager.refresh()
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Comic reader")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Choose which application opens your comics. Popular readers are detected "
            "automatically; you can also point the app to any executable."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(subtitle)

        # Default reader -------------------------------------------------
        default_group = QGroupBox("Default application")
        default_layout = QVBoxLayout(default_group)
        self.system_radio = QRadioButton("Use the system default application")
        self.reader_radio = QRadioButton("Always open with:")
        default_layout.addWidget(self.system_radio)
        default_layout.addWidget(self.reader_radio)

        reader_row = QHBoxLayout()
        reader_row.addSpacing(22)
        self.default_combo = QComboBox()
        self.default_combo.currentIndexChanged.connect(self._update_default_path)
        reader_row.addWidget(self.default_combo, 1)
        default_layout.addLayout(reader_row)

        self.default_path_label = QLabel("")
        self.default_path_label.setObjectName("SubtitleLabel")
        self.default_path_label.setWordWrap(True)
        default_layout.addWidget(self.default_path_label)

        self.system_radio.toggled.connect(self._on_default_mode_changed)
        self.reader_radio.toggled.connect(self._on_default_mode_changed)
        layout.addWidget(default_group)

        # Per-format overrides -------------------------------------------
        format_group = QGroupBox("Per file type (optional)")
        grid = QGridLayout(format_group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.format_combos: Dict[str, QComboBox] = {}
        for row, group in enumerate(FORMAT_GROUPS):
            label = QLabel(FORMAT_LABELS[group])
            label.setWordWrap(True)
            combo = QComboBox()
            combo.setMinimumWidth(280)
            self.format_combos[group] = combo
            grid.addWidget(label, row, 0)
            grid.addWidget(combo, row, 1)
        layout.addWidget(format_group)

        # Detected readers -----------------------------------------------
        detected_group = QGroupBox("Readers on this computer")
        detected_layout = QVBoxLayout(detected_group)
        self.readers_list = QListWidget()
        self.readers_list.setMinimumHeight(150)
        self.readers_list.itemSelectionChanged.connect(self._update_buttons)
        detected_layout.addWidget(self.readers_list)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add custom reader...")
        self.add_button.clicked.connect(self._add_custom_reader)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_custom_reader)
        self.refresh_button = QPushButton("Detect again")
        self.refresh_button.clicked.connect(self._refresh_detection)
        self.test_button = QPushButton("Launch")
        self.test_button.setToolTip("Start the selected reader to verify it works")
        self.test_button.clicked.connect(self._test_reader)
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.remove_button)
        button_row.addWidget(self.refresh_button)
        button_row.addStretch()
        button_row.addWidget(self.test_button)
        detected_layout.addLayout(button_row)
        layout.addWidget(detected_group, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("SubtitleLabel")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox()
        save_button = QPushButton("Save settings")
        save_button.setObjectName("PrimaryButton")
        cancel_button = QPushButton("Cancel")
        buttons.addButton(save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------
    def _populate(self):
        readers = reader_manager.readers
        available = [reader for reader in readers if reader.available]

        self.default_combo.blockSignals(True)
        self.default_combo.clear()
        for reader in available:
            if reader.is_system:
                continue
            self.default_combo.addItem(reader.name, reader.id)
        self.default_combo.blockSignals(False)

        default_id = settings.get_default_reader_id()
        if default_id == SYSTEM_READER_ID or self.default_combo.count() == 0:
            self.system_radio.setChecked(True)
        else:
            index = self.default_combo.findData(default_id)
            if index >= 0:
                self.reader_radio.setChecked(True)
                self.default_combo.setCurrentIndex(index)
            else:
                # Configured reader disappeared: fall back gracefully.
                self.reader_radio.setChecked(True)
                self.default_combo.setCurrentIndex(0)

        for group, combo in self.format_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Use the default application", "")
            for reader in available:
                if reader.is_system or not reader.supports(group):
                    continue
                combo.addItem(reader.name, reader.id)
            current = settings.get_reader_settings().get("per_format", {}).get(group, "")
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        self._fill_readers_list()
        self._on_default_mode_changed()
        self.status_label.setText(
            f"{len([r for r in readers if r.available])} readers detected on this computer"
        )

    def _fill_readers_list(self):
        self.readers_list.clear()
        for reader in reader_manager.readers:
            if not reader.available and reader.source != "custom":
                continue
            location = reader.executable or "managed by the operating system"
            if reader.is_system:
                location = "uses the operating system association"
            item = QListWidgetItem(f"{reader.name}\n{location}")
            item.setData(Qt.ItemDataRole.UserRole, reader.id)
            if not reader.available:
                item.setToolTip("The configured path no longer exists")
            self.readers_list.addItem(item)
        self._update_buttons()

    def _update_buttons(self):
        reader = self._selected_reader()
        is_custom = bool(reader and reader.source == "custom")
        self.remove_button.setEnabled(is_custom)
        self.test_button.setEnabled(bool(reader and reader.available and not reader.is_system))

    def _selected_reader(self) -> Optional[ReaderInfo]:
        item = self.readers_list.currentItem()
        if not item:
            return None
        return reader_manager.get(item.data(Qt.ItemDataRole.UserRole))

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------
    def _on_default_mode_changed(self):
        custom = self.reader_radio.isChecked()
        self.default_combo.setEnabled(custom)
        self._update_default_path()

    def _update_default_path(self):
        reader = reader_manager.get(self.default_combo.currentData())
        if self.system_radio.isChecked() or reader is None:
            self.default_path_label.setText("")
            return
        self.default_path_label.setText(reader.executable)

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
        reader_manager.refresh()
        self._populate()
        index = self.default_combo.findData(reader.id)
        if index >= 0:
            self.reader_radio.setChecked(True)
            self.default_combo.setCurrentIndex(index)
        self.status_label.setText(f"Added {reader.name}")

    def _remove_custom_reader(self):
        reader = self._selected_reader()
        if not reader or reader.source != "custom":
            return
        answer = QMessageBox.question(
            self,
            "Remove reader",
            f"Remove '{reader.name}' from the list of readers?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        reader_manager.remove_custom_reader(reader.id)
        reader_manager.refresh()
        self._populate()

    def _refresh_detection(self):
        reader_manager.refresh()
        self._populate()
        QMessageBox.information(
            self,
            "Reader detection",
            "Detection finished. Installed readers are listed below.",
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
        default_id = (
            SYSTEM_READER_ID if self.system_radio.isChecked() else self.default_combo.currentData()
        )
        if not default_id:
            default_id = SYSTEM_READER_ID

        reader_settings = settings.settings.setdefault("reader", {})
        reader_settings["default"] = default_id
        reader_settings.setdefault("per_format", {})
        for group, combo in self.format_combos.items():
            reader_settings["per_format"][group] = combo.currentData() or ""
        if settings.save():
            self.accept()
        else:
            QMessageBox.critical(
                self, "Settings", "The settings file could not be written."
            )
