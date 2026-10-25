import json
import os
import shutil
import subprocess
from fractions import Fraction

import pytest

SAY_SPEC = {"duration": 2, "render_mode": "3d", "scenes": [
    {"type": "text", "text": "Заголовок", "start": 0, "end": 0.5},
    {"type": "say", "who": "robot", "shot": "close", "text": "Привет, *мир*!", "start": 0.5, "end": 2},
]}


def test_3d_without_blender_raises_tool_not_found(api, monkeypatch, tmp_path):
    spec = api.parse_spec(json.dumps(SAY_SPEC))
    monkeypatch.delenv("WIBECODE_BLENDER", raising=False)
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "blender" else real_which(name, *a, **k))
    output = tmp_path / "no-blender.mp4"
    with pytest.raises(api.ToolNotFoundError) as caught:
        api.render_video(spec, str(output))
    assert isinstance(caught.value, FileNotFoundError)
    assert "Blender" in str(caught.value)
    assert not output.exists()


@pytest.mark.integration
@pytest.mark.blender
def test_3d_renders_mp4_at_30_fps(api, tmp_path):
    if not (os.environ.get("WIBECODE_BLENDER") or shutil.which("blender")):
        pytest.fail("Для теста blender нужен Blender в PATH или WIBECODE_BLENDER", pytrace=False)
    spec = api.parse_spec(json.dumps(SAY_SPEC))
    calls = []
    output = tmp_path / "3d.mp4"
    result = api.render_video(spec, str(output), on_progress=lambda d, n: calls.append((d, n)))
    assert result == str(output.resolve())
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert Fraction(stream["r_frame_rate"]) == 30
    assert abs(float(info["format"]["duration"]) - SAY_SPEC["duration"]) <= 0.1
    assert calls[0] == (0, 60) and calls[-1] == (60, 60)
    assert all(a[0] <= b[0] for a, b in zip(calls, calls[1:]))


def test_subframe_video_raises_render_error_before_launching_ffmpeg(api, tmp_path, monkeypatch):
    spec = api.parse_spec(json.dumps({"duration": 0.001, "scenes": [
        {"type": "text", "text": "x", "start": 0, "end": 0.001},
    ]}))

    def unexpected_process(*args, **kwargs):
        pytest.fail("Видео без единого кадра не должно запускать FFmpeg", pytrace=False)

    monkeypatch.setattr(subprocess, "run", unexpected_process)
    output = tmp_path / "too-short.mp4"
    with pytest.raises(api.RenderError) as caught:
        api.render_video(spec, str(output))
    assert str(caught.value).strip()
    assert not output.exists()


@pytest.mark.integration
@pytest.mark.parametrize("outcome", ["cancel", "error"])
def test_final_progress_veto_keeps_existing_output(api, payload, tmp_path, outcome):
    payload["scenes"] = [{"type": "text", "text": "x", "start": 0, "end": 1}]
    payload["duration"] = 1
    spec = api.parse_spec(json.dumps(payload))
    output = tmp_path / "keep.mp4"
    output.write_bytes(b"OLD")

    def on_progress(done, total):
        if done == total:
            if outcome == "cancel":
                return False
            raise RuntimeError("UI callback failed")
        return True

    expected = api.RenderCancelled if outcome == "cancel" else RuntimeError
    with pytest.raises(expected):
        api.render_video(spec, str(output), on_progress=on_progress)
    assert output.read_bytes() == b"OLD"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.mp4"]
