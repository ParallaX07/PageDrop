import sys

from PyQt6.QtWidgets import QApplication

from pagedrop.assets import app_icon
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.theme import app_stylesheet


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    icon = app_icon()
    app.setWindowIcon(icon)
    win = MainWindow()
    win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
