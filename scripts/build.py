"""Build the PySide6 desktop app with PyInstaller (FFmpeg stays external)."""

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Проверить входные файлы без сборки")
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 11):
        parser.error("Сборка требует Python 3.11")
    required = ("src/ui/main.py", "src/api/__init__.py", "src/core/schema.py",
                "src/core/renderer.py", "src/core/render3d/blender_scene.py",
                "src/core/render3d/kaykit_scene.py",
                "src/llm/client.py", "src/llm/prompt.py")
    missing = [name for name in required if not (ROOT / name).is_file()]
    for module in ("PyInstaller", "PySide6", "pydantic", "PIL", "googleapiclient", "google_auth_oauthlib"):
        if importlib.util.find_spec(module) is None:
            missing.append(f"пакет {module}")
    if missing:
        print("Сборка невозможна, отсутствуют: " + ", ".join(missing), file=sys.stderr)
        return 1
    if args.check:
        print("Входные файлы и зависимости найдены; сборка ещё не запускалась.")
        return 0

    command = [sys.executable, "-m", "PyInstaller", "--name", "ShortsStudio", "--onedir",
               "--windowed", "--paths", str(ROOT), "--distpath", str(ROOT / "dist"),
               "--workpath", str(ROOT / "build" / "work"), "--specpath", str(ROOT / "build"),
               "--add-data", f"{ROOT / 'assets'}:assets",
               # Blender runs this script itself, so PyInstaller cannot see it as an import.
               "--add-data", f"{ROOT / 'src/core/render3d'}:src/core/render3d",
               # Optional local voice (requirements-chatterbox.txt) is several GB of PyTorch:
               # keep it out of the bundle; Chatterbox works when running from source.
               "--exclude-module", "chatterbox", "--exclude-module", "torch",
               str(ROOT / "src" / "ui" / "main.py")]
    build_env = os.environ.copy()
    if sys.platform == "win32":
        # Foreign tools on PATH may provide DLLs (for example Poppler's ICU) that
        # shadow Windows APIs in the frozen app. Resolve system DLLs from Windows.
        windows = Path(build_env.get("SystemRoot", r"C:\Windows"))
        build_env["PATH"] = os.pathsep.join(map(str, (
            Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows,
        )))
    code = subprocess.run(command, cwd=ROOT, check=False, env=build_env).returncode
    if code == 0:
        # The googleapiclient hook bundles ~600 API descriptions (~120 MB); the app needs
        # only YouTube for publishing.
        docs = ROOT / "dist" / "ShortsStudio" / "_internal" / "googleapiclient" / "discovery_cache" / "documents"
        for doc in docs.glob("*.json"):
            if doc.name != "youtube.v3.json":
                doc.unlink()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
