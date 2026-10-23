"""
Folder import preview.

Before anything is written to the database the user sees:

* which folder becomes which series (names are editable)
* how many files are new and how many are already in the library
* the volume numbers that will be assigned
* a sample of the cleaned file names

This is what makes "import a folder" a one-click operation that still produces a
sensible structure: a series per subfolder, unique volume numbers and clean
titles.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from importer import FolderPlan, build_folder_plan_with_db, importer
from importer import ImportResult
from utils.logger import logger
from utils.settings import settings
from utils.text_cleaner import clean_file_stem

SAMPLE_LIMIT = 400


class FolderImportDialog(QDialog):
    """Preview and import a folder of comics."""

    def __init__(self, parent=None, folder: Optional[str] = None, mode: str = "auto"):
        super().__init__(parent)
        self.setWindowTitle("Import a folder")
        self.setMinimumSize(900, 680)
        self.folder_path = folder or ""
        self.plan: Optional[FolderPlan] = None
        self.result: Optional[ImportResult] = None
        self._mode = mode

        self._build_ui()
        if self.folder_path:
            self.folder_input.setText(self.folder_path)
            self.refresh_plan()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("Import a folder")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Each subfolder can become a series. Volume numbers are taken from the "
            "file names, duplicates are skipped and advertising text is removed."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(subtitle)

        # Folder row -----------------------------------------------------
        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Choose the folder that contains your comics")
        self.folder_input.editingFinished.connect(self.refresh_plan)
        folder_row.addWidget(self.folder_input, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        # Options --------------------------------------------------------
        options = QHBoxLayout()
        options.addWidget(QLabel("Structure:"))

        self.mode_single = QRadioButton("One series per folder")
        self.mode_subfolders = QRadioButton("One series per subfolder")
        self.mode_none = QRadioButton("No series")
        self.mode_single.setToolTip("Every comic in the folder joins a single series")
        self.mode_subfolders.setToolTip("Each immediate subfolder becomes its own series")
        self.mode_none.setToolTip("Just add the files, without creating series")

        for button in (self.mode_single, self.mode_subfolders, self.mode_none):
            button.toggled.connect(self._on_mode_changed)
            options.addWidget(button)

        self.clean_check = QCheckBox("Clean names")
        self.clean_check.setToolTip(
            "Remove site addresses, channel IDs and advertising words from titles"
        )
        self.clean_check.setChecked(settings.get_clean_names())
        options.addWidget(self.clean_check)

        self.metadata_check = QCheckBox("Read comic metadata")
        self.metadata_check.setChecked(True)
        options.addWidget(self.metadata_check)
        options.addStretch()
        layout.addLayout(options)

        # Tables ---------------------------------------------------------
        tabs = QTabWidget()
        tabs.addTab(self._build_groups_tab(), "Series")
        tabs.addTab(self._build_names_tab(), "Names")
        layout.addWidget(tabs, 1)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("SubtitleLabel")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        buttons = QDialogButtonBox()
        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self._import)
        cancel_button = QPushButton("Cancel")
        buttons.addButton(self.import_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_groups_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)

        self.question_label = QLabel(
            "Should a series with this same name be created?   "
            "سری با همین نام ساخته شود؟"
        )
        self.question_label.setObjectName("QuestionLabel")
        self.question_label.setWordWrap(True)
        layout.addWidget(self.question_label)

        self.groups_table = QTableWidget(0, 6)
        self.groups_table.setHorizontalHeaderLabels(
            ["Create", "Series name", "Files", "New", "Already in library", "Volumes"]
        )
        self.groups_table.verticalHeader().setVisible(False)
        self.groups_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        header = self.groups_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.groups_table, 1)

        hint = QLabel(
            "Tick a row to create that series, untick it to import those files "
            "without a series. You can also rename a series before importing."
        )
        hint.setObjectName("SubtitleLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _build_names_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)

        self.names_table = QTableWidget(0, 3)
        self.names_table.setHorizontalHeaderLabels(["File", "Title after import", "Volume"])
        self.names_table.verticalHeader().setVisible(False)
        self.names_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.names_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.names_table)

        hint = QLabel(
            "Preview of the first files: the name that will be stored, after removing "
            "advertising text, and the volume number that will be assigned."
        )
        hint.setObjectName("SubtitleLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------
    def _browse(self):
        start = self.folder_input.text().strip() or settings.get_last_import_folder()
        folder = QFileDialog.getExistingDirectory(self, "Select the comics folder", start)
        if folder:
            self.folder_input.setText(folder)
            settings.set_last_import_folder(folder)
            self.refresh_plan()

    def _selected_mode(self) -> str:
        if self._mode != "auto":
            return self._mode
        if self.mode_subfolders.isChecked():
            return "subfolders"
        if self.mode_none.isChecked():
            return "none"
        if self.mode_single.isChecked():
            return "single"
        # Nothing chosen yet: let the folder structure decide.
        return "auto"

    def _on_mode_changed(self, *_args):
        if self._mode != "auto":
            # A mode chosen by the caller (for example from drag & drop) stays.
            return
        self.refresh_plan()

    def refresh_plan(self):
        folder = self.folder_input.text().strip()
        if not folder or not Path(folder).is_dir():
            self.summary_label.setText("Choose a folder to see what will be imported.")
            return

        mode = self._selected_mode()
        self.plan = build_folder_plan_with_db(
            folder,
            database=importer.db,
            mode=mode,
            clean_names=self.clean_check.isChecked(),
        )

        # Reflect the detected mode in the radio buttons without recursing.
        for button in (self.mode_single, self.mode_subfolders, self.mode_none):
            button.blockSignals(True)
        if self.plan.mode == "subfolders":
            self.mode_subfolders.setChecked(True)
        elif self.plan.mode == "none":
            self.mode_none.setChecked(True)
        else:
            self.mode_single.setChecked(True)
        for button in (self.mode_single, self.mode_subfolders, self.mode_none):
            button.blockSignals(False)

        self._fill_groups_table()
        self._fill_names_table()
        self._update_summary()

    def _fill_groups_table(self):
        self.groups_table.setRowCount(0)
        if not self.plan:
            return

        for group in self.plan.groups:
            row = self.groups_table.rowCount()
            self.groups_table.insertRow(row)

            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            create_series = self.plan.mode != "none" and bool(group.default_name)
            check_item.setCheckState(
                Qt.CheckState.Checked if create_series else Qt.CheckState.Unchecked
            )
            check_item.setData(Qt.ItemDataRole.UserRole, group.key)
            self.groups_table.setItem(row, 0, check_item)

            name_item = QTableWidgetItem(group.default_name)
            name_item.setData(Qt.ItemDataRole.UserRole, group.key)
            self.groups_table.setItem(row, 1, name_item)

            for column, value in (
                (2, len(group.files)),
                (3, len(group.new_files)),
                (4, len(group.duplicates)),
            ):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.groups_table.setItem(row, column, item)

            span = group.volume_range if group.new_files else "-"
            item = QTableWidgetItem(span)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.groups_table.setItem(row, 5, item)

        self.groups_table.resizeRowsToContents()

    def _fill_names_table(self):
        self.names_table.setRowCount(0)
        if not self.plan:
            return

        shown = 0
        for group in self.plan.groups:
            assignments = {a.filepath: a for a in group.assignments}
            for filepath in group.new_files:
                if shown >= SAMPLE_LIMIT:
                    return
                row = self.names_table.rowCount()
                self.names_table.insertRow(row)
                self.names_table.setItem(row, 0, QTableWidgetItem(Path(filepath).name))

                title = (
                    clean_file_stem(filepath)
                    if self.clean_check.isChecked()
                    else Path(filepath).stem
                )
                self.names_table.setItem(row, 1, QTableWidgetItem(title))

                assignment = assignments.get(filepath)
                volume = assignment.volume if assignment else "-"
                item = QTableWidgetItem(volume)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.names_table.setItem(row, 2, item)
                shown += 1

    def _update_summary(self):
        if not self.plan:
            return
        if not self.plan.groups:
            self.summary_label.setText("No supported comic or book files were found here.")
            self.import_button.setEnabled(False)
            return

        self.import_button.setEnabled(self.plan.new_count > 0)
        text = (
            f"{self.plan.new_count} new file(s) will be added, "
            f"{self.plan.duplicate_count} already in the library will be skipped, "
            f"{len(self.plan.groups)} series."
        )
        if self.plan.new_count == 0:
            text = (
                "Everything in this folder is already in the library. "
                f"({self.plan.duplicate_count} file(s) skipped)"
            )
        self.summary_label.setText(text)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def _series_names(self) -> Dict[str, Optional[str]]:
        """Answer the question per folder: build this series, or only the files?"""
        names: Dict[str, Optional[str]] = {}
        if self.plan is not None and self.plan.mode == "none":
            # "No series" mode: import everything without creating series.
            return {group.key: None for group in self.plan.groups}
        for row in range(self.groups_table.rowCount()):
            check = self.groups_table.item(row, 0)
            name_item = self.groups_table.item(row, 1)
            if check is None or name_item is None:
                continue
            key = check.data(Qt.ItemDataRole.UserRole)
            name = name_item.text().strip()
            if check.checkState() != Qt.CheckState.Checked or not name:
                names[key] = None
            else:
                names[key] = name
        return names

    def _import(self):
        if not self.plan or self.plan.new_count == 0:
            return

        settings.set_clean_names(self.clean_check.isChecked())

        progress = QProgressDialog("Importing comics...", None, 0, self.plan.new_count, self)
        progress.setWindowTitle("Importing")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def on_progress(index, total, filepath):
            progress.setMaximum(total)
            progress.setValue(index - 1)
            progress.setLabelText(f"Importing {Path(filepath).name}...")
            QApplication.processEvents()

        try:
            self.result = importer.import_plan(
                self.plan,
                series_names=self._series_names(),
                use_metadata=self.metadata_check.isChecked(),
                clean_names=self.clean_check.isChecked(),
                progress=on_progress,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Folder import failed")
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        finally:
            progress.setValue(self.plan.new_count)

        self.accept()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def summary_text(self) -> str:
        if not self.result:
            return ""
        text = self.result.summary()
        if self.result.errors:
            text += "\n" + "\n".join(self.result.errors[:5])
        return text
