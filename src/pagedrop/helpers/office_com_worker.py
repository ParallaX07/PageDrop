"""Microsoft Office → PDF helper (dedicated process, Windows + pywin32 only).

IPC: one JSON object on stdin, one JSON object on stdout.

Request::

    {"input": "/abs/in.docx", "output": "/abs/out.pdf"}

Response::

    {"ok": true, "output": "/abs/out.pdf"}
    {"ok": false, "error": "…", "code": "…"}

Uses ``DispatchEx`` so we never attach to the user's live Office session.
``Quit`` only runs when *this* process started the app via ``DispatchEx``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

# Fixed-format PDF export constants (MS Office).
WD_FORMAT_PDF = 17
XL_TYPE_PDF = 0
PP_FIXED_FORMAT_PDF = 2
# msoAutomationSecurityForceDisable — block macros without prompting.
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3

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


def _dispatch_owned(client: Any, progid: str) -> tuple[Any, bool]:
    """``DispatchEx`` a ProgID; return ``(app, owned)``.

    ``owned`` is True only after a successful ``DispatchEx`` — callers must not
    ``Quit`` an app they did not start (never use plain ``Dispatch`` here).
    """
    app = client.DispatchEx(progid)
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
        # ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False
        doc = app.Documents.Open(input_path, False, True, False)
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
        # UpdateLinks=0, ReadOnly=True
        workbook = app.Workbooks.Open(input_path, 0, True)
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


def convert_file(input_path: str | Path, output_path: str | Path) -> Path:
    """Convert one Office file to PDF via COM. Raises ``OfficeComError``."""
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
    try:
        _CONVERTERS[app_kind](client, str(src), str(dst))
    except OfficeComError:
        raise
    except Exception as exc:  # noqa: BLE001 — COM failures are opaque
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
        out = convert_file(str(input_path), str(output_path))
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
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
