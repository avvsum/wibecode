"""Render a local KayKit dialogue without an LLM or API key."""

import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    from src import api

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=[e for e in api.ENVIRONMENTS if e != "studio"],
                        default="forest")
    parser.add_argument("--cast", choices=[c for c in api.CASTS if c != "classic"],
                        default="knight_mage")
    parser.add_argument("--duration", type=float, default=4)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "kaykit.mp4")
    parser.add_argument("--blender", type=Path, help="Path to blender.exe if it is not in PATH")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0.1:
        parser.error("--duration должна быть конечным числом, не меньше 0.1 секунды")
    if args.blender:
        os.environ["WIBECODE_BLENDER"] = str(args.blender.resolve())

    half = args.duration / 2
    spec = api.parse_spec(json.dumps({
        "duration": args.duration, "render_mode": "3d",
        "environment": args.environment, "cast": args.cast,
        "scenes": [
            {"type": "say", "who": "robot", "shot": "wide",
             "text": "Новый мир начинается с истории!", "start": 0, "end": half},
            {"type": "say", "who": "girl", "shot": "medium",
             "text": "А наши герои готовы её рассказать.", "start": half, "end": args.duration},
        ],
    }, ensure_ascii=False))
    previous = -1

    def progress(done, total):
        nonlocal previous
        percent = done * 100 // total if total else 0
        if percent >= previous + 10 or done == total:
            print(f"Рендер: {done}/{total} кадров ({percent}%)", flush=True)
            previous = percent

    try:
        print(f"KayKit: {args.environment}, {args.cast}", flush=True)
        print(f"MP4: {api.render_video(spec, str(args.out), on_progress=progress)}")
        return 0
    except (api.RenderError, OSError) as error:
        print(f"Рендер не выполнен: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
