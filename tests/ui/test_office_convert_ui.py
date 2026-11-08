"""Phase 26 UI — Office to PDF modeless shell."""

from __future__ import annotations

from pathlib import Path

import threading

import fitz
import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QPushButton

from pagedrop.core.backends.office import (
    OfficeCapabilityReport,
    OfficeComFailedNeedsRetry,
    OfficeConvertResult,
)
from pagedrop.core.capabilities import (
    LIBREOFFICE,
    OFFICE_COM,
    AbsenceReason,
    CapabilityStatus,
    clear_cache,
)
from pagedrop.core.jobs import JobError, JobSpec
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.ui.dialogs import build_missing_libreoffice_dialog
from pagedrop.ui.office_convert_window import (
    SHELL_OFFICE_ID,
    _run_office_conversion,
    open_office_convert_shell,
)
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow
from tests.conftest import file_sha256


def _report(*, com: bool = False, lo: bool = False) -> OfficeCapabilityReport:
    return OfficeCapabilityReport(
        com=(
            CapabilityStatus(
                id=OFFICE_COM,
                available=True,
                detail="ok",
                extras={"apps": ["word"]},
            )
            if com
            else CapabilityStatus(
                id=OFFICE_COM,
                available=False,
                reason=AbsenceReason.ENGINE_MISSING,
                detail="no",
            )
        ),
        libreoffice=(
            CapabilityStatus(
                id=LIBREOFFICE,
                available=True,
                detail="ok",
                extras={"path": "/usr/bin/soffice"},
            )
            if lo
            else CapabilityStatus(
                id=LIBREOFFICE,
                available=False,
                reason=AbsenceReason.ENGINE_MISSING,
                detail="no",
            )
        ),
        preferred="auto",
        soffice_path=None,
    )


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        return doc.tobytes()
    finally:
        doc.close()


def test_office_tile_opens_modeless_shell(qtbot, isolated_settings):
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    tools.showMinimized()
    shell = open_office_convert_shell(tools)
    assert shell is not None
    assert isinstance(shell, ToolShellWindow)
    assert shell.isVisible()
    qtbot.addWidget(shell)
    shell.close()


def test_office_tile_not_coming_soon(qtbot, isolated_settings):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    by_id = {t.entry.id: t.entry for t in window._tiles}
    assert SHELL_OFFICE_ID in by_id
    assert by_id[SHELL_OFFICE_ID].action == "office_to_pdf"
    assert not by_id[SHELL_OFFICE_ID].coming_soon
    window.close()


def test_preflight_shows_backend_status(qtbot, monkeypatch, isolated_settings):
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.capability_report",
        lambda **_k: _report(com=True, lo=True),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)
    label = getattr(shell, "_backend_status_label", None)
    assert isinstance(label, QLabel)
    text = label.text()
    assert "Microsoft Office" in text
    assert "LibreOffice" in text


def test_run_disabled_without_backend(qtbot, tmp_path, monkeypatch, isolated_settings):
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.capability_report",
        lambda **_k: _report(com=False, lo=False),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)

    doc = tmp_path / "note.docx"
    doc.write_bytes(b"docx")
    shell.drop_zone.set_paths([str(doc)])
    assert not shell._run_btn.isEnabled()

    # Configure CTA present
    configure = shell.findChildren(QPushButton)
    assert any(b.text() == "Configure…" for b in configure)


@pytest.mark.parametrize("opened", [True, False])
def test_download_button_warns_only_when_the_browser_cannot_open(
    qtbot, monkeypatch, opened
):
    from pagedrop.core.backends.libreoffice import DOWNLOAD_URL
    from pagedrop.ui import dialogs

    class Stub:
        def __init__(self) -> None:
            self.button = QPushButton()
            self.button.setObjectName("lo_download")

        def exec(self) -> int:
            return 0

        def clickedButton(self) -> QPushButton:  # noqa: N802
            return self.button

    warned: list[tuple[str, str]] = []
    monkeypatch.delenv("PAGEDROP_TESTING")
    monkeypatch.setattr(dialogs, "build_missing_libreoffice_dialog", lambda *_a, **_k: Stub())
    monkeypatch.setattr(dialogs.QDesktopServices, "openUrl", lambda _url: opened)
    monkeypatch.setattr(
        dialogs.QMessageBox, "warning", lambda _parent, title, text: warned.append((title, text))
    )

    assert dialogs.prompt_missing_libreoffice(None) == "download"
    if opened:
        assert warned == []
    else:
        assert warned == [
            (
                "LibreOffice",
                f"PageDrop could not open your browser. Open {DOWNLOAD_URL} in your browser.",
            )
        ]


def test_missing_lo_dialog_has_download_and_recheck(qtbot):
    host = ToolsWindow()
    qtbot.addWidget(host)
    dialog = build_missing_libreoffice_dialog(host, subject="Office to PDF")
    names = {b.objectName() for b in dialog.buttons() if b.objectName()}
    assert "lo_recheck" in names
    assert "lo_download" in names
    dialog.close()


def test_status_names_backend_used(qtbot, tmp_path, monkeypatch, isolated_settings):
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.capability_report",
        lambda **_k: _report(lo=True),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)

    src = tmp_path / "note.docx"
    src.write_bytes(b"docx")
    out = tmp_path / "note.pdf"
    ended: list[dict] = []

    class FakeRunner:
        def run(self, spec, **_kwargs):
            Path(spec.output).write_bytes(_pdf_bytes())
            return Path(spec.output)

    monkeypatch.setattr(shell, "job_runner", lambda: FakeRunner())
    real_end = shell.end_job

    def capture_end(**kwargs):
        ended.append(dict(kwargs))
        return real_end(**kwargs)

    monkeypatch.setattr(shell, "end_job", capture_end)

    # Avoid clobbering the success status with idle refresh in this assertion.
    _run_office_conversion(
        shell,
        source=str(src),
        output=str(out),
        backend="libreoffice",
        backend_label="LibreOffice",
        refresh_status=lambda: None,
    )
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)

    assert ended, "expected end_job after conversion"
    status = ended[-1].get("status") or ""
    toast = ended[-1].get("toast") or ""
    assert "LibreOffice" in status
    assert "LibreOffice" in toast
    assert out.is_file()
    clear_cache()


def test_office_job_overwrites_only_when_destination_exists(
    qtbot, tmp_path, monkeypatch, isolated_settings
):
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.capability_report",
        lambda **_k: _report(lo=True),
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)
    monkeypatch.setattr(
        "pagedrop.ui.office_convert_window.confirm_overwrite",
        lambda *_a, **_k: True,
    )

    src = tmp_path / "note.docx"
    src.write_bytes(b"docx")
    out = tmp_path / "note.pdf"
    overwrite_flags: list[bool] = []

    class FakeRunner:
        def run(self, spec, **_kwargs):
            overwrite_flags.append(spec.overwrite)
            Path(spec.output).write_bytes(_pdf_bytes())
            return Path(spec.output)

    monkeypatch.setattr(shell, "job_runner", lambda: FakeRunner())

    def convert() -> None:
        _run_office_conversion(
            shell,
            source=str(src),
            output=str(out),
            backend="libreoffice",
            backend_label="LibreOffice",
            refresh_status=lambda: None,
        )

    convert()
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)
    convert()  # the first run created the destination, so this one replaces it
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)

    assert overwrite_flags == [False, True]
    clear_cache()


# --- conversion runs off the GUI thread ---------------------------------------

_JOBS_BACKEND = "pagedrop.core.office_conversion_jobs.convert_office_to_pdf"
_WINDOW = "pagedrop.ui.office_convert_window"


@pytest.fixture
def office_job(qtbot, tmp_path, monkeypatch, isolated_settings):
    """Shell + source/output paths; the real runner and handler, a mocked backend."""
    monkeypatch.setattr(
        f"{_WINDOW}.capability_report", lambda **_k: _report(com=True, lo=True)
    )
    tools = ToolsWindow()
    qtbot.addWidget(tools)
    shell = open_office_convert_shell(tools)
    assert shell is not None
    qtbot.addWidget(shell)
    src = tmp_path / "note.docx"
    src.write_bytes(b"docx")

    class Job:
        pass

    job = Job()
    job.shell = shell
    job.src = src
    job.out = tmp_path / "note.pdf"
    job.source_hash = file_sha256(src)
    job.calls = []

    def convert() -> None:
        _run_office_conversion(
            shell,
            source=str(src),
            output=str(job.out),
            backend="com",
            backend_label="Microsoft Office",
            refresh_status=lambda: None,
        )

    job.convert = convert
    yield job
    clear_cache()


def _ok_backend(job, behaviour=None):
    """Fake ``convert_office_to_pdf``: records (backend, thread) and writes a PDF."""

    def fake(source, staged, *, backend, cancel=None, **_kw):
        job.calls.append((backend, threading.get_ident()))
        if behaviour is not None:
            behaviour(backend, cancel)
        staged.write_bytes(_pdf_bytes())
        return OfficeConvertResult(path=staged, backend=backend, page_count=1)

    return fake


def _wait_idle(qtbot, shell):
    qtbot.waitUntil(lambda: not shell.is_job_running(), timeout=10000)


def test_office_conversion_runs_off_gui_thread(qtbot, office_job, monkeypatch):
    shell = office_job.shell
    release = threading.Event()
    started = threading.Event()

    def block(_backend, _cancel):
        started.set()
        release.wait(10)

    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, block))
    ticks: list[int] = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)

    try:
        office_job.convert()  # returns while the backend is still blocked
        assert shell.is_job_running()
        qtbot.waitUntil(started.is_set, timeout=5000)
        seen = len(ticks)
        qtbot.waitUntil(lambda: len(ticks) >= seen + 3, timeout=5000)
        assert shell.is_job_running()
    finally:
        release.set()
        timer.stop()
    _wait_idle(qtbot, shell)

    assert office_job.calls[0][1] != threading.get_ident()
    assert office_job.out.is_file()
    assert file_sha256(office_job.src) == office_job.source_hash


def test_office_cancel_via_overlay_reaches_backend(qtbot, office_job, monkeypatch):
    shell = office_job.shell
    in_backend = threading.Event()

    def wait_for_cancel(_backend, cancel):
        in_backend.set()
        pause = threading.Event()
        for _ in range(1000):
            if cancel.is_cancelled():
                break
            pause.wait(0.01)
        cancel.check()

    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, wait_for_cancel))
    office_job.convert()
    qtbot.waitUntil(
        lambda: in_backend.is_set() and shell._busy_overlay._cancel_btn.isVisible(),
        timeout=5000,
    )
    shell._busy_overlay._cancel_btn.click()
    _wait_idle(qtbot, shell)

    assert shell.statusBar().currentMessage() == "Cancelled"
    assert not office_job.out.exists()
    assert file_sha256(office_job.src) == office_job.source_hash


def _com_fails(backend, _cancel):
    if backend == "com":
        raise OfficeComFailedNeedsRetry("COM crashed")


def test_com_failure_retry_confirmed_runs_libreoffice_once(
    qtbot, office_job, monkeypatch
):
    shell = office_job.shell
    asked: list[str] = []
    confirmed: list[list] = []
    overwrite_flags: list[bool] = []
    office_job.out.write_bytes(b"old")  # destination exists -> overwrite confirm

    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, _com_fails))
    monkeypatch.setattr(
        f"{_WINDOW}._ask_retry_with_libreoffice",
        lambda _parent, message: asked.append(message) or True,
    )
    monkeypatch.setattr(
        f"{_WINDOW}.confirm_overwrite",
        lambda _parent, paths, **_k: confirmed.append(list(paths)) or True,
    )
    real_create = JobSpec.create

    def spy_create(*a, **k):
        spec = real_create(*a, **k)
        overwrite_flags.append(spec.overwrite)
        return spec

    monkeypatch.setattr(f"{_WINDOW}.JobSpec.create", spy_create)

    office_job.convert()
    _wait_idle(qtbot, shell)

    assert [c[0] for c in office_job.calls] == ["com", "libreoffice"]
    assert all(c[1] != threading.get_ident() for c in office_job.calls)
    assert len(asked) == 1
    assert len(confirmed) == 1
    assert overwrite_flags == [True, True]
    assert office_job.out.read_bytes() != b"old"
    assert office_job.out != office_job.src
    assert file_sha256(office_job.src) == office_job.source_hash
    assert "LibreOffice" in shell.statusBar().currentMessage()


def test_com_failure_retry_declined_surfaces_error(qtbot, office_job, monkeypatch):
    shell = office_job.shell
    asked: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, _com_fails))
    monkeypatch.setattr(
        f"{_WINDOW}._ask_retry_with_libreoffice",
        lambda _parent, message: asked.append(message) or False,
    )
    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.QMessageBox.critical",
        lambda _p, _t, text: errors.append(text),
    )

    office_job.convert()
    _wait_idle(qtbot, shell)

    assert [c[0] for c in office_job.calls] == ["com"]
    assert len(asked) == 1
    assert errors and "COM crashed" in errors[0]
    assert not office_job.out.exists()
    assert file_sha256(office_job.src) == office_job.source_hash


def test_cancel_during_retry_dialog_skips_second_attempt(
    qtbot, office_job, monkeypatch
):
    shell = office_job.shell

    def cancel_while_open(_parent, _message):
        shell.cancel_active_job()  # user cancels while the dialog is up
        return True

    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, _com_fails))
    monkeypatch.setattr(f"{_WINDOW}._ask_retry_with_libreoffice", cancel_while_open)
    runner = shell.job_runner()
    real_run = runner.run
    runs: list[str] = []
    monkeypatch.setattr(
        runner, "run", lambda spec, **k: runs.append(spec.options["backend"]) or real_run(spec, **k)
    )

    office_job.convert()
    _wait_idle(qtbot, shell)

    assert runs == ["com"]  # no second worker was even started
    assert [c[0] for c in office_job.calls] == ["com"]
    assert shell.statusBar().currentMessage() == "Cancelled"
    assert not office_job.out.exists()
    assert not shell.worker_pending()


def test_backend_unavailable_shows_missing_capability_prompt(
    qtbot, office_job, monkeypatch
):
    shell = office_job.shell
    prompts: list[object] = []

    def unavailable(_backend, _cancel):
        raise BackendUnavailableError(OFFICE_COM, "engine_missing")

    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, unavailable))
    monkeypatch.setattr(
        f"{_WINDOW}.prompt_missing_capability",
        lambda _parent, status, **_k: prompts.append(status) or "cancel",
    )

    office_job.convert()
    _wait_idle(qtbot, shell)

    assert len(prompts) == 1
    assert prompts[0].id == OFFICE_COM
    assert not office_job.out.exists()


def test_generic_job_error_shows_failure(qtbot, office_job, monkeypatch):
    shell = office_job.shell
    errors: list[str] = []

    def boom(_backend, _cancel):
        raise JobError("converter exploded")

    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, boom))
    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.QMessageBox.critical",
        lambda _p, _t, text: errors.append(text),
    )

    office_job.convert()
    _wait_idle(qtbot, shell)

    assert errors == ["converter exploded"]
    assert shell.statusBar().currentMessage() == "Job failed"
    assert not office_job.out.exists()


def test_close_during_conversion_cancels_and_waits_for_worker(
    qtbot, office_job, monkeypatch
):
    shell = office_job.shell
    in_backend = threading.Event()
    release = threading.Event()

    def block(_backend, _cancel):
        in_backend.set()
        release.wait(10)

    monkeypatch.setattr(_JOBS_BACKEND, _ok_backend(office_job, block))
    monkeypatch.setattr(
        "pagedrop.ui.job_chrome.prompt_cancel_running_job", lambda *_a, **_k: True
    )
    office_job.convert()
    qtbot.waitUntil(in_backend.is_set, timeout=5000)

    assert shell.request_close()
    assert not shell.is_job_running()
    assert shell.worker_pending()  # the backend is still unwinding

    release.set()
    qtbot.waitUntil(lambda: not shell.worker_pending(), timeout=10000)
    assert not office_job.out.exists()
    assert file_sha256(office_job.src) == office_job.source_hash
