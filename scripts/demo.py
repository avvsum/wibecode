"""Offline FakeLLMClient -> generate_spec -> parse_spec -> MP4 demo."""

import argparse
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "demo.mp4")
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--text", default="Покажи заголовок. Добавь картинку. Заверши графиком.")
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 11):
        parser.error("Проект требует Python 3.11")
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("--duration должна быть положительным конечным числом")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        parser.error("Добавьте внешние ffmpeg и ffprobe в PATH")

    try:
        from PIL import Image
        from src.api import parse_spec, render_video
        from src.llm import client

        output = args.out.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="shorts-demo-") as directory:
            image = Path(directory) / "image.png"
            Image.new("RGB", (320, 320), "navy").save(image)
            step = args.duration / 3
            payload = {"duration": args.duration, "scenes": [
                {"type": "text", "text": "Привет, Москва!", "start": 0, "end": step},
                {"type": "image", "path": str(image), "start": step, "end": 2 * step},
                {"type": "chart", "data": [[1, 2], [2, 4]], "start": 2 * step,
                 "end": args.duration},
            ]}
            fake = client.FakeLLMClient([json.dumps(payload, ensure_ascii=False)])
            with patch.object(client, "AnthropicClient", return_value=fake):
                raw = client.generate_spec(args.text)
            result = render_video(parse_spec(raw), str(output))
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError("Движок не создал непустой MP4")
        print(f"MP4: {result}")
        return 0
    except Exception as error:
        print(f"Демо не выполнено: {error}", file=sys.stderr)
        print("Нужны реализации A/C и тестовый интерфейс C из docs/README.md.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
