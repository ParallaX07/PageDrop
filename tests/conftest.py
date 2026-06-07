"""Shared pytest fixtures for PageDrop."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.fixtures.generate_fixtures import (
    ensure_fixtures,
    fixture_path,
)

# Headless Qt on CI/Linux; harmless on Windows when supported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "generated"


@pytest.fixture(scope="session")
def pdf_fixtures_dir() -> Path:
    """Session-scoped directory with generated PDF fixtures."""
    ensure_fixtures(FIXTURES_DIR)
    return FIXTURES_DIR


@pytest.fixture
def one_page_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "one_page")


@pytest.fixture
def five_page_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "five_page")


@pytest.fixture
def empty_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "empty")


@pytest.fixture
def corrupt_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "corrupt")


@pytest.fixture
def garbage_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "garbage")


@pytest.fixture
def main_window(qtbot):
    """Fresh MainWindow instance registered with qtbot."""
    from pagedrop.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window
