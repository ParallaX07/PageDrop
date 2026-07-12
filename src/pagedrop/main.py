import sys

from PyQt6.QtWidgets import QApplication

from pagedrop.assets import app_icon
from pagedrop.ui.theme import app_stylesheet
from pagedrop.ui.window_manager import WindowManager


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    icon = app_icon()
    app.setWindowIcon(icon)
    manager = WindowManager(app)
    win = manager.open_new_window()
    win.setWindowIcon(icon)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
