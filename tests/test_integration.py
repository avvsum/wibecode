import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image


@pytest.mark.integration
@pytest.mark.parametrize("duration", [3, 30])
def test_fake_llm_to_mp4(api, fake_llm, payload, tmp_path, duration):
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            pytest.fail(f"Для integration необходим {executable} в PATH", pytrace=False)

    image_path = tmp_path / "Москва.png"
    Image.new("RGB", (96, 96), "navy").save(image_path)
    payload["duration"] = duration
    payload["scenes"][1]["path"] = str(image_path)
    for index, scene in enumerate(payload["scenes"]):
        scene.update(start=index * duration / 3, end=(index + 1) * duration / 3)
    # Keep the old JSON shape: omission of render_mode must still render in 2D.
    assert "render_mode" not in payload
    generate_spec, requests = fake_llm([json.dumps(payload, ensure_ascii=False)])
    raw = generate_spec("Покажи заголовок. Добавь изображение. Заверши графиком.")
    spec = api.parse_spec(raw)
    assert spec.render_mode == "2d"
    output = tmp_path / "готовые ролики" / "demo.mp4"
    output.parent.mkdir()
    result = api.render_video(spec, str(output))
    assert isinstance(result, str)
    assert Path(result).resolve() == output.resolve()
    assert output.is_file() and output.stat().st_size > 0
    assert len(requests) == 1

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "format=duration,format_name:stream=width,height,avg_frame_rate,r_frame_rate",
         "-of", "json", str(output)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    metadata = json.loads(probe.stdout)
    assert "mp4" in metadata["format"]["format_name"].split(",")
    assert float(metadata["format"]["duration"]) == pytest.approx(duration, abs=0.1)
    stream = metadata["streams"][0]
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert Fraction(stream["r_frame_rate"]) == 60
    assert Fraction(stream["avg_frame_rate"]) == 60
