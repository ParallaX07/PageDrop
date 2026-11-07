import os
import sys
from collections.abc import MutableMapping, Sequence

_APP_NAME = "PageDrop"
_ORG_NAME = "PageDrop"

# Frozen: helpers re-enter this exe before Qt starts.
_OFFICE_COM_WORKER_FLAG = "--pagedrop-office-com-worker"


def restore_inherited_library_path(
    environ: MutableMapping[str, str],
    *,
    frozen: bool,
    platform: str,
) -> None:
    """Undo the bootloader's ``LD_LIBRARY_PATH`` so child programs don't load bundled libs.

    The dynamic loader reads the variable once at process start, so this
    process keeps its bundled libraries; only children (``soffice``,
    ``xdg-open`` and the apps it starts) stop inheriting it.
    """
    if not frozen or not platform.startswith("linux"):
        return
    original = environ.get("LD_LIBRARY_PATH_ORIG")
    if original is None:
        environ.pop("LD_LIBRARY_PATH", None)
    else:
        environ["LD_LIBRARY_PATH"] = original


def command_line_paths(args: Sequence[str]) -> list[str]:
    """File arguments to open: everything that is not an option or empty."""
    return [a for a in args if a and not a.startswith("-")]


def _app_version() -> str:
    from pagedrop.utils.diagnostics import installed_version

    return installed_version()


def main() -> int:
    restore_inherited_library_path(
        os.environ, frozen=getattr(sys, "frozen", False), platform=sys.platform
    )
    from pagedrop.utils.diagnostics import (
        configure_terminal_logging,
        install_qt_message_handler,
        log_startup,
    )

    configure_terminal_logging()
    log_startup(app_version=_app_version())
    if _OFFICE_COM_WORKER_FLAG in sys.argv:
        from pagedrop.helpers.office_com_worker import main as worker_main

        argv = [a for a in sys.argv[1:] if a != _OFFICE_COM_WORKER_FLAG]
        return worker_main(argv)

    from pagedrop.core.redact import REDACT_VERIFY_FLAG

    if REDACT_VERIFY_FLAG in sys.argv:
        from pagedrop.core.redact import main as redact_main

        argv = [a for a in sys.argv[1:] if a != REDACT_VERIFY_FLAG]
        return redact_main(argv)

    from pagedrop.core.optimize_secure import COMPRESS_WORKER_FLAG

    if COMPRESS_WORKER_FLAG in sys.argv:
        from pagedrop.core.optimize_secure import main as compress_main

        argv = [a for a in sys.argv[1:] if a != COMPRESS_WORKER_FLAG]
        return compress_main(argv)

    from PyQt6.QtCore import QEvent, QTimer
    from PyQt6.QtWidgets import QApplication

    from pagedrop.assets import app_icon
    from pagedrop.ui.accessibility import install_accessibility
    from pagedrop.ui.window_manager import WindowManager
    from pagedrop.utils.update_windows import UpdateMutex, WindowsUpdateError

    install_qt_message_handler()
    app = QApplication(sys.argv)
    app.setOrganizationName(_ORG_NAME)
    app.setApplicationName(_APP_NAME)
    app.setApplicationVersion(_app_version())
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    install_accessibility(app)
    from pagedrop.ui.settings import apply_optional_settings_to_capabilities

    apply_optional_settings_to_capabilities()
    icon = app_icon()
    app.setWindowIcon(icon)
    mutex = None
    mutex_error = ""
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            mutex = UpdateMutex.acquire()
        except WindowsUpdateError as exc:
            mutex_error = str(exc)
    manager = WindowManager(app, update_mutex=mutex, update_mutex_error=mutex_error)
    win = manager.open_new_window(restore_geometry=True)
    if win is not None:
        win.setWindowIcon(icon)
        paths = command_line_paths(app.arguments()[1:])

        def finish_startup() -> None:
            # One callback so a recovery prompt finishes before the files open.
            win.restore_recovery_drafts()
            win.open_command_line_paths(paths)

        QTimer.singleShot(0, finish_startup)
    exit_code = app.exec()

    # Flush top-level widgets before interpreter shutdown. Leaving the viewer's
    # QObject tree for SIP's atexit cleanup can segfault after a clean Qt exit.
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if mutex is not None:
        mutex.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
