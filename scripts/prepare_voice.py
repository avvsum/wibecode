"""Prepare the Windows CPU voice payload: .venv/Scripts/python scripts/prepare_voice.py.

Requires Python 3.11 and uv. Downloads official CPython 3.11.9, PyTorch CPU
2.6.0, Chatterbox 0.1.7 and six files from the immutable HF revision below.
Only build/voice-runtime, build/voice-models and build/downloads are written;
the invoking Python environment is never changed. Interrupted models resume.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME, MODELS, DOWNLOADS = [ROOT / "build" / p for p in
                             ("voice-runtime", "voice-models", "downloads")]
PYTHON_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
PYTHON_SHA = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
FILES = ("ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt",
         "grapheme_mtl_merged_expanded_v1.json", "conds.pt", "Cangjie5_TC.json")
PROBE = ("import torch,torchaudio,perth,importlib.metadata as m; "
         "from chatterbox.mtl_tts import ChatterboxMultilingualTTS; "
         "assert torch.__version__ == torchaudio.__version__ == '2.6.0+cpu'; "
         "assert m.version('chatterbox-tts') == '0.1.7'; "
         "assert perth.PerthImplicitWatermarker is not None")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, path, size=None, sha=None):
    if path.exists() and (size is None or path.stat().st_size == size):
        if sha is None or digest(path) == sha:
            return
    part = path.with_suffix(path.suffix + ".part")
    if part.exists() and size is not None and part.stat().st_size == size:
        if sha is None or digest(part) == sha:
            part.replace(path)
            return
    for attempt in range(10):
        offset = part.stat().st_size if part.exists() else 0
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                append = response.status == 206 and offset > 0
                with part.open("ab" if append else "wb") as output:
                    while block := response.read1(256 * 1024):
                        output.write(block)
            if size is not None and part.stat().st_size != size:
                raise OSError(f"Incomplete download: {path.name}")
            if sha and digest(part) != sha:
                part.unlink()
                raise OSError(f"Checksum mismatch: {path.name}")
            part.replace(path)
            print(f"Ready: {path.name}", flush=True)
            return
        except OSError:
            if attempt == 9:
                raise
            time.sleep(1)


def main():
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11) or sys.maxsize <= 2**32:
        raise SystemExit("Run this builder with Windows Python 3.11 (64 bit).")
    for folder in (RUNTIME, MODELS, DOWNLOADS):
        folder.mkdir(parents=True, exist_ok=True)
    archive = DOWNLOADS / "python-3.11.9-embed-amd64.zip"
    download(PYTHON_URL, archive, sha=PYTHON_SHA)
    if not (RUNTIME / "python.exe").exists():
        with zipfile.ZipFile(archive) as package:
            package.extractall(RUNTIME)
    (RUNTIME / "python311._pth").write_text(
        "python311.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    target = RUNTIME / "Lib" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    python = str(RUNTIME / "python.exe")
    if subprocess.run([python, "-c", PROBE], capture_output=True).returncode:
        base = [shutil.which("uv") or "uv", "--no-config", "pip", "install",
                "--python", sys.executable, "--target", str(target)]
        cpu = ["torch==2.6.0+cpu", "torchaudio==2.6.0+cpu"]
        subprocess.run(base + ["--index-url", "https://download.pytorch.org/whl/cpu"] + cpu, check=True)
        subprocess.run(base + ["--index-url", "https://pypi.org/simple", "--extra-index-url",
                       "https://download.pytorch.org/whl/cpu", "--index-strategy", "unsafe-best-match",
                       "chatterbox-tts==0.1.7", "setuptools==80.10.2"] + cpu, check=True)
        subprocess.run([python, "-c", PROBE], check=True)
    (RUNTIME / "RUNTIME-PROVENANCE.json").write_text(json.dumps(
        {"url": PYTHON_URL, "sha256": PYTHON_SHA}, indent=2), encoding="utf-8")
    versions = sorted(({"name": d.metadata["Name"], "version": d.version} for d in
                       importlib.metadata.distributions(path=[str(target)])), key=lambda d: d["name"].lower())
    (RUNTIME / "PACKAGE-VERSIONS.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
    url = f"https://huggingface.co/api/models/ResembleAI/chatterbox/tree/{REVISION}?recursive=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        manifest = {f["path"]: f for f in json.load(response) if f["path"] in FILES}
    def model(name):
        item = manifest[name]
        source = f"https://huggingface.co/ResembleAI/chatterbox/resolve/{REVISION}/{name}?download=true"
        download(source, MODELS / name, item["size"], item.get("lfs", {}).get("oid"))
        return {"path": name, "bytes": item["size"], "sha256": digest(MODELS / name), "url": source}
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(model, FILES))
    shutil.copy2(target / "chatterbox_tts-0.1.7.dist-info" / "licenses" / "LICENSE", MODELS / "LICENSE")
    (MODELS / "PROVENANCE.json").write_text(json.dumps(
        {"repository": "ResembleAI/chatterbox", "revision": REVISION, "license": "MIT", "files": records},
        indent=2), encoding="utf-8")
    print("Voice payload ready.", flush=True)


if __name__ == "__main__":
    main()
