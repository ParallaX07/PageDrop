"""Focused terminal and file diagnostics for PageDrop failures.

No Qt import at module level: this runs before the application exists and must
keep working when the heavy app modules are what failed.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import platform
import re
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import IO

_LOG = logging.getLogger("pagedrop")
_HANDLER_MARKER = "pagedrop-terminal"
_FILE_HANDLER_MARKER = "pagedrop-file"
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(threadName)s] %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_ORG_AND_APP = ("PageDrop", "PageDrop")
# Every helper process flag (office COM, redact verify, compress) starts with this.
HELPER_FLAG_PREFIX = "--pagedrop-"
_MAX_LOG_BYTES = 1024 * 1024
_LOG_BACKUPS = 3
_ROLLOVER_RETRY_SECONDS = 60.0

_app_logging_enabled = False
_log_path: Path | None = None
_native_crash_file: IO[str] | None = None
_shown_crash_sites: set[object] = set()

_SECRET_KEYS = (
    "password", "passwd", "passphrase", "pwd", "secret", "token",
    "private_key", "pfx", "certificate",
)
_SECRET_RE = re.compile(
    r"(?P<key>[\"']?\w*(?:" + "|".join(_SECRET_KEYS) + r")\w*[\"']?)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|[^\s,;)}\]]+)",
    re.IGNORECASE,
)


def _mask_secret(match: re.Match[str]) -> str:
    value = match.group("value")
    quote = value[0] if value[0] in "\"'" else ""
    return f"{match.group('key')}{match.group('sep')}{quote}***{quote}"


def _withholds_detail(exc: BaseException | None) -> bool:
    """True when *exc* or anything in its cause/context chain must stay out of logs."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if getattr(exc, "log_detail_sensitive", False):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


class SafeFormatter(logging.Formatter):
    """Formatter that masks secret-looking values and withholds sensitive failures."""

    def format(self, record: logging.LogRecord) -> str:
        exc = record.exc_info[1] if record.exc_info else None
        if _withholds_detail(exc):
            # Format a copy: other handlers share the original record.
            record = logging.makeLogRecord(record.__dict__)
            record.msg = f"{type(exc).__name__} details withheld from the log"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return _SECRET_RE.sub(_mask_secret, super().format(record))


def _new_formatter() -> SafeFormatter:
    return SafeFormatter(_LOG_FORMAT, _LOG_DATE_FORMAT)


def configure_terminal_logging() -> logging.Logger:
    """Log actionable failures to stderr without changing the host application's root logger."""
    if not any(
        getattr(handler, "name", "") == _HANDLER_MARKER
        for handler in _LOG.handlers
    ):
        handler = logging.StreamHandler()
        handler.name = _HANDLER_MARKER
        handler.setFormatter(_new_formatter())
        _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False

    try:
        faulthandler.enable(file=sys.stderr, all_threads=True)
    except (OSError, RuntimeError):
        _LOG.warning("Could not enable native crash tracebacks", exc_info=True)

    _install_exception_hooks()
    return _LOG


class _AppendingRotatingFileHandler(RotatingFileHandler):
    """Rotating handler that keeps appending when a rollover cannot rename the file.

    A second running copy of PageDrop holding the file open makes the rename fail on
    Windows. The stock rollover shifts and deletes the older copies before that
    rename, so a failure would destroy history and retry on every record. Here the
    rename is proven first, and after a failure the handler just appends for a while.
    """

    _rollover_not_before = 0.0

    def doRollover(self) -> None:  # noqa: N802
        if time.monotonic() < self._rollover_not_before:
            return
        try:
            self._prove_active_file_can_be_renamed()
            super().doRollover()
        except OSError:
            self._rollover_not_before = time.monotonic() + _ROLLOVER_RETRY_SECONDS
            if self.stream is None:
                try:
                    self.stream = self._open()
                except OSError:
                    pass

    def _prove_active_file_can_be_renamed(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]
        probe = self.baseFilename + ".rollover"
        os.rename(self.baseFilename, probe)
        os.rename(probe, self.baseFilename)


def _app_local_data_dir() -> Path:
    """Qt's AppLocalDataLocation for org and app "PageDrop", resolved without Qt."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base).joinpath(*_ORG_AND_APP)
    if sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", "")
        if not os.path.isabs(base):
            base = str(Path.home() / ".local" / "share")
    return Path(base).joinpath(*_ORG_AND_APP)


def configure_app_logging(argv: Sequence[str]) -> Path | None:
    """Also log to ``<AppLocalData>/logs/pagedrop.log`` and enable the crash dialog.

    Helper processes (any ``--pagedrop-*`` flag) are left alone. Never raises.
    Returns the log path, or ``None`` when no file log is in use.
    """
    global _app_logging_enabled, _log_path, _native_crash_file
    if any(arg.startswith(HELPER_FLAG_PREFIX) for arg in argv[1:]):
        return None
    _app_logging_enabled = True
    for handler in _LOG.handlers:
        if getattr(handler, "name", "") == _FILE_HANDLER_MARKER:
            return _log_path
    try:
        logs_dir = _app_local_data_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = logs_dir / "pagedrop.log"
        handler = _AppendingRotatingFileHandler(
            path,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_LOG_BACKUPS,
            encoding="utf-8",
            errors="backslashreplace",
        )
    except (OSError, RuntimeError):
        _LOG.warning("Could not open the PageDrop log file", exc_info=True)
        return None
    handler.name = _FILE_HANDLER_MARKER
    handler.setFormatter(_new_formatter())
    _LOG.addHandler(handler)
    _log_path = path

    if sys.stderr is None:
        # Separate file: a descriptor held on pagedrop.log would block rotation.
        try:
            _native_crash_file = open(  # noqa: SIM115 - held for the process lifetime
                logs_dir / "native-crash.log", "a", encoding="utf-8", errors="backslashreplace"
            )
            faulthandler.enable(file=_native_crash_file, all_threads=True)
        except (OSError, RuntimeError):
            _LOG.warning("Could not enable native crash tracebacks", exc_info=True)
    return path


def log_startup(*, app_version: str) -> None:
    """Record enough runtime context to reproduce a reported terminal failure."""
    _LOG.info(
        "Starting PageDrop version=%s python=%s platform=%s frozen=%s",
        app_version,
        platform.python_version(),
        platform.platform(),
        getattr(sys, "frozen", False),
    )


def log_failure(operation: str, exc: BaseException, **context: object) -> None:
    """Log a handled failure with its causal traceback and safe operation context."""
    details = " ".join(f"{key}={value!s}" for key, value in context.items())
    suffix = f" {details}" if details else ""
    _LOG.error(
        "%s failed (%s: %s)%s",
        operation,
        type(exc).__name__,
        exc,
        suffix,
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def install_qt_message_handler() -> None:
    """Route Qt warnings and fatal messages through the same readable terminal log."""
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    levels: Mapping[QtMsgType, int] = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handle_qt_message(mode: QtMsgType, context: object, message: str) -> None:
        source = getattr(context, "file", None)
        line = getattr(context, "line", 0)
        category = getattr(context, "category", "default")
        location = f" {source}:{line}" if source else ""
        _LOG.log(
            levels.get(mode, logging.WARNING),
            "Qt[%s]%s: %s",
            category,
            location,
            message,
        )

    qInstallMessageHandler(handle_qt_message)


def _crash_site(exc_type: type[BaseException], traceback: object) -> object:
    """Exception type plus the code object and line of the last traceback frame."""
    last = traceback if isinstance(traceback, TracebackType) else None
    while last is not None and last.tb_next is not None:
        last = last.tb_next
    if last is None:
        return (exc_type, None, 0)
    return (exc_type, last.tb_frame.f_code, last.tb_lineno)


def _show_crash_dialog_once(exc_type: type[BaseException], traceback: object) -> None:
    """Tell the user about a main-thread crash, once per crash site. Never raises."""
    if (
        not _app_logging_enabled
        or threading.current_thread() is not threading.main_thread()
        or "PyQt6.QtWidgets" not in sys.modules
    ):
        return
    try:
        site = _crash_site(exc_type, traceback)
        if site in _shown_crash_sites:
            return
        _shown_crash_sites.add(site)
        from pagedrop.ui.crash_dialog import show_crash_dialog

        show_crash_dialog(_log_path)
    except Exception:
        _LOG.error("Could not show the crash dialog", exc_info=True)


def _install_exception_hooks() -> None:
    def report_unhandled(
        exc_type: type[BaseException], exc: BaseException, traceback: object,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        _LOG.critical(
            "Unhandled exception (%s: %s)",
            exc_type.__name__,
            exc,
            exc_info=(exc_type, exc, traceback),
        )
        _show_crash_dialog_once(exc_type, traceback)

    def report_thread_exception(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        _LOG.critical(
            "Unhandled exception in thread %s (%s: %s)",
            args.thread.name if args.thread else "unknown",
            args.exc_type.__name__,
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    def report_unraisable(args: sys.UnraisableHookArgs) -> None:
        _LOG.error(
            "Unraisable exception in %r (%s: %s)",
            args.object,
            args.exc_type.__name__ if args.exc_type else "unknown",
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = report_unhandled
    threading.excepthook = report_thread_exception
    sys.unraisablehook = report_unraisable


def installed_version() -> str:
    """Return the package version without making startup diagnostics fragile."""
    try:
        return version("pagedrop")
    except PackageNotFoundError:
        return "0.0.0"
