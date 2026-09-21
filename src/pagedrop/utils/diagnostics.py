"""Focused terminal diagnostics for PageDrop failures."""

from __future__ import annotations

import faulthandler
import logging
import platform
import sys
import threading
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version

_LOG = logging.getLogger("pagedrop")
_HANDLER_MARKER = "pagedrop-terminal"


def configure_terminal_logging() -> logging.Logger:
    """Log actionable failures to stderr without changing the host application's root logger."""
    if not any(
        getattr(handler, "name", "") == _HANDLER_MARKER
        for handler in _LOG.handlers
    ):
        handler = logging.StreamHandler()
        handler.name = _HANDLER_MARKER
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s [%(threadName)s] %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False

    try:
        faulthandler.enable(file=sys.stderr, all_threads=True)
    except (OSError, RuntimeError):
        _LOG.warning("Could not enable native crash tracebacks", exc_info=True)

    _install_exception_hooks()
    return _LOG


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


def _install_exception_hooks() -> None:
    def report_unhandled(
        exc_type: type[BaseException], exc: BaseException, traceback: object,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        _LOG.critical(
            "Unhandled exception terminated the application (%s: %s)",
            exc_type.__name__,
            exc,
            exc_info=(exc_type, exc, traceback),
        )

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
