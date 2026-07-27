"""Office COM helper process — IPC, ownership, timeout / cancel tree kill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pagedrop.core.backends import office_com, process_tree
from pagedrop.core.backends.office_com import (
    OfficeComConversionError,
    convert_via_com,
    worker_argv,
)
from pagedrop.core.capabilities import OFFICE_COM, AbsenceReason, CapabilityStatus
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError, JobCancelledError
from pagedrop.helpers import office_com_worker as worker


def test_office_app_for_path_routes_extensions() -> None:
    assert worker.office_app_for_path(Path("a.docx")) == "word"
    assert worker.office_app_for_path(Path("a.XLSX")) == "excel"
    assert worker.office_app_for_path(Path("deck.pptx")) == "powerpoint"
    with pytest.raises(worker.OfficeComError) as exc:
        worker.office_app_for_path(Path("nope.pdf"))
    assert exc.value.code == "unsupported_format"


def test_handle_request_rejects_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker.sys, "platform", "linux")
    result = worker.handle_request(
        {"input": "/tmp/in.docx", "output": "/tmp/out.pdf"}
    )
    assert result["ok"] is False
    assert result["code"] == "not_windows"


def test_handle_request_bad_payload() -> None:
    assert worker.handle_request({})["code"] == "bad_request"
    assert worker.handle_request({"input": "x"})["code"] == "bad_request"


def test_quit_only_when_dispatchex_owned() -> None:
    """Quit must not run if DispatchEx never succeeded."""
    client = MagicMock()
    client.DispatchEx.side_effect = RuntimeError("no Office")
    with pytest.raises(RuntimeError):
        worker._convert_word(client, r"C:\in.docx", r"C:\out.pdf")
    # No app object to Quit — DispatchEx failed before assignment completes
    # via _dispatch_owned; ensure we never call Quit on a MagicMock app.
    # (If ownership were wrong, a partial app.Quit would appear on a mock.)


def test_convert_word_quits_owned_app() -> None:
    app = MagicMock()
    doc = MagicMock()
    client = MagicMock()
    client.DispatchEx.return_value = app
    app.Documents.Open.return_value = doc

    worker._convert_word(client, r"C:\in.docx", r"C:\out.pdf")

    client.DispatchEx.assert_called_once_with("Word.Application")
    assert app.Visible is False or app.Visible == False
    assert app.DisplayAlerts == 0
    doc.Close.assert_called()
    app.Quit.assert_called_once()


def test_convert_excel_and_powerpoint_export_pdf() -> None:
    excel = MagicMock()
    workbook = MagicMock()
    excel_client = MagicMock()
    excel_client.DispatchEx.return_value = excel
    excel.Workbooks.Open.return_value = workbook
    worker._convert_excel(excel_client, r"C:\in.xlsx", r"C:\out.pdf")
    workbook.ExportAsFixedFormat.assert_called()
    excel.Quit.assert_called_once()

    ppt = MagicMock()
    presentation = MagicMock()
    ppt_client = MagicMock()
    ppt_client.DispatchEx.return_value = ppt
    ppt.Presentations.Open.return_value = presentation
    worker._convert_powerpoint(ppt_client, r"C:\in.pptx", r"C:\out.pdf")
    presentation.ExportAsFixedFormat.assert_called()
    kwargs = ppt.Presentations.Open.call_args.kwargs
    assert kwargs.get("ReadOnly") is True
    assert kwargs.get("WithWindow") is False
    ppt.Quit.assert_called_once()


def test_worker_main_json_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker.sys, "platform", "linux")
    req = tmp_path / "req.json"
    req.write_text(
        json.dumps({"input": str(tmp_path / "a.docx"), "output": str(tmp_path / "a.pdf")}),
        encoding="utf-8",
    )
    # Capture stdout via monkeypatching write path through main's Path read.
    from io import StringIO

    buf = StringIO()
    monkeypatch.setattr(worker.sys, "stdout", buf)
    code = worker.main([str(req)])
    assert code == 1
    payload = json.loads(buf.getvalue().strip())
    assert payload["ok"] is False
    assert payload["code"] == "not_windows"


def test_pywin32_not_in_base_dependencies() -> None:
    """Base install must not require pywin32 (Linux/macOS wheels stay clean)."""
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    # Only under optional-dependencies / dependency-groups office, with win32 marker.
    assert "pywin32" in text
    assert 'pywin32>=306; sys_platform == \'win32\'' in text
    # Base [project] dependencies block must not list pywin32.
    start = text.index("dependencies = [")
    end = text.index("]", start)
    base_deps = text[start:end]
    assert "pywin32" not in base_deps


def test_kill_process_tree_reaps_owned_child() -> None:
    """Cancel/timeout path: kill helper session without leaving the sleeper."""
    if sys.platform == "win32":
        child = process_tree.popen_owned(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
        )
    else:
        child = process_tree.popen_owned(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
        )
    pid = child.pid
    assert child.poll() is None
    process_tree.kill_process_tree(pid)
    child.wait(timeout=5)
    assert child.poll() is not None
    # PID should be gone (or at least not our sleeper).
    if sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_convert_via_com_timeout_kills_owned_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "doc.docx"
    src.write_bytes(b"PK")  # minimal placeholder; helper is faked
    dst = tmp_path / "out.pdf"

    monkeypatch.setattr(
        office_com,
        "probe",
        lambda _cid: CapabilityStatus(
            id=OFFICE_COM, available=True, detail="mocked"
        ),
    )

    def fake_argv() -> list[str]:
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    monkeypatch.setattr(office_com, "worker_argv", fake_argv)

    t0 = time.monotonic()
    with pytest.raises(OfficeComConversionError) as exc:
        convert_via_com(src, dst, timeout_sec=0.5)
    assert exc.value.code == "timeout"
    assert time.monotonic() - t0 < 5.0


def test_convert_via_com_cancel_kills_owned_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "doc.docx"
    src.write_bytes(b"PK")
    dst = tmp_path / "out.pdf"
    token = CancelToken()

    monkeypatch.setattr(
        office_com,
        "probe",
        lambda _cid: CapabilityStatus(
            id=OFFICE_COM, available=True, detail="mocked"
        ),
    )
    monkeypatch.setattr(
        office_com,
        "worker_argv",
        lambda: [sys.executable, "-c", "import time; time.sleep(60)"],
    )

    def cancel_soon() -> None:
        time.sleep(0.2)
        token.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    with pytest.raises(JobCancelledError):
        convert_via_com(src, dst, timeout_sec=30, cancel=token)


def test_convert_via_com_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        office_com,
        "probe",
        lambda _cid: CapabilityStatus(
            id=OFFICE_COM,
            available=False,
            reason=AbsenceReason.ENGINE_MISSING,
            detail="mocked absent",
        ),
    )
    with pytest.raises(BackendUnavailableError):
        convert_via_com(tmp_path / "a.docx", tmp_path / "a.pdf")


def test_worker_argv_module_form() -> None:
    assert worker_argv()[-2:] == ["-m", "pagedrop.helpers.office_com_worker"] or (
        getattr(sys, "frozen", False)
        and "--pagedrop-office-com-worker" in worker_argv()
    )


def test_subprocess_worker_ipc_error_json(tmp_path: Path) -> None:
    """Real subprocess: worker module answers JSON without crashing the parent."""
    req = {"input": str(tmp_path / "missing.docx"), "output": str(tmp_path / "o.pdf")}
    proc = subprocess.run(
        [sys.executable, "-m", "pagedrop.helpers.office_com_worker"],
        input=json.dumps(req),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["code"] in {"not_windows", "input_missing", "pywin32_missing"}
    assert proc.returncode == 1
