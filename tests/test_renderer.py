import json
import subprocess

import pytest


def test_render_video_rejects_3d_until_engine_is_implemented(api, payload, tmp_path):
    payload["render_mode"] = "3d"
    spec = api.parse_spec(json.dumps(payload))
    output = tmp_path / "unsupported-3d.mp4"
    with pytest.raises(NotImplementedError):
        api.render_video(spec, str(output))
    assert not output.exists()


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
