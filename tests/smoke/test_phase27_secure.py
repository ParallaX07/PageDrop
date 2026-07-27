"""Phase 27 smoke — encrypt → open via editor password dialog."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QInputDialog

from pagedrop.core import optimize_secure as ops


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(path: Path, *, text: str = "phase27 secret") -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), text, fontsize=18)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_smoke_encrypt_then_open_with_password_dialog(
    main_window, tmp_path, monkeypatch, qtbot
) -> None:
    src = _make_pdf(tmp_path / "plain.pdf")
    source_hash = _file_hash(src)
    enc = tmp_path / "locked.pdf"
    password = "gate-secret"

    ops.encrypt_pdf(str(src), str(enc), user_password=password)
    assert _file_hash(src) == source_hash
    assert enc.resolve() != src.resolve()
    enc_hash = _file_hash(enc)

    locked = fitz.open(str(enc))
    try:
        assert locked.needs_pass
        assert locked.authenticate("wrong") == 0
    finally:
        locked.close()

    prompts: list[str] = []
    replies = iter([("wrong", True), (password, True)])

    def fake_get_text(parent, title, label, *args, **kwargs):
        prompts.append(label)
        return next(replies)

    monkeypatch.setattr(QInputDialog, "getText", fake_get_text)

    main_window._load_pdf(str(enc))

    assert len(prompts) == 2
    assert "password-protected" in prompts[0]
    assert "Incorrect password" in prompts[1]
    assert main_window._loader is not None
    assert main_window._loader.page_count == 1
    qtbot.waitUntil(
        lambda: len(main_window._thumbnail_grid._cards) == 1,
        timeout=15_000,
    )
    assert enc.name in main_window.windowTitle()
    assert _file_hash(src) == source_hash
    assert _file_hash(enc) == enc_hash
