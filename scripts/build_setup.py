"""Build the offline Windows installer after build.py and voice runtime staging."""

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check staged files without compiling")
    parser.add_argument("--iscc", type=Path, help="Path to Inno Setup 6.7+ ISCC.exe")
    parser.add_argument("--smoke", action="store_true", help="Use a separate test installer identity")
    args = parser.parse_args(argv)
    compiler = args.iscc or Path(shutil.which("ISCC.exe") or ROOT / "build/tools/InnoSetup/ISCC.exe")
    required = [compiler, ROOT / "installer/ShortsStudio.iss"]
    required += [ROOT / "dist/ShortsStudio" / name for name in (
        "ShortsStudio.exe", "ffmpeg.exe", "ffprobe.exe", "_internal/src/llm/chatterbox_worker.py",
    )]
    runtime, models = ROOT / "build/voice-runtime", ROOT / "build/voice-models"
    required += [runtime / "python.exe", runtime / "Lib/site-packages/chatterbox/mtl_tts.py"]
    required += [models / name for name in ("ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt",
        "grapheme_mtl_merged_expanded_v1.json", "conds.pt", "Cangjie5_TC.json")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("Missing installer inputs: " + ", ".join(missing))
    if args.check:
        print("Installer inputs and compiler found; compilation was not started.")
        return 0
    output = ROOT / "dist" / ("setup-smoke" if args.smoke else "setup")
    command = [str(compiler), f"/DRepoRoot={ROOT}", f"/DSetupOutputDir={output}"]
    if args.smoke:
        command += ["/DSetupAppId=ShortsStudio.SetupSmoke", "/DSetupAppName=Shorts Studio (Setup Smoke)",
                    "/DSetupOutputName=ShortsStudio-Setup-Smoke",
                    f"/DSetupDefaultDir={ROOT / 'build/installer-smoke'}"]
    code = subprocess.run(command + [str(ROOT / "installer/ShortsStudio.iss")], cwd=ROOT, check=False).returncode
    if code == 0:
        for artifact in sorted(output.glob("ShortsStudio-Setup*")):
            print(f"{artifact}: {artifact.stat().st_size} bytes")
        print("Keep the setup EXE and every BIN file together when distributing.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
