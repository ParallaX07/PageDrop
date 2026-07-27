"""Optimize & Secure — Phase 22b modeless shells (Phase 27 UI)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from pagedrop.core.pdf_loader import PdfLoader, PdfPasswordRequiredError
from pagedrop.core.supported_formats import is_pdf_path
from pagedrop.ui.organize_tools import editor_pdf_context
from pagedrop.ui.settings import remember_directory
from pagedrop.ui.tool_shell import ToolShellWindow, run_tool_job

if TYPE_CHECKING:
    from pagedrop.ui.tools_window import ToolsWindow

SHELL_OPTIMIZE_SECURE_IDS: frozenset[str] = frozenset(
    {"compress", "repair", "encrypt", "decrypt", "sanitize"}
)

_PDF_FILTER = "PDF files (*.pdf);;All files (*)"

_PERMISSION_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("allow_print", "Print", True),
    ("allow_print_hq", "High-quality print", True),
    ("allow_copy", "Copy text and images", True),
    ("allow_modify", "Modify contents", True),
    ("allow_annotate", "Annotate", True),
    ("allow_form", "Fill forms", True),
    ("allow_assemble", "Assemble / insert pages", True),
    ("allow_accessibility", "Accessibility extract", True),
)

_OUTPUT_SUFFIX: dict[str, str] = {
    "compress": "_compressed",
    "repair": "_repaired",
    "encrypt": "_encrypted",
    "decrypt": "_decrypted",
    "sanitize": "_sanitized",
}


def password_strength_label(password: str) -> str:
    """Heuristic strength label for the encrypt options panel (not zxcvbn)."""
    if not password:
        return "Enter a password"
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if any(c.islower() for c in password) and any(c.isupper() for c in password):
        score += 1
    if any(c.isdigit() for c in password):
        score += 1
    if any(not c.isalnum() for c in password):
        score += 1
    if score <= 1:
        return "Weak"
    if score <= 3:
        return "Fair"
    return "Strong"


def _pick_save_path(parent: QWidget, title: str, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(
        parent, title, suggested, _PDF_FILTER
    )
    if not path:
        return None
    remember_directory(path)
    if not path.lower().endswith(".pdf"):
        path = f"{path}.pdf"
    return path


def _suggested_output(source: str, tool_id: str) -> str:
    path = Path(source)
    return str(path.with_name(f"{path.stem}{_OUTPUT_SUFFIX[tool_id]}{path.suffix}"))


def _pdf_needs_password(path: str) -> bool:
    try:
        loader = PdfLoader(path)
    except PdfPasswordRequiredError:
        return True
    else:
        loader.close()
        return False


def _configure_compress(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    profile = QComboBox()
    profile.addItem("Lossless (recommended)", "lossless")
    profile.addItem("Fast", "fast")
    profile.addItem("Maximum cleanup", "max")
    form.addRow("Profile", profile)
    hint = QLabel(
        "Writes a new copy with garbage collection and deflate. "
        "Does not use lossy recompression or linearize."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save compressed PDF", _suggested_output(source, "compress")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="compress",
            inputs=[source],
            output=output,
            options={"profile": profile.currentData()},
            progress_message="Compressing PDF…",
        )

    shell.set_run_handler(on_run)


def _configure_repair(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    hint = QLabel(
        "Opens the PDF tolerantly and rewrites a clean copy. "
        "Source file is never overwritten."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save repaired PDF", _suggested_output(source, "repair")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="repair",
            inputs=[source],
            output=output,
            progress_message="Repairing PDF…",
        )

    shell.set_run_handler(on_run)


def _configure_encrypt(shell: ToolShellWindow) -> None:
    options = QWidget()
    root = QFormLayout(options)
    root.setContentsMargins(0, 0, 0, 0)

    user_pw = QLineEdit()
    user_pw.setEchoMode(QLineEdit.EchoMode.Password)
    user_pw.setAccessibleName("User password")
    confirm_pw = QLineEdit()
    confirm_pw.setEchoMode(QLineEdit.EchoMode.Password)
    confirm_pw.setAccessibleName("Confirm password")
    owner_pw = QLineEdit()
    owner_pw.setEchoMode(QLineEdit.EchoMode.Password)
    owner_pw.setPlaceholderText("Same as user password if empty")
    owner_pw.setAccessibleName("Owner password")

    strength = QLabel("Enter a password")
    strength.setObjectName("ToolsHint")
    strength.setAccessibleName("Password strength")

    mismatch = QLabel("")
    mismatch.setObjectName("ToolsHint")
    mismatch.setStyleSheet("color: #b00020;")
    mismatch.hide()

    def _refresh_strength() -> None:
        strength.setText(password_strength_label(user_pw.text()))
        if confirm_pw.text() and confirm_pw.text() != user_pw.text():
            mismatch.setText("Passwords do not match")
            mismatch.show()
        else:
            mismatch.hide()

    user_pw.textChanged.connect(lambda _t: _refresh_strength())
    confirm_pw.textChanged.connect(lambda _t: _refresh_strength())

    root.addRow("Password", user_pw)
    root.addRow("Confirm", confirm_pw)
    root.addRow("Strength", strength)
    root.addRow("", mismatch)
    root.addRow("Owner password", owner_pw)

    enc = QComboBox()
    enc.addItem("AES-256 (recommended)", "AES-256")
    enc.addItem("AES-128", "AES-128")
    root.addRow("Encryption", enc)

    perm_box = QGroupBox("Permissions")
    perm_box.setObjectName("EncryptPermissions")
    grid = QGridLayout(perm_box)
    grid.setContentsMargins(8, 8, 8, 8)
    checks: dict[str, QCheckBox] = {}
    for i, (key, label, default) in enumerate(_PERMISSION_FIELDS):
        cb = QCheckBox(label)
        cb.setChecked(default)
        checks[key] = cb
        grid.addWidget(cb, i // 2, i % 2)

    root.addRow(perm_box)
    shell.set_options_widget(options)
    # Expose for tests.
    shell._encrypt_user_pw = user_pw  # type: ignore[attr-defined]
    shell._encrypt_confirm_pw = confirm_pw  # type: ignore[attr-defined]
    shell._encrypt_mismatch = mismatch  # type: ignore[attr-defined]
    shell._encrypt_strength = strength  # type: ignore[attr-defined]

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        password = user_pw.text()
        if not password:
            QMessageBox.warning(shell, shell.WINDOW_TITLE, "Enter a password.")
            return
        if password != confirm_pw.text():
            mismatch.setText("Passwords do not match")
            mismatch.show()
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                "Password and confirmation do not match.",
            )
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save encrypted PDF", _suggested_output(source, "encrypt")
        )
        if not output:
            return
        secrets = {"user_password": password}
        owner = owner_pw.text()
        if owner:
            secrets["owner_password"] = owner
        run_tool_job(
            shell,
            job_type="encrypt",
            inputs=[source],
            output=output,
            options={
                "encryption": enc.currentData(),
                "permissions": {k: cb.isChecked() for k, cb in checks.items()},
            },
            secrets=secrets,
            progress_message="Encrypting PDF…",
        )
        # Clear password fields after launch (secrets already copied into job).
        user_pw.clear()
        confirm_pw.clear()
        owner_pw.clear()

    shell.set_run_handler(on_run)


def _configure_decrypt(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    hint = QLabel(
        "Writes an unlocked copy. You will be asked for the PDF password when "
        "you run. Source file is never overwritten."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        source = paths[0]
        if not _pdf_needs_password(source):
            QMessageBox.information(
                shell,
                shell.WINDOW_TITLE,
                "This PDF is not encrypted.",
            )
            return
        output = _pick_save_path(
            shell, "Save decrypted PDF", _suggested_output(source, "decrypt")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="decrypt",
            inputs=[source],
            output=output,
            progress_message="Decrypting PDF…",
        )

    shell.set_run_handler(on_run)


def _configure_sanitize(shell: ToolShellWindow) -> None:
    options = QWidget()
    form = QFormLayout(options)
    form.setContentsMargins(0, 0, 0, 0)
    strip_meta = QCheckBox("Strip document metadata")
    strip_meta.setChecked(True)
    strip_xmp = QCheckBox("Strip XMP metadata")
    strip_xmp.setChecked(True)
    strip_annots = QCheckBox("Remove annotations")
    strip_annots.setChecked(False)
    form.addRow(strip_meta)
    form.addRow(strip_xmp)
    form.addRow(strip_annots)
    hint = QLabel(
        "Scrubs metadata into a new file. Annotation removal deletes existing "
        "markup only — authoring and redaction are separate tools."
    )
    hint.setObjectName("ToolsHint")
    hint.setWordWrap(True)
    form.addRow(hint)
    shell.set_options_widget(options)

    def on_run() -> None:
        paths = shell.drop_zone.paths()
        if not paths:
            return
        if not (
            strip_meta.isChecked()
            or strip_xmp.isChecked()
            or strip_annots.isChecked()
        ):
            QMessageBox.warning(
                shell,
                shell.WINDOW_TITLE,
                "Choose at least one sanitize option.",
            )
            return
        source = paths[0]
        output = _pick_save_path(
            shell, "Save sanitized PDF", _suggested_output(source, "sanitize")
        )
        if not output:
            return
        run_tool_job(
            shell,
            job_type="sanitize",
            inputs=[source],
            output=output,
            options={
                "strip_metadata": strip_meta.isChecked(),
                "strip_xmp": strip_xmp.isChecked(),
                "strip_annotations": strip_annots.isChecked(),
            },
            progress_message="Sanitizing PDF…",
        )

    shell.set_run_handler(on_run)


_CONFIGURERS = {
    "compress": _configure_compress,
    "repair": _configure_repair,
    "encrypt": _configure_encrypt,
    "decrypt": _configure_decrypt,
    "sanitize": _configure_sanitize,
}


def open_optimize_secure_shell(
    tools: ToolsWindow, tool_id: str
) -> ToolShellWindow | None:
    """Lazy-create / raise a Phase 27 Optimize & Secure shell."""
    from pagedrop.ui.tools_window import TOOL_CATALOGUE

    if tool_id not in SHELL_OPTIMIZE_SECURE_IDS:
        return None
    entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
    if entry is None:
        return None

    store: dict[str, ToolShellWindow] = getattr(tools, "_tool_shells", None) or {}
    tools._tool_shells = store  # type: ignore[attr-defined]

    shell = store.get(tool_id)
    ctx = editor_pdf_context(tools.editor)

    if shell is None:
        shell = ToolShellWindow(
            title=entry.title,
            description=entry.description,
            editor=tools.editor,
            window_manager=getattr(tools, "_window_manager", None),
            multi=False,
            accept=is_pdf_path,
            dialog_filter=_PDF_FILTER,
            browse_title=f"Choose PDF — {entry.title}",
        )
        _CONFIGURERS[tool_id](shell)
        store[tool_id] = shell
    else:
        shell.set_editor(tools.editor)

    if ctx is not None and Path(ctx.path).is_file():
        shell.drop_zone.set_paths([ctx.path])

    shell.show()
    shell.raise_()
    shell.activateWindow()
    return shell
