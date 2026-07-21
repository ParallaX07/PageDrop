import sys
from importlib.metadata import PackageNotFoundError, version

from PyQt6.QtWidgets import QApplication

from pagedrop.assets import app_icon
from pagedrop.ui.accessibility import install_accessibility
from pagedrop.ui.window_manager import WindowManager

_APP_NAME = "PageDrop"
_ORG_NAME = "PageDrop"


def _app_version() -> str:
    try:
        return version("pagedrop")
    except PackageNotFoundError:
        return "0.0.0"


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName(_ORG_NAME)
    app.setApplicationName(_APP_NAME)
    app.setApplicationVersion(_app_version())
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    install_accessibility(app)
    icon = app_icon()
    app.setWindowIcon(icon)
    manager = WindowManager(app)
    win = manager.open_new_window()
    win.setWindowIcon(icon)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
