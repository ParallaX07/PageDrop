from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from pagedrop.core.optimize_secure import COMPRESS_WORKER_FLAG
from pagedrop.core.redact import REDACT_VERIFY_FLAG, RedactionVerifyError
from pagedrop.main import _OFFICE_COM_WORKER_FLAG
from pagedrop.utils import diagnostics
from pagedrop.utils.diagnostics import (
    configure_app_logging,
    configure_terminal_logging,
    log_failure,
    log_startup,
)

HELPER_FLAGS = [_OFFICE_COM_WORKER_FLAG, REDACT_VERIFY_FLAG, COMPRESS_WORKER_FLAG]
MARKER = "PRIVATE-REDACTED-TEXT-7731"


class _Recorder:
    """Records faulthandler.enable calls and crash dialog requests."""

    def __init__(self) -> None:
        self.faulthandler: list[dict] = []
        self.dialogs: list[Path | None] = []


@pytest.fixture
def diag(monkeypatch, tmp_path):
    """Isolate profile paths and restore every global the diagnostics module touches."""
    data = tmp_path / "data"
    data.mkdir()
    for name in ("XDG_DATA_HOME", "LOCALAPPDATA", "HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(data))
    rec = _Recorder()
    monkeypatch.setattr(
        diagnostics.faulthandler, "enable", lambda **kw: rec.faulthandler.append(kw)
    )

    import pagedrop.ui.crash_dialog as crash_dialog

    monkeypatch.setattr(crash_dialog, "show_crash_dialog", rec.dialogs.append)

    saved_hooks = (sys.excepthook, threading.excepthook, sys.unraisablehook)
    log = diagnostics._LOG
    saved_handlers = list(log.handlers)
    saved_state = (log.propagate, log.level)
    saved_globals = (
        diagnostics._app_logging_enabled,
        diagnostics._log_path,
        diagnostics._native_crash_file,
        set(diagnostics._shown_crash_sites),
    )
    diagnostics._app_logging_enabled = False
    diagnostics._log_path = None
    diagnostics._native_crash_file = None
    diagnostics._shown_crash_sites.clear()
    rec.data = data  # type: ignore[attr-defined]
    try:
        yield rec
    finally:
        for handler in list(log.handlers):
            if handler not in saved_handlers:
                log.removeHandler(handler)
                handler.close()
        for handler in saved_handlers:
            if handler not in log.handlers:
                log.addHandler(handler)
        log.propagate, log.level = saved_state
        if diagnostics._native_crash_file is not None:
            diagnostics._native_crash_file.close()
        (
            diagnostics._app_logging_enabled,
            diagnostics._log_path,
            diagnostics._native_crash_file,
            shown,
        ) = saved_globals
        diagnostics._shown_crash_sites.clear()
        diagnostics._shown_crash_sites.update(shown)
        sys.excepthook, threading.excepthook, sys.unraisablehook = saved_hooks


def _read_log(path: Path) -> str:
    for handler in diagnostics._LOG.handlers:
        handler.flush()
    return path.read_text(encoding="utf-8")


def _unraisable(exc: BaseException) -> SimpleNamespace:
    # sys.UnraisableHookArgs cannot be constructed from Python.
    return SimpleNamespace(
        exc_type=type(exc), exc_value=exc, exc_traceback=exc.__traceback__,
        err_msg="err", object=None,
    )


def _raise_verify_error() -> RedactionVerifyError:
    try:
        raise RedactionVerifyError(
            f"Redaction verification failed. text still present: {MARKER}",
            failures=[f"text still present: {MARKER}"],
        )
    except RedactionVerifyError as exc:
        return exc


def test_log_failure_includes_context_and_traceback(diag, capsys):
    configure_terminal_logging()
    try:
        raise ValueError("disk full")
    except ValueError as exc:
        log_failure("Save PDF", exc, output="/tmp/output.pdf")

    stderr = capsys.readouterr().err
    assert "Save PDF failed (ValueError: disk full) output=/tmp/output.pdf" in stderr
    assert "ValueError: disk full" in stderr


def test_diagnostics_import_keeps_qt_out():
    code = (
        "import sys\n"
        "import pagedrop.utils.diagnostics\n"
        "assert 'PyQt6' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr


# --- A. file log -----------------------------------------------------------------


def test_every_helper_flag_matches_the_skip_prefix():
    assert HELPER_FLAGS == [
        "--pagedrop-office-com-worker",
        "--pagedrop-redact-verify",
        "--pagedrop-compress-worker",
    ]
    assert all(flag.startswith(diagnostics.HELPER_FLAG_PREFIX) for flag in HELPER_FLAGS)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="XDG_DATA_HOME is Linux only")
def test_log_folder_matches_qt_app_local_data(monkeypatch, tmp_path):
    from PyQt6.QtCore import QCoreApplication, QStandardPaths

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    org, app = QCoreApplication.organizationName(), QCoreApplication.applicationName()
    QCoreApplication.setOrganizationName("PageDrop")
    QCoreApplication.setApplicationName("PageDrop")
    try:
        qt_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
    finally:
        QCoreApplication.setOrganizationName(org)
        QCoreApplication.setApplicationName(app)
    assert diagnostics._app_local_data_dir() == Path(qt_dir)


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("win32", {"LOCALAPPDATA": "C:/L"}, Path("C:/L/PageDrop/PageDrop")),
        ("darwin", {}, Path.home() / "Library/Application Support/PageDrop/PageDrop"),
        ("linux", {"XDG_DATA_HOME": "/x"}, Path("/x/PageDrop/PageDrop")),
        ("linux", {}, Path.home() / ".local/share/PageDrop/PageDrop"),
    ],
)
def test_app_local_data_dir_per_platform(monkeypatch, platform, env, expected):
    monkeypatch.setattr(sys, "platform", platform)
    for name in ("LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert diagnostics._app_local_data_dir() == expected


def test_configure_app_logging_writes_startup_and_failures(diag):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    log_startup(app_version="9.9.9")
    try:
        raise ValueError("disk full")
    except ValueError as exc:
        log_failure("Save PDF", exc, output="out.pdf")

    assert path == diag.data / "PageDrop" / "PageDrop" / "logs" / "pagedrop.log"
    assert diagnostics._log_path == path
    text = _read_log(path)
    assert "Starting PageDrop version=9.9.9" in text
    assert "Save PDF failed (ValueError: disk full) output=out.pdf" in text
    assert "Traceback" in text


def test_configure_app_logging_adds_one_handler(diag):
    configure_terminal_logging()
    first = configure_app_logging(["pagedrop"])
    second = configure_app_logging(["pagedrop"])
    assert first == second
    file_handlers = [h for h in diagnostics._LOG.handlers if h.name == "pagedrop-file"]
    assert len(file_handlers) == 1
    handler = file_handlers[0]
    assert handler.maxBytes == 1024 * 1024
    assert handler.backupCount == 3
    assert handler.encoding == "utf-8"
    assert handler.errors == "backslashreplace"
    assert not handler.delay


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_log_folder_is_private(diag):
    path = configure_app_logging(["pagedrop"])
    assert path is not None
    assert path.parent.stat().st_mode & 0o077 == 0


def test_unencodable_text_is_escaped_not_dropped(diag):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    diagnostics._LOG.error("name \ud800 end")
    assert "end" in _read_log(path)


def test_rollover_failure_keeps_appending(diag, monkeypatch):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    handler = next(h for h in diagnostics._LOG.handlers if h.name == "pagedrop-file")
    handler.maxBytes = 200

    def locked(*_a, **_k):
        raise PermissionError("file is open in another instance")

    monkeypatch.setattr(type(handler), "rotate", locked)
    diagnostics._LOG.error("x" * 400)
    diagnostics._LOG.error("record after the failed rollover")
    assert "record after the failed rollover" in _read_log(path)


def test_unwritable_log_folder_does_not_stop_startup(diag, monkeypatch, capsys):
    blocker = diag.data / "blocker"
    blocker.write_text("not a folder")
    monkeypatch.setenv("XDG_DATA_HOME", str(blocker))
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    monkeypatch.setattr(sys, "platform", "linux")
    configure_terminal_logging()

    assert configure_app_logging(["pagedrop"]) is None
    assert diagnostics._log_path is None
    assert not [h for h in diagnostics._LOG.handlers if h.name == "pagedrop-file"]
    assert "Could not open the PageDrop log file" in capsys.readouterr().err
    # The crash dialog stays on and tells the user nothing was saved.
    assert diagnostics._app_logging_enabled


def test_home_lookup_failure_does_not_stop_startup(diag, monkeypatch):
    def broken() -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(diagnostics, "_app_local_data_dir", broken)
    configure_terminal_logging()
    assert configure_app_logging(["pagedrop"]) is None
    assert diagnostics._app_logging_enabled


def test_native_crash_log_is_a_separate_file_when_stderr_is_missing(diag, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    path = configure_app_logging(["pagedrop"])
    assert path is not None
    assert len(diag.faulthandler) == 1
    call = diag.faulthandler[0]
    assert Path(call["file"].name) == path.parent / "native-crash.log"
    assert call["all_threads"] is True


def test_native_crash_log_unused_when_stderr_exists(diag):
    configure_app_logging(["pagedrop"])
    assert diag.faulthandler == []


# --- B. secrets -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "opening password=hunter2 now",
        "opening PASSWORD: hunter2 now",
        'payload {"password": "hunter2 with spaces"} end',
        "payload {'passphrase': 'hunter2 with spaces'} end",
        "token=hunter2",
        "api_token: hunter2",
        "Secret=hunter2",
        "pfx=hunter2",
        "pwd=hunter2",
        "passwd=hunter2",
        "private_key=hunter2",
        "certificate=hunter2",
    ],
)
def test_secret_values_are_masked(text):
    record = logging.LogRecord("pagedrop", logging.INFO, __file__, 1, text, (), None)
    out = diagnostics.SafeFormatter("%(message)s").format(record)
    assert "hunter2" not in out
    assert "with spaces" not in out
    assert "***" in out


def test_mask_leaves_neighbouring_text(diag):
    record = logging.LogRecord(
        "pagedrop", logging.INFO, __file__, 1, "Open failed output=a.pdf password=x", (), None
    )
    out = diagnostics.SafeFormatter("%(message)s").format(record)
    assert out == "Open failed output=a.pdf password=***"


def test_log_failure_context_password_is_masked_in_both_logs(diag, capsys):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    log_failure("Open PDF", ValueError("bad"), password="hunter2")
    assert "password=***" in _read_log(path)
    assert "hunter2" not in _read_log(path)
    err = capsys.readouterr().err
    assert "password=***" in err
    assert "hunter2" not in err


def test_sensitive_failure_detail_never_reaches_either_log(diag, capsys):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    exc = _raise_verify_error()
    log_failure("Redact", exc, output="out.pdf")

    err = capsys.readouterr().err
    for text in (_read_log(path), err):
        assert MARKER not in text
        assert "RedactionVerifyError details withheld from the log" in text
    # The UI still shows the real message.
    assert MARKER in str(exc)


def test_sensitive_cause_chain_is_withheld(diag, capsys):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    try:
        try:
            raise _raise_verify_error()
        except RedactionVerifyError as inner:
            raise RuntimeError("job failed") from inner
    except RuntimeError as exc:
        log_failure("Redact", exc)

    assert MARKER not in _read_log(path)
    assert MARKER not in capsys.readouterr().err


def test_cyclic_exception_chain_terminates(diag):
    a, b = ValueError("a"), ValueError("b")
    a.__context__, b.__context__ = b, a
    assert diagnostics._withholds_detail(a) is False


def test_withholding_formats_a_copy_and_leaves_the_record_alone(diag):
    seen: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record)

    diagnostics._LOG.addHandler(Capture())
    diagnostics._LOG.setLevel(logging.INFO)
    configure_terminal_logging()
    log_failure("Redact", _raise_verify_error())

    record = seen[0]
    assert MARKER in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_text is None
    assert "details withheld" not in record.getMessage()


def test_exception_hooks_withhold_sensitive_detail(diag, capsys):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    exc = _raise_verify_error()

    sys.excepthook(type(exc), exc, exc.__traceback__)
    threading.excepthook(
        threading.ExceptHookArgs((type(exc), exc, exc.__traceback__, threading.current_thread()))
    )
    sys.unraisablehook(_unraisable(exc))

    assert MARKER not in _read_log(path)
    assert MARKER not in capsys.readouterr().err


def test_ordinary_failure_detail_is_still_logged(diag):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    log_failure("Save", ValueError("disk full at /tmp/x"))
    assert "disk full at /tmp/x" in _read_log(path)


# --- C. crash dialog hook ---------------------------------------------------------


def _crash_in_one_place() -> BaseException:
    try:
        raise ValueError("first problem")
    except ValueError as exc:
        return exc


def _crash_somewhere_else() -> BaseException:
    try:
        raise ValueError("second problem")
    except ValueError as exc:
        return exc


def _hook(exc: BaseException) -> None:
    sys.excepthook(type(exc), exc, exc.__traceback__)


def test_dialog_shows_once_per_crash_site(diag):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    for _ in range(3):
        _hook(_crash_in_one_place())
    assert diag.dialogs == [path]
    _hook(_crash_somewhere_else())
    assert diag.dialogs == [path, path]


def test_dialog_is_off_until_app_logging_is_configured(diag):
    configure_terminal_logging()
    _hook(_crash_in_one_place())
    assert diag.dialogs == []


def test_dialog_never_opens_from_a_worker_thread(diag):
    configure_terminal_logging()
    configure_app_logging(["pagedrop"])
    exc = _crash_in_one_place()
    worker = threading.Thread(target=_hook, args=(exc,))
    worker.start()
    worker.join()
    assert diag.dialogs == []


def test_thread_and_unraisable_hooks_are_log_only(diag):
    configure_terminal_logging()
    configure_app_logging(["pagedrop"])
    exc = _crash_in_one_place()
    threading.excepthook(
        threading.ExceptHookArgs((type(exc), exc, exc.__traceback__, threading.current_thread()))
    )
    sys.unraisablehook(_unraisable(exc))
    assert diag.dialogs == []


def test_dialog_failure_does_not_escape_the_hook(diag, monkeypatch):
    import pagedrop.ui.crash_dialog as crash_dialog

    def boom(_path):
        raise RuntimeError("no display")

    monkeypatch.setattr(crash_dialog, "show_crash_dialog", boom)
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    _hook(_crash_in_one_place())
    assert "Could not show the crash dialog" in _read_log(path)


def test_hook_cannot_be_what_imports_qt_widgets(diag, monkeypatch):
    configure_terminal_logging()
    configure_app_logging(["pagedrop"])
    monkeypatch.delitem(sys.modules, "PyQt6.QtWidgets")
    _hook(_crash_in_one_place())
    assert diag.dialogs == []
    assert "PyQt6.QtWidgets" not in sys.modules


def test_keyboard_interrupt_shows_nothing(diag):
    configure_terminal_logging()
    configure_app_logging(["pagedrop"])
    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert diag.dialogs == []


# --- D. console=False and helpers -------------------------------------------------


@pytest.fixture
def windowed_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)


def test_windowed_build_logs_to_the_file_and_reaches_the_dialog(diag, windowed_build):
    configure_terminal_logging()
    path = configure_app_logging(["pagedrop"])
    assert path is not None
    log_startup(app_version="1.2.3")
    log_failure("Open PDF", ValueError("bad file"))
    _hook(_crash_in_one_place())

    text = _read_log(path)
    assert "Starting PageDrop version=1.2.3" in text
    assert "frozen=True" in text
    assert "Open PDF failed (ValueError: bad file)" in text
    assert diag.dialogs == [path]
    assert len(diag.faulthandler) == 1  # native crash file, not the missing stderr


@pytest.mark.parametrize("flag", HELPER_FLAGS)
def test_helper_process_creates_no_log_and_shows_no_dialog(diag, windowed_build, flag):
    configure_terminal_logging()
    assert configure_app_logging(["pagedrop", flag, "--anything"]) is None
    log_startup(app_version="1.2.3")
    _hook(_crash_in_one_place())

    assert not (diag.data / "PageDrop").exists()
    assert not [h for h in diagnostics._LOG.handlers if h.name == "pagedrop-file"]
    assert diag.dialogs == []
    assert diagnostics._log_path is None


@pytest.mark.parametrize("flag", HELPER_FLAGS)
def test_helper_process_never_imports_qt_or_makes_a_folder(tmp_path, flag):
    code = (
        "import sys\n"
        "from pagedrop.utils import diagnostics\n"
        "diagnostics.configure_terminal_logging()\n"
        f"assert diagnostics.configure_app_logging(['pagedrop', {flag!r}]) is None\n"
        "try:\n"
        "    raise ValueError('boom')\n"
        "except ValueError as exc:\n"
        "    sys.excepthook(type(exc), exc, exc.__traceback__)\n"
        "assert 'PyQt6' not in sys.modules, 'Qt was imported'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=_isolated_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "data" / "PageDrop").exists()


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    import os

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    env = dict(os.environ)
    for name in ("XDG_DATA_HOME", "LOCALAPPDATA", "HOME", "USERPROFILE"):
        env[name] = str(data)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def test_verify_helper_keeps_stdout_a_single_json_object(tmp_path):
    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((40, 80), "hello world")
    doc.save(str(pdf))
    doc.close()
    payload = {"path": str(pdf), "absent_text": ["not-in-the-file"]}
    code = (
        "import sys\n"
        "from pagedrop.main import main\n"
        f"sys.argv = ['pagedrop', {REDACT_VERIFY_FLAG!r}, '--verify-json']\n"
        "sys.exit(main())\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=_isolated_env(tmp_path),
    )
    assert result.returncode in (0, 2), result.stderr
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    assert "failures" in parsed
    assert not (tmp_path / "data" / "PageDrop").exists()
