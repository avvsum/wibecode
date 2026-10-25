import json

import pytest


def test_render_video_rejects_3d_until_engine_is_implemented(api, payload, tmp_path):
    payload["render_mode"] = "3d"
    spec = api.parse_spec(json.dumps(payload))
    output = tmp_path / "unsupported-3d.mp4"
    with pytest.raises(NotImplementedError):
        api.render_video(spec, str(output))
    assert not output.exists()
