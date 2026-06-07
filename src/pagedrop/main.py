import sys

from PyQt6.QtWidgets import QApplication, QMainWindow


def main():
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("PageDrop")
    win.resize(900, 650)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
