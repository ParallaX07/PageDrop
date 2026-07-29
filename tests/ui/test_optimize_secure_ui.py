"""Phase 27 UI — Optimize & Secure modeless shells."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from pagedrop.ui.optimize_secure_shell import (
    SHELL_OPTIMIZE_SECURE_IDS,
    _LOSSY_QUALITY_WARNING,
    open_optimize_secure_shell,
    password_strength_label,
)
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow
from tests.core.test_jobs import _encrypted_pdf


def _write_pdf(path: Path, *, text: str = "hello") -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), text, fontsize=18)
        doc.save(str(path))
    finally:
        doc.close()


def test_password_strength_label() -> None:
    assert password_strength_label("") == "Enter a password"
    assert password_strength_label("abc") == "Weak"
    assert password_strength_label("CorrectHorseBattery9!") == "Strong"


def test_optimize_secure_tiles_open_shells(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    by_id = {t.entry.id: t.entry for t in tools._tiles}
    for tool_id in SHELL_OPTIMIZE_SECURE_IDS:
        assert tool_id in by_id
        assert by_id[tool_id].action == "optimize_secure"
        assert not by_id[tool_id].coming_soon
        shell = open_optimize_secure_shell(tools, tool_id)
        assert shell is not None
        assert isinstance(shell, ToolShellWindow)
        assert shell.isVisible()
        qtbot.addWidget(shell)
        shell.close()
    tools.close()


def test_compress_lossy_presets_and_quality_warning(qtbot, isolated_settings):
    """Lossy profiles are wired; quality warning is visible before Run."""
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_optimize_secure_shell(tools, "compress")
    assert shell is not None
    qtbot.addWidget(shell)

    combo = shell._compress_profile
    values = [combo.itemData(i) for i in range(combo.count())]
    assert values == ["lossless", "fast", "max", "screen", "ebook", "print"]
    assert "does not use lossy" not in shell._compress_hint.text().lower()
    assert not shell._compress_warning.isVisible()

    idx = combo.findData("screen")
    assert idx >= 0
    combo.setCurrentIndex(idx)
    assert shell._compress_warning.isVisible()
    assert _LOSSY_QUALITY_WARNING in shell._compress_warning.text()
    assert "same quality" not in shell._compress_hint.text().lower()
    assert "72" in shell._compress_hint.text()

    shell.close()
    tools.close()


def test_encrypt_password_mismatch_blocked(qtbot, tmp_path, monkeypatch, isolated_settings):
    pdf = tmp_path / "src.pdf"
    _write_pdf(pdf)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_optimize_secure_shell(tools, "encrypt")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])

    shell._encrypt_user_pw.setText("one-password")
    shell._encrypt_confirm_pw.setText("different")

    warned: list[str] = []

    def fake_warning(parent, title, text):
        warned.append(text)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    save_called = {"n": 0}

    def fake_save(*_a, **_k):
        save_called["n"] += 1
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)

    shell._run_btn.click()
    assert any("do not match" in t for t in warned)
    assert save_called["n"] == 0
    assert shell._encrypt_mismatch.isVisible()
    shell.close()
    tools.close()


def test_decrypt_prompts_for_password(qtbot, tmp_path, monkeypatch, isolated_settings):
    enc = tmp_path / "locked.pdf"
    out = tmp_path / "unlocked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = enc.read_bytes()

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_optimize_secure_shell(tools, "decrypt")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(enc)])

    prompts: list[tuple[str, bool]] = []

    def fake_prompt(parent, filename, *, incorrect=False):
        prompts.append((filename, incorrect))
        return "secret"

    monkeypatch.setattr(
        "pagedrop.ui.tool_shell.prompt_pdf_password",
        fake_prompt,
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), "PDF files (*.pdf)"),
    )

    shell._run_btn.click()
    qtbot.waitUntil(lambda: out.is_file(), timeout=10_000)
    assert prompts == [("locked.pdf", False)]

    check = fitz.open(str(out))
    try:
        assert not check.needs_pass
        assert check.page_count == 1
    finally:
        check.close()

    assert enc.read_bytes() == source_hash
    shell.close()
    tools.close()


def test_decrypt_rejects_unencrypted(qtbot, tmp_path, monkeypatch, isolated_settings):
    pdf = tmp_path / "plain.pdf"
    _write_pdf(pdf)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_optimize_secure_shell(tools, "decrypt")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])

    infos: list[str] = []

    def fake_info(parent, title, text):
        infos.append(text)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_info)
    shell._run_btn.click()
    assert any("not encrypted" in t for t in infos)
    shell.close()
    tools.close()


def test_encrypt_job_uses_secrets_not_options(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    """Passwords stay off JobSpec; runner receives them via secrets."""
    pdf = tmp_path / "src.pdf"
    out = tmp_path / "enc.pdf"
    _write_pdf(pdf)

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_optimize_secure_shell(tools, "encrypt")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(pdf)])
    shell._encrypt_user_pw.setText("user-secret")
    shell._encrypt_confirm_pw.setText("user-secret")

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), "PDF files (*.pdf)"),
    )

    captured: dict = {}
    real_run = shell.job_runner().run

    def spy_run(spec, **kwargs):
        captured["spec"] = spec
        captured["secrets"] = dict(kwargs.get("secrets") or {})
        return real_run(spec, **kwargs)

    monkeypatch.setattr(shell.job_runner(), "run", spy_run)
    shell._run_btn.click()
    qtbot.waitUntil(lambda: out.is_file(), timeout=10_000)

    assert "user_password" not in captured["spec"].options
    assert captured["secrets"].get("user_password") == "user-secret"
    persisted = captured["spec"].to_persistable_dict()
    assert "user-secret" not in str(persisted)

    locked = fitz.open(str(out))
    try:
        assert locked.needs_pass
        assert locked.authenticate("user-secret") != 0
    finally:
        locked.close()
    shell.close()
    tools.close()


def test_sanitize_cancel_mid_run_clears_busy_chrome(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    """O13: Cancel mid sanitize annot loop → no promote, BusyOverlay clears."""
    import hashlib
    import time

    from pagedrop.core import optimize_secure as ops
    from PyQt6.QtWidgets import QCheckBox

    src = tmp_path / "multi.pdf"
    doc = fitz.open()
    try:
        for i in range(8):
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), f"page {i}", fontsize=14)
            page.add_highlight_annot(fitz.Rect(30, 60, 120, 90))
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    out = tmp_path / "sanitized.pdf"

    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_optimize_secure_shell(tools, "sanitize")
    assert shell is not None
    qtbot.addWidget(shell)
    shell.drop_zone.set_paths([str(src)])

    # Enable annotation strip so the page annot loop runs cancel checks.
    for box in shell._options_host.findChildren(QCheckBox):
        if "annotation" in box.text().casefold():
            box.setChecked(True)

    monkeypatch.setattr(
        "pagedrop.ui.optimize_secure_shell._pick_save_path",
        lambda parent, title, suggested: str(out),
    )

    real_check = ops._check_cancel
    checks = {"n": 0}

    def wait_for_ui_cancel(cancel):
        checks["n"] += 1
        if checks["n"] == 1:
            deadline = time.time() + 5.0
            while not cancel.is_cancelled() and time.time() < deadline:
                time.sleep(0.01)
        real_check(cancel)

    monkeypatch.setattr(ops, "_check_cancel", wait_for_ui_cancel)

    shell._run_btn.click()
    qtbot.waitUntil(
        lambda: (
            shell.is_job_running()
            and checks["n"] >= 1
            and shell._busy_overlay._cancel_btn.isVisible()
        ),
        timeout=5000,
    )
    assert shell._busy_overlay.isVisible()
    shell._busy_overlay._cancel_btn.click()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=15000)

    assert not out.exists()
    assert not shell._busy_overlay.isVisible()
    assert shell.statusBar().currentMessage() == "Cancelled"
    assert hashlib.sha256(src.read_bytes()).hexdigest() == source_hash

    shell.close()
    tools.close()
