"""Phase 29 UI — OCR tile capability gate + configure dialog."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QHideEvent
from PyQt6.QtWidgets import QApplication, QWidget

from pagedrop.core.capabilities import (
    TESSDATA,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
)
from pagedrop.core.tessdata_pack import TessdataDownloadError
from pagedrop.ui import dialogs
from pagedrop.ui.busy_overlay import BusyOverlay
from pagedrop.ui.dialogs import build_missing_tessdata_dialog
from pagedrop.ui.preferences_dialog import PreferencesDialog
from pagedrop.ui.settings import tessdata_path
from pagedrop.ui.ocr_shell import SHELL_OCR_IDS, open_ocr_shell
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow


def test_ocr_tile_blocked_when_tessdata_absent(monkeypatch, qtbot, isolated_settings):
    clear_cache()

    def _fake_probe(capability_id: str, refresh: bool = False) -> CapabilityStatus:
        del refresh
        if capability_id == TESSDATA:
            return CapabilityStatus(
                id=TESSDATA,
                available=False,
                reason=AbsenceReason.DATA_MISSING,
                detail="missing in test",
            )
        return CapabilityStatus(id=capability_id, available=True)

    monkeypatch.setattr("pagedrop.ui.tools_window.probe", _fake_probe)
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    by_id = {t.entry.id: t for t in window._tiles}
    tile = by_id["ocr_pdf"]
    assert tile.is_blocked()
    assert "Data missing" in tile._subtitle.text()
    assert by_id["extract_tables"].entry.action == "extract_tables"
    assert not by_id["extract_tables"].is_blocked()
    window.close()


def test_missing_tessdata_dialog_has_download_configure_recheck(qtbot):
    dialog = build_missing_tessdata_dialog(None, subject="OCR", detail="none found")
    qtbot.addWidget(dialog)
    names = {b.objectName() for b in dialog.buttons() if b.objectName()}
    assert "tess_recheck" in names
    assert "tess_download" in names
    assert "tess_configure" in names
    assert "Language data missing" in dialog.text()


def test_ocr_and_tables_shells_open(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    for tool_id in sorted(SHELL_OCR_IDS):
        shell = open_ocr_shell(tools, tool_id)
        assert shell is not None
        assert isinstance(shell, ToolShellWindow)
        assert shell.isVisible()
        qtbot.addWidget(shell)
        shell.close()
    tools.close()


class _Download:
    """Stub for ``download_eng_fast`` that blocks until released or cancelled."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.thread: int | None = None
        self.token = None
        self.error: Exception | None = None
        self.ignore_cancel = False
        self.timeout: float | None = None

    def __call__(self, *, dest_dir, cancel=None, on_progress=None, **_kw) -> Path:
        self.thread = threading.get_ident()
        self.token = cancel
        self.timeout = _kw.get("timeout")
        self.started.set()
        for _ in range(500):  # bounded so a blocked GUI thread fails, not hangs
            if self.release.wait(0.01):
                break
            if not self.ignore_cancel:
                cancel.check()
        else:
            raise TessdataDownloadError("stub timed out")
        if self.error is not None:
            raise self.error
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / "eng.traineddata"
        target.write_bytes(b"stub")
        return target


@pytest.fixture
def download(monkeypatch, tmp_path, isolated_settings):
    stub = _Download()
    dest = tmp_path / "tessdata"
    warnings: list[str] = []
    stub.warnings = warnings
    stub.dest = dest
    monkeypatch.setattr(dialogs, "download_eng_fast", stub)
    monkeypatch.setattr(dialogs, "user_tessdata_dir", lambda: dest)
    monkeypatch.setattr(
        dialogs.QMessageBox, "exec", lambda self: self.defaultButton().click() or 0
    )
    monkeypatch.setattr(
        dialogs.QMessageBox,
        "warning",
        staticmethod(lambda _p, _t, text, *_a: warnings.append(text)),
    )
    monkeypatch.setattr(
        dialogs.QMessageBox, "information", staticmethod(lambda *_a: 0)
    )
    yield stub
    stub.release.set()
    dialogs._tessdata_pool().waitForDone(5000)
    clear_cache()


def _drive(qtbot, call, stub, action):
    """Run *call* (which spins a local loop); fire *action* once the loop has ticked."""
    ticks: list[int] = []
    fired: list[bool] = []

    def tick() -> None:
        if not stub.started.is_set():
            return
        ticks.append(1)
        if len(ticks) == 3 and not fired:
            fired.append(True)
            action()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(10)
    try:
        result = call()
    finally:
        timer.stop()
    assert fired, "the event loop kept running while the download was blocked"
    return result


def _prefs(qtbot):
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog, dialog._on_download_eng


def _missing_data_prompt(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    return host, lambda: dialogs._download_eng_tessdata(host)


ENTRY_POINTS = [pytest.param(_prefs, id="preferences"), pytest.param(_missing_data_prompt, id="prompt")]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_tessdata_download_runs_off_gui_thread_and_saves(qtbot, download, entry):
    parent, call = entry(qtbot)

    def finish() -> None:
        assert parent.findChild(BusyOverlay).isVisible()
        download.release.set()

    _drive(qtbot, call, download, finish)

    assert download.thread != threading.get_ident()
    assert download.timeout == 30.0
    if entry is _prefs:
        # Preferences keep the download unsaved until OK.
        assert not tessdata_path()
        assert parent._tessdata.text() == str(download.dest)
    else:
        assert tessdata_path() == str(download.dest)
    assert (download.dest / "eng.traineddata").exists()
    assert download.warnings == []


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_tessdata_download_cancel_reaches_token_and_changes_nothing(
    qtbot, download, entry
):
    parent, call = entry(qtbot)

    def cancel() -> None:
        parent.findChild(BusyOverlay)._cancel_btn.click()

    _drive(qtbot, call, download, cancel)

    assert download.token.is_cancelled()
    assert not tessdata_path()
    assert not (download.dest / "eng.traineddata").exists()
    assert download.warnings == []


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_tessdata_download_failure_warns_and_changes_nothing(qtbot, download, entry):
    parent, call = entry(qtbot)
    download.error = TessdataDownloadError("network down")

    _drive(qtbot, call, download, download.release.set)

    assert download.warnings == ["network down"]
    assert not tessdata_path()


def test_closing_preferences_during_download_cancels_without_hanging(qtbot, download):
    dialog, call = _prefs(qtbot)

    def close() -> None:
        assert dialog.close() is False  # close is refused while running
        assert dialog.isVisible()

    _drive(qtbot, call, download, close)

    assert download.token.is_cancelled()
    assert not tessdata_path()
    assert dialog.close() is True


def test_second_close_abandons_a_download_that_ignores_cancel(qtbot, download):
    download.ignore_cancel = True
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    closes: list[bool] = []

    def close_twice() -> None:
        closes.append(host.close())
        closes.append(host.close())

    result = _drive(
        qtbot, lambda: dialogs.run_tessdata_download(host), download, close_twice
    )

    assert closes == [False, True]
    assert result is None
    assert download.token.is_cancelled()
    assert not host.isVisible()


def test_rejecting_preferences_during_download_cancels_without_hanging(qtbot, download):
    dialog, call = _prefs(qtbot)

    _drive(qtbot, call, download, dialog.reject)

    assert download.token.is_cancelled()
    assert not tessdata_path()
    qtbot.waitUntil(lambda: not dialogs._TESSDATA_RUNS)


class _SpontaneousHide(QHideEvent):
    def spontaneous(self) -> bool:
        return True


def test_minimising_preferences_during_download_keeps_it_running(qtbot, download):
    dialog, call = _prefs(qtbot)

    def minimise_then_finish() -> None:
        QApplication.sendEvent(dialog, _SpontaneousHide())
        assert not download.token.is_cancelled()
        download.release.set()

    _drive(qtbot, call, download, minimise_then_finish)

    assert not download.token.is_cancelled()
    assert not tessdata_path()
    assert dialog._tessdata.text() == str(download.dest)
    assert download.warnings == []


def _finish_download(qtbot, download):
    dialog, call = _prefs(qtbot)
    _drive(qtbot, call, download, download.release.set)
    assert dialog._tessdata.text() == str(download.dest)
    return dialog


def test_download_then_cancel_saves_nothing_and_restores_registry(
    qtbot, download, capability_registry
):
    dialog = _finish_download(qtbot, download)
    assert capability_registry.configured_tessdata_path() == str(download.dest)

    dialog.reject()

    assert not tessdata_path()
    assert capability_registry.configured_tessdata_path() is None
    assert (download.dest / "eng.traineddata").exists()


def test_download_then_ok_saves_the_folder(qtbot, download, capability_registry):
    dialog = _finish_download(qtbot, download)
    assert not tessdata_path()

    dialog._on_accept()

    assert tessdata_path() == str(download.dest)
    assert capability_registry.configured_tessdata_path() == str(download.dest)
