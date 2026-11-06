"""Microsoft Office → PDF helper (dedicated process, Windows + pywin32 only).

IPC: one JSON object on stdin, one JSON object on stdout.

Request::

    {"input": "/abs/in.docx", "output": "/abs/out.pdf", "pid_file": "/abs/office.pid"}

``pid_file`` is optional. When given, the worker writes the PID of the Office
app it launched there (atomically, best effort) so the parent can end that app
if it has to give up on the conversion.

Response::

    {"ok": true, "output": "/abs/out.pdf"}
    {"ok": false, "error": "…", "code": "…"}

Uses ``DispatchEx`` so we never attach to the user's live Office session.
``Quit`` only runs when *this* process started the app via ``DispatchEx``.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

# Fixed-format PDF export constants (MS Office).
WD_FORMAT_PDF = 17
XL_TYPE_PDF = 0
PP_FIXED_FORMAT_PDF = 2
# msoAutomationSecurityForceDisable — block macros without prompting.
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3
# Office ignores this for unprotected files; for protected ones it raises
# instead of showing a password dialog nobody can answer.
_NO_PROMPT_PASSWORD = "pagedrop-no-password-prompt"
# Low word of Word's "wrong password" COM error (locale-independent).
_WORD_PASSWORD_SCODE = 5408
# Office wrong-password phrases; the bare word also appears in file paths.
_PASSWORD_PHRASES = ("password is incorrect", "password you supplied")

WORD_EXTENSIONS = frozenset(
    {".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm", ".rtf", ".odt"}
)
EXCEL_EXTENSIONS = frozenset(
    {".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".xltm", ".csv"}
)
POWERPOINT_EXTENSIONS = frozenset(
    {".ppt", ".pptx", ".pptm", ".pot", ".potx", ".potm", ".pps", ".ppsx", ".ppsm"}
)


class OfficeComError(Exception):
    """Worker-side conversion failure (serialized to JSON ``error`` / ``code``)."""

    def __init__(self, message: str, code: str = "office_com_error") -> None:
        super().__init__(message)
        self.code = code


def office_app_for_path(path: Path) -> str:
    """Return ``word``, ``excel``, or ``powerpoint`` for *path*."""
    ext = path.suffix.lower()
    if ext in WORD_EXTENSIONS:
        return "word"
    if ext in EXCEL_EXTENSIONS:
        return "excel"
    if ext in POWERPOINT_EXTENSIONS:
        return "powerpoint"
    raise OfficeComError(
        f"Unsupported Office extension for COM conversion: {ext or '(none)'}",
        code="unsupported_format",
    )


def _require_windows() -> None:
    if sys.platform != "win32":
        raise OfficeComError(
            "Microsoft Office COM is only available on Windows",
            code="not_windows",
        )


def _import_com() -> tuple[Any, Any]:
    """Return ``(pythoncom, win32com.client)`` or raise ``OfficeComError``."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise OfficeComError(
            f"pywin32 not available ({type(exc).__name__})",
            code="pywin32_missing",
        ) from exc
    return pythoncom, win32com.client


# Where to report the owned Office app's PID; set per request by ``convert_file``.
_pid_file: str | None = None


def _office_pid(app: Any, progid: str) -> int:
    """PID of the Office app behind *app* (Windows; pywin32 imported lazily)."""
    import win32process

    if progid == "Excel.Application":
        hwnd = app.Hwnd
    elif progid == "PowerPoint.Application":
        hwnd = app.HWND
    else:
        # Word has no reliable Application hwnd; find its window by a unique caption.
        import win32gui

        caption = f"pagedrop-{uuid.uuid4().hex}"
        previous = app.Caption
        app.Caption = caption
        try:
            hwnd = win32gui.FindWindow("OpusApp", caption)
        finally:
            app.Caption = previous
    if not hwnd:
        raise OfficeComError("no window handle", code="pid_lookup")
    return int(win32process.GetWindowThreadProcessId(hwnd)[1])


def _report_owned_pid(app: Any, progid: str) -> None:
    """Best effort: record the owned app's PID in ``_pid_file``; never raises."""
    if not _pid_file:
        return
    try:
        pid = _office_pid(app, progid)
        if pid <= 0:
            raise OfficeComError("invalid process id", code="pid_lookup")
        tmp = f"{_pid_file}.tmp"
        Path(tmp).write_text(str(pid), encoding="utf-8")
        os.replace(tmp, _pid_file)
    except Exception as exc:  # noqa: BLE001 — conversion must still run
        print(f"could not report the {progid} process id: {exc}", file=sys.stderr)


def _dispatch_owned(client: Any, progid: str) -> tuple[Any, bool]:
    """``DispatchEx`` a ProgID; return ``(app, owned)``.

    ``owned`` is True only after a successful ``DispatchEx`` — callers must not
    ``Quit`` an app they did not start (never use plain ``Dispatch`` here).
    """
    app = client.DispatchEx(progid)
    _report_owned_pid(app, progid)
    return app, True


def _convert_word(client: Any, input_path: str, output_path: str) -> None:
    app = None
    owned = False
    doc = None
    try:
        app, owned = _dispatch_owned(client, "Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        try:
            app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
        except Exception:  # noqa: BLE001 — older Word builds
            pass
        doc = app.Documents.Open(
            FileName=input_path,
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            PasswordDocument=_NO_PROMPT_PASSWORD,
        )
        # Prefer ExportAsFixedFormat; fall back to SaveAs with wdFormatPDF.
        try:
            doc.ExportAsFixedFormat(output_path, WD_FORMAT_PDF)
        except Exception:  # noqa: BLE001
            doc.SaveAs(output_path, FileFormat=WD_FORMAT_PDF)
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:  # noqa: BLE001
                pass
        if owned and app is not None:
            try:
                app.Quit()
            except Exception:  # noqa: BLE001
                pass


def _convert_excel(client: Any, input_path: str, output_path: str) -> None:
    app = None
    owned = False
    workbook = None
    try:
        app, owned = _dispatch_owned(client, "Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        try:
            app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
        except Exception:  # noqa: BLE001
            pass
        workbook = app.Workbooks.Open(
            Filename=input_path,
            UpdateLinks=0,
            ReadOnly=True,
            Password=_NO_PROMPT_PASSWORD,
        )
        workbook.ExportAsFixedFormat(Type=XL_TYPE_PDF, Filename=output_path)
    finally:
        if workbook is not None:
            try:
                workbook.Close(False)
            except Exception:  # noqa: BLE001
                pass
        if owned and app is not None:
            try:
                app.Quit()
            except Exception:  # noqa: BLE001
                pass


def _convert_powerpoint(client: Any, input_path: str, output_path: str) -> None:
    app = None
    owned = False
    presentation = None
    try:
        app, owned = _dispatch_owned(client, "PowerPoint.Application")
        # PowerPoint has no reliable Visible=False on all builds; WithWindow=False
        # on Open keeps the UI off the user's desktop.
        try:
            app.DisplayAlerts = 1  # ppAlertsNone
        except Exception:  # noqa: BLE001
            pass
        try:
            app.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
        except Exception:  # noqa: BLE001
            pass
        presentation = app.Presentations.Open(
            input_path,
            ReadOnly=True,
            Untitled=False,
            WithWindow=False,
        )
        presentation.ExportAsFixedFormat(
            output_path,
            PP_FIXED_FORMAT_PDF,
        )
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:  # noqa: BLE001
                pass
        if owned and app is not None:
            try:
                app.Quit()
            except Exception:  # noqa: BLE001
                pass


_CONVERTERS: dict[str, Callable[[Any, str, str], None]] = {
    "word": _convert_word,
    "excel": _convert_excel,
    "powerpoint": _convert_powerpoint,
}


def _is_password_failure(exc: BaseException) -> bool:
    """True when Office refused a protected document (text or COM scode)."""
    text = str(exc).lower()
    if any(phrase in text for phrase in _PASSWORD_PHRASES):
        return True
    info = getattr(exc, "excepinfo", None)
    try:
        scode = info[5]
    except (TypeError, IndexError, KeyError):
        return False
    return isinstance(scode, int) and (scode & 0xFFFF) == _WORD_PASSWORD_SCODE


def convert_file(
    input_path: str | Path,
    output_path: str | Path,
    pid_file: str | Path | None = None,
) -> Path:
    """Convert one Office file to PDF via COM. Raises ``OfficeComError``."""
    global _pid_file
    _require_windows()
    src = Path(input_path).resolve()
    dst = Path(output_path).resolve()
    if not src.is_file():
        raise OfficeComError(f"Input not found: {src}", code="input_missing")
    if src == dst:
        raise OfficeComError(
            "Output path must not overwrite the source Office file",
            code="source_overwrite",
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()

    app_kind = office_app_for_path(src)
    pythoncom, client = _import_com()
    pythoncom.CoInitialize()
    _pid_file = str(pid_file) if pid_file else None
    try:
        _CONVERTERS[app_kind](client, str(src), str(dst))
    except OfficeComError:
        raise
    except Exception as exc:  # noqa: BLE001 — COM failures are opaque
        if _is_password_failure(exc):
            raise OfficeComError(
                "This document is password-protected. "
                "Remove the password in Office, then try again.",
                code="password_protected",
            ) from exc
        raise OfficeComError(
            f"{app_kind} COM conversion failed: {exc}",
            code="com_failed",
        ) from exc
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass

    if not dst.is_file() or dst.stat().st_size <= 0:
        raise OfficeComError(
            "COM conversion produced no PDF output",
            code="empty_output",
        )
    return dst


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Run one IPC request dict; return a response dict (never raises)."""
    try:
        input_path = request.get("input")
        output_path = request.get("output")
        if not input_path or not output_path:
            return {
                "ok": False,
                "error": "Request requires string 'input' and 'output' paths",
                "code": "bad_request",
            }
        pid_file = request.get("pid_file")
        out = convert_file(
            str(input_path), str(output_path), str(pid_file) if pid_file else None
        )
        return {"ok": True, "output": str(out)}
    except OfficeComError as exc:
        return {"ok": False, "error": str(exc), "code": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Unexpected worker error: {exc}",
            "code": "worker_crash",
        }


def main(argv: list[str] | None = None) -> int:
    """Read JSON from stdin (or ``argv[1]`` file); write JSON to stdout."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args:
            raw = Path(args[0]).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()
        request = json.loads(raw) if raw.strip() else {}
        if not isinstance(request, dict):
            response = {
                "ok": False,
                "error": "Request JSON must be an object",
                "code": "bad_request",
            }
        else:
            response = handle_request(request)
    except json.JSONDecodeError as exc:
        response = {
            "ok": False,
            "error": f"Invalid JSON: {exc}",
            "code": "bad_request",
        }
    except Exception as exc:  # noqa: BLE001
        response = {
            "ok": False,
            "error": f"Failed to read request: {exc}",
            "code": "bad_request",
        }
    # A windowed build started without handles has no stdout; nobody is listening.
    if sys.stdout is not None:
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
