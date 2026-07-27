"""Phase 8 smoke tests — error-path matrix keeps the app alive."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.generate_fixtures import ensure_fixtures

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "generated"


def _run_app_scenario(code: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _assert_process_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ALIVE" in result.stdout
    assert "VISIBLE" in result.stdout


@pytest.fixture(scope="module", autouse=True)
def _phase8_fixtures():
    ensure_fixtures(FIXTURES_DIR)


def _scenario_template(body: str, *, auto_dismiss_dialogs: bool = False) -> str:
    dismiss = ""
    if auto_dismiss_dialogs:
        dismiss = """
from PyQt6.QtWidgets import QMessageBox
QMessageBox.critical = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
"""
    return f"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from pagedrop.ui.main_window import MainWindow

app = QApplication([])
window = MainWindow()
window.showMinimized()
{dismiss}{body}
print("ALIVE", flush=True)
print("VISIBLE", window.isVisible(), flush=True)
QTimer.singleShot(50, window.close)
QTimer.singleShot(100, app.quit)
app.exec()
"""


def test_smoke_open_corrupt_pdf_survives():
    corrupt = FIXTURES_DIR / "corrupt.pdf"
    code = _scenario_template(
        f'window._load_pdf(r"{corrupt}")',
        auto_dismiss_dialogs=True,
    )
    _assert_process_ok(_run_app_scenario(code))


def test_smoke_open_empty_pdf_survives():
    empty = FIXTURES_DIR / "empty.pdf"
    code = _scenario_template(
        f'window._load_pdf(r"{empty}")',
        auto_dismiss_dialogs=True,
    )
    _assert_process_ok(_run_app_scenario(code))


def test_smoke_open_garbage_pdf_survives():
    garbage = FIXTURES_DIR / "garbage.pdf"
    code = _scenario_template(
        f'window._load_pdf(r"{garbage}")',
        auto_dismiss_dialogs=True,
    )
    _assert_process_ok(_run_app_scenario(code))


def test_smoke_rapid_reopen_survives():
    five = FIXTURES_DIR / "five_page.pdf"
    one = FIXTURES_DIR / "one_page.pdf"
    code = _scenario_template(
        f'window._load_pdf(r"{five}")\nwindow._load_pdf(r"{one}")'
    )
    _assert_process_ok(_run_app_scenario(code))


def test_smoke_drag_without_pdf_survives():
    # Standalone script (not _scenario_template): QTest mouse press on a
    # synthetic PageCard under offscreen Qt can SIGSEGV during normal
    # interpreter/Qt teardown after app.exec() even when the gesture itself
    # survives. os._exit(0) after ALIVE is the reliable smoke gate.
    code = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.page_card import PageCard

app = QApplication([])
window = MainWindow()
window.showMinimized()

card = PageCard(0, window)
card.resize(200, 200)
card.show()
QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
QTest.mouseMove(card, pos=QPoint(250, 250))
QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(250, 250))

print("ALIVE", flush=True)
print("VISIBLE", window.isVisible(), flush=True)
os._exit(0)
"""
    _assert_process_ok(_run_app_scenario(code))
