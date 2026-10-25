"""Точка входа: python -m src.ui.main"""
import os
import shutil
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.ui.app import AppController
from src.ui.shell import ShellWindow
from src.ui.theme import apply_theme


def main() -> int:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as settings:
                for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
                             "WIBECODE_LLM_BASE_URL", "WIBECODE_LLM_API_KEY", "ELEVENLABS_API_KEY"):
                    try:
                        value = winreg.QueryValueEx(settings, name)[0]
                    except FileNotFoundError:
                        continue
                    if value and not os.environ.get(name):
                        os.environ[name] = value
        except FileNotFoundError:
            pass
    if getattr(sys, "frozen", False):
        os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "win32" and not (os.environ.get("WIBECODE_BLENDER") or shutil.which("blender")):
        blender_root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"
        versions = sorted(blender_root.glob("Blender*/blender.exe"))
        if versions:
            os.environ["WIBECODE_BLENDER"] = str(versions[-1])
    app = QApplication(sys.argv)
    apply_theme(app)
    window = ShellWindow()
    AppController(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
