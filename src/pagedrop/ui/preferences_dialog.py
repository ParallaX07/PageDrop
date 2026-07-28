"""Preferences dialog — accessibility, Office backends, LibreOffice path, OCR tessdata."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.backends.office import capability_report
from pagedrop.core.capabilities import TESSDATA, clear_cache, probe, probe_all
from pagedrop.core.tessdata_pack import download_eng_fast, user_tessdata_dir
from pagedrop.ui.settings import (
    apply_office_settings_to_capabilities,
    apply_tessdata_settings_to_capabilities,
    office_preferred_backend,
    office_soffice_path,
    reduce_motion,
    set_office_preferred_backend,
    set_office_soffice_path,
    set_reduce_motion,
    set_tessdata_path,
    tessdata_path,
)


class PreferencesDialog(QDialog):
    """Modeless-friendly modal prefs: accessibility + Office/OCR + Recheck."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setObjectName("PreferencesDialog")
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        a11y_heading = QLabel("Accessibility")
        a11y_heading.setObjectName("PreferencesSection")
        root.addWidget(a11y_heading)

        self._reduce_motion = QCheckBox("Reduce motion")
        self._reduce_motion.setObjectName("PreferencesReduceMotion")
        self._reduce_motion.setToolTip(
            "Minimize non-essential animation (skeleton pulse, hover shadows). "
            "Platform reduce-motion settings are still honored when available."
        )
        self._reduce_motion.setChecked(reduce_motion())
        root.addWidget(self._reduce_motion)

        heading = QLabel("Office to PDF")
        heading.setObjectName("PreferencesSection")
        root.addWidget(heading)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self._backend = QComboBox()
        self._backend.addItem("Auto (COM when available, else LibreOffice)", "auto")
        self._backend.addItem("Microsoft Office (COM)", "com")
        self._backend.addItem("LibreOffice", "libreoffice")
        current = office_preferred_backend()
        index = self._backend.findData(current)
        self._backend.setCurrentIndex(max(0, index))
        form.addRow("Preferred backend", self._backend)

        path_row = QHBoxLayout()
        self._soffice = QLineEdit(office_soffice_path())
        self._soffice.setPlaceholderText("Detect automatically (PATH / install dirs)")
        self._soffice.setClearButtonEnabled(True)
        browse = QPushButton("Browse…")
        browse.setObjectName("ToolbarSecondary")
        browse.clicked.connect(self._browse_soffice)
        path_row.addWidget(self._soffice, stretch=1)
        path_row.addWidget(browse)
        form.addRow("LibreOffice soffice", path_row)

        root.addLayout(form)

        self._status = QLabel()
        self._status.setObjectName("ToolsHint")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        ocr_heading = QLabel("OCR (tessdata)")
        ocr_heading.setObjectName("PreferencesSection")
        root.addWidget(ocr_heading)

        ocr_form = QFormLayout()
        ocr_form.setContentsMargins(0, 0, 0, 0)
        tess_row = QHBoxLayout()
        self._tessdata = QLineEdit(tessdata_path())
        self._tessdata.setPlaceholderText(
            "Auto-detect, or folder containing *.traineddata"
        )
        self._tessdata.setClearButtonEnabled(True)
        tess_browse = QPushButton("Browse…")
        tess_browse.setObjectName("ToolbarSecondary")
        tess_browse.clicked.connect(self._browse_tessdata)
        tess_row.addWidget(self._tessdata, stretch=1)
        tess_row.addWidget(tess_browse)
        ocr_form.addRow("tessdata folder", tess_row)
        root.addLayout(ocr_form)

        self._ocr_status = QLabel()
        self._ocr_status.setObjectName("ToolsHint")
        self._ocr_status.setWordWrap(True)
        root.addWidget(self._ocr_status)

        recheck_row = QHBoxLayout()
        self._recheck_btn = QPushButton("Recheck")
        self._recheck_btn.setObjectName("ToolbarSecondary")
        self._recheck_btn.clicked.connect(self._on_recheck)
        self._download_eng_btn = QPushButton("Download eng…")
        self._download_eng_btn.setObjectName("ToolbarSecondary")
        self._download_eng_btn.setToolTip(
            "Download tessdata_fast English into the user data folder"
        )
        self._download_eng_btn.clicked.connect(self._on_download_eng)
        recheck_row.addWidget(self._recheck_btn)
        recheck_row.addWidget(self._download_eng_btn)
        recheck_row.addStretch(1)
        root.addLayout(recheck_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._refresh_status()

    def _browse_soffice(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Locate soffice",
            self._soffice.text().strip() or "",
            "Executable (*);;All files (*)",
        )
        if path:
            self._soffice.setText(path)

    def _browse_tessdata(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Locate tessdata folder",
            self._tessdata.text().strip() or str(user_tessdata_dir()),
        )
        if chosen:
            self._tessdata.setText(chosen)

    def _on_download_eng(self) -> None:
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Question)
        confirm.setWindowTitle("Download eng tessdata")
        dest = user_tessdata_dir()
        confirm.setText("Download English (tessdata_fast) language data?")
        confirm.setInformativeText(
            f"Saves eng.traineddata to:\n{dest}\n\n"
            "PageDrop never downloads language data silently — only when you ask."
        )
        download_btn = confirm.addButton(
            "Download", QMessageBox.ButtonRole.AcceptRole
        )
        confirm.addButton(QMessageBox.StandardButton.Cancel)
        confirm.setDefaultButton(download_btn)
        confirm.exec()
        if confirm.clickedButton() is not download_btn:
            return
        try:
            path = download_eng_fast(dest_dir=dest)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Download eng tessdata", str(exc))
            return
        self._tessdata.setText(str(path.parent))
        set_tessdata_path(path.parent)
        clear_cache()
        probe_all(refresh=True)
        self._refresh_status()
        QMessageBox.information(
            self,
            "Download eng tessdata",
            f"Saved:\n{path}",
        )

    def _on_recheck(self) -> None:
        # Apply path into the registry before probing so Recheck sees it.
        set_office_soffice_path(self._soffice.text().strip() or None)
        set_office_preferred_backend(str(self._backend.currentData()))
        set_tessdata_path(self._tessdata.text().strip() or None)
        clear_cache()
        probe_all(refresh=True)
        self._refresh_status()
        report = capability_report(refresh=False)
        tess = probe(TESSDATA)
        lines = [report.status_line(), self._tess_line(tess)]
        if report.any_available or tess.available:
            QMessageBox.information(
                self,
                "Preferences",
                "Backends updated.\n\n" + "\n".join(lines),
            )
        else:
            QMessageBox.warning(
                self,
                "Preferences",
                "Still no Office / OCR backends detected.\n\n" + "\n".join(lines),
            )

    @staticmethod
    def _tess_line(status) -> str:
        if status.available:
            langs = status.extras.get("languages") or []
            return f"OCR: {len(langs)} language(s) at {status.extras.get('path')}"
        return f"OCR: {status.detail}"

    def _refresh_status(self) -> None:
        apply_office_settings_to_capabilities()
        apply_tessdata_settings_to_capabilities()
        # Reflect in-dialog edits without requiring OK yet for the soffice line
        # when recheck already applied; otherwise show last-saved + combo.
        from pagedrop.core.capabilities import (
            set_configured_office_backend,
            set_configured_tessdata_path,
        )

        set_configured_office_backend(str(self._backend.currentData()))
        set_configured_tessdata_path(self._tessdata.text().strip() or None)
        self._status.setText(capability_report().status_line())
        self._ocr_status.setText(self._tess_line(probe(TESSDATA)))

    def _on_accept(self) -> None:
        set_reduce_motion(self._reduce_motion.isChecked())
        set_office_preferred_backend(str(self._backend.currentData()))
        set_office_soffice_path(self._soffice.text().strip() or None)
        set_tessdata_path(self._tessdata.text().strip() or None)
        apply_office_settings_to_capabilities()
        apply_tessdata_settings_to_capabilities()
        self.accept()


def open_preferences(parent: QWidget | None = None) -> PreferencesDialog:
    """Show the Preferences dialog (modal). Returns the dialog instance."""
    dialog = PreferencesDialog(parent)
    dialog.exec()
    return dialog
