"""Точка входа: python -m src.ui.main"""
import sys

from PySide6.QtWidgets import QApplication

from src.ui.app import AppController
from src.ui.shell import ShellWindow
from src.ui.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = ShellWindow()
    AppController(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
