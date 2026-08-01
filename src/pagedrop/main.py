import sys
from importlib.metadata import PackageNotFoundError, version

_APP_NAME = "PageDrop"
_ORG_NAME = "PageDrop"

# Frozen: helpers re-enter this exe before Qt starts.
_OFFICE_COM_WORKER_FLAG = "--pagedrop-office-com-worker"


def _app_version() -> str:
    try:
        return version("pagedrop")
    except PackageNotFoundError:
        return "0.0.0"


def main() -> int:
    if _OFFICE_COM_WORKER_FLAG in sys.argv:
        from pagedrop.helpers.office_com_worker import main as worker_main

        argv = [a for a in sys.argv[1:] if a != _OFFICE_COM_WORKER_FLAG]
        return worker_main(argv)

    from pagedrop.core.redact import REDACT_VERIFY_FLAG

    if REDACT_VERIFY_FLAG in sys.argv:
        from pagedrop.core.redact import main as redact_main

        argv = [a for a in sys.argv[1:] if a != REDACT_VERIFY_FLAG]
        return redact_main(argv)

    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QApplication

    from pagedrop.assets import app_icon
    from pagedrop.ui.accessibility import install_accessibility
    from pagedrop.ui.window_manager import WindowManager

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
    manager = WindowManager(app)
    win = manager.open_new_window()
    win.restore_saved_geometry()
    win.setWindowIcon(icon)
    exit_code = app.exec()

    # Flush top-level widgets before interpreter shutdown. Leaving the viewer's
    # QObject tree for SIP's atexit cleanup can segfault after a clean Qt exit.
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return exit_code


if __name__ == "__main__":
    main()
