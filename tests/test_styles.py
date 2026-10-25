import json
import shutil
import subprocess
from fractions import Fraction

import pytest
from PIL import Image, ImageChops

from src.core import styles


def spec_json(**extra):
    return json.dumps({"duration": 1, **extra, "scenes": [
        {"type": "text", "text": "Привет, мир", "start": 0, "end": 0.5},
        {"type": "chart", "data": [[1, 2], [2, 5], [3, 3]], "start": 0.5, "end": 1},
    ]}, ensure_ascii=False)  # fmt: skip


def test_every_style_has_a_filter(api):
    assert set(api.STYLES) == set(styles.FILTERS)


def test_style_is_optional_and_validated(api):
    assert api.parse_spec(spec_json()).style == "none"
    assert api.parse_spec(spec_json(style="pixel")).style == "pixel"
    with pytest.raises(api.SpecError, match="неизвестный style 'neon', допустимы: none, cinematic"):
        api.parse_spec(spec_json(style="neon"))


@pytest.mark.integration
@pytest.mark.parametrize("style", ["cinematic", "vivid", "bw", "sepia", "pixel", "retro",
                                   "warm", "cold", "dreamy"])  # fmt: skip
def test_style_keeps_size_fps_and_length(api, tmp_path, style):
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            pytest.fail(f"Для integration необходим {executable} в PATH", pytrace=False)
    video = api.render_video(api.parse_spec(spec_json(style=style)), str(tmp_path / "v.mp4"))

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "format=duration:stream=width,height,r_frame_rate,pix_fmt", "-of", "json", video],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    metadata = json.loads(probe.stdout)
    stream = metadata["streams"][0]
    assert (stream["width"], stream["height"], stream["pix_fmt"]) == (1080, 1920, "yuv420p")
    assert Fraction(stream["r_frame_rate"]) == 60
    assert float(metadata["format"]["duration"]) == pytest.approx(1, abs=0.1)

    if style == "bw":
        frame = tmp_path / "frame.png"
        subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.75", "-i", video, "-frames:v", "1",
                        str(frame)], check=True, timeout=30)  # fmt: skip
        r, g, b = Image.open(frame).convert("RGB").split()
        spread = max(ImageChops.difference(x, y).getextrema()[1] for x, y in ((r, g), (g, b), (r, b)))
        assert spread <= 6  # no colour left in the chart


def test_3d_assembly_applies_style(api, tmp_path):
    from src.core.render3d import FPS, BlenderRenderer, _plan

    spec = api.parse_spec(json.dumps({"duration": 2, "render_mode": "3d", "style": "pixel",
        "scenes": [{"type": "say", "who": "robot", "shot": "close", "text": "Привет",
                    "start": 0, "end": 2}]}, ensure_ascii=False))  # fmt: skip
    total = round(spec.duration * FPS)
    lines = [(spec.scenes[0], 1, total)]
    cmd = BlenderRenderer._assemble("ffmpeg", spec, _plan(spec, total), lines,
                                    str(tmp_path), str(tmp_path), "out.mp4")  # fmt: skip

    graph = cmd[cmd.index("-filter_complex") + 1]
    assert styles.FILTERS["pixel"] in graph
    assert cmd[cmd.index("-map") + 1] == "[styled]"
