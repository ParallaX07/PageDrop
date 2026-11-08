"""Bundled UI font: registration, fallbacks and non-Latin file names."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo
from PyQt6.QtWidgets import QApplication

import pagedrop.assets as assets
from pagedrop.ui.tab_manager import DetachableTabBar
from pagedrop.ui.theme import FONT_UI_FAMILIES, app_stylesheet, apply_app_font

WRITING = QFontDatabase.WritingSystem


@pytest.fixture
def registered_fonts():
    assert assets.register_fonts() == 4


def test_registration_makes_public_sans_resolve_at_every_weight(registered_fonts):
    assert "Public Sans" in QFontDatabase.families()
    for weight in (400, 500, 600, 700):
        font = QFont("Public Sans")
        font.setWeight(QFont.Weight(weight))
        info = QFontInfo(font)
        assert info.family() == "Public Sans"
        assert info.weight() == weight


def test_missing_font_files_log_a_warning_and_do_not_raise(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(assets, "fonts_dir", lambda: tmp_path / "does-not-exist")
    with caplog.at_level(logging.WARNING, logger="pagedrop"):
        assert assets.register_fonts() == 0
    assert any("fonts" in r.getMessage().lower() for r in caplog.records)


def test_unreadable_font_logs_a_warning_and_loads_the_rest(monkeypatch, tmp_path, caplog):
    for src in assets.fonts_dir().glob("*.ttf"):
        (tmp_path / src.name).write_bytes(src.read_bytes())
    (tmp_path / "Broken.ttf").write_bytes(b"not a font")
    monkeypatch.setattr(assets, "fonts_dir", lambda: tmp_path)
    with caplog.at_level(logging.WARNING, logger="pagedrop"):
        assert assets.register_fonts() == 4
    assert any("Broken.ttf" in r.getMessage() for r in caplog.records)


def test_resource_lookup_failure_logs_a_warning_and_does_not_raise(monkeypatch, caplog):
    def boom() -> Path:
        raise FileNotFoundError("no resources")

    monkeypatch.setattr(assets, "fonts_dir", boom)
    with caplog.at_level(logging.WARNING, logger="pagedrop"):
        assert assets.register_fonts() == 0
    assert any("no resources" in r.getMessage() for r in caplog.records)


def test_app_font_uses_the_stack_and_keeps_its_size(qtbot):
    app = QApplication.instance()
    original = app.font()
    try:
        apply_app_font(app)
        font = app.font()
        assert tuple(font.families()) == FONT_UI_FAMILIES
        assert font.pointSizeF() == original.pointSizeF()
    finally:
        app.setFont(original)


def test_app_font_is_safe_when_registration_failed(monkeypatch, tmp_path, qtbot):
    monkeypatch.setattr(assets, "fonts_dir", lambda: tmp_path / "does-not-exist")
    assert assets.register_fonts() == 0
    app = QApplication.instance()
    original = app.font()
    try:
        apply_app_font(app)
        assert QFontInfo(app.font()).family()
    finally:
        app.setFont(original)


def _tab_pixels(bar: DetachableTabBar, text: str):
    bar.setTabText(0, text)
    return bar.grab().toImage()


@pytest.mark.parametrize(
    ("writing_system", "first", "second"),
    [
        (WRITING.Cyrillic, "Отчет.pdf", "Банки.pdf"),
        (WRITING.SimplifiedChinese, "报告文件.pdf", "预算表格.pdf"),
    ],
    ids=["cyrillic", "cjk"],
)
def test_non_latin_file_names_shape_in_a_tab(qtbot, registered_fonts, writing_system, first, second):
    if not QFontDatabase.families(writing_system):
        pytest.skip(f"no installed font covers {writing_system.name}")
    app = QApplication.instance()
    original = app.font()
    apply_app_font(app)
    try:
        bar = DetachableTabBar()
        bar.setStyleSheet(app_stylesheet())
        qtbot.addWidget(bar)
        bar.addTab("x")
        bar.resize(320, 40)
        bar.show()
        qtbot.waitExposed(bar)
        # Same-script strings with different letters: tofu boxes would match.
        assert _tab_pixels(bar, first) != _tab_pixels(bar, second)
    finally:
        app.setFont(original)
