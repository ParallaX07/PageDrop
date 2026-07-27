"""Preferences dialog — Office conversion backends and LibreOffice path."""

from __future__ import annotations

from PyQt6.QtWidgets import (
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
from pagedrop.core.capabilities import clear_cache, probe_all
from pagedrop.ui.settings import (
    apply_office_settings_to_capabilities,
    office_preferred_backend,
    office_soffice_path,
    set_office_preferred_backend,
    set_office_soffice_path,
)


class PreferencesDialog(QDialog):
    """Modeless-friendly modal prefs: Office backend + soffice + Recheck."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setObjectName("PreferencesDialog")
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setSpacing(12)

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

        recheck_row = QHBoxLayout()
        self._recheck_btn = QPushButton("Recheck")
        self._recheck_btn.setObjectName("ToolbarSecondary")
        self._recheck_btn.clicked.connect(self._on_recheck)
        recheck_row.addWidget(self._recheck_btn)
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

    def _on_recheck(self) -> None:
        # Apply path into the registry before probing so Recheck sees it.
        set_office_soffice_path(self._soffice.text().strip() or None)
        set_office_preferred_backend(str(self._backend.currentData()))
        clear_cache()
        probe_all(refresh=True)
        self._refresh_status()
        report = capability_report(refresh=False)
        if report.any_available:
            QMessageBox.information(
                self,
                "Preferences",
                f"Backends updated.\n\n{report.status_line()}",
            )
        else:
            QMessageBox.warning(
                self,
                "Preferences",
                "Still no Office backend detected.\n\n"
                f"{report.status_line()}",
            )

    def _refresh_status(self) -> None:
        apply_office_settings_to_capabilities()
        # Reflect in-dialog edits without requiring OK yet for the soffice line
        # when recheck already applied; otherwise show last-saved + combo.
        from pagedrop.core.capabilities import set_configured_office_backend

        set_configured_office_backend(str(self._backend.currentData()))
        self._status.setText(capability_report().status_line())

    def _on_accept(self) -> None:
        set_office_preferred_backend(str(self._backend.currentData()))
        set_office_soffice_path(self._soffice.text().strip() or None)
        apply_office_settings_to_capabilities()
        self.accept()


def open_preferences(parent: QWidget | None = None) -> PreferencesDialog:
    """Show the Preferences dialog (modal). Returns the dialog instance."""
    dialog = PreferencesDialog(parent)
    dialog.exec()
    return dialog
