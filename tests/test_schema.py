import json

import pytest


def test_render_mode_defaults_to_2d_for_legacy_json(api, payload):
    assert "render_mode" not in payload
    spec = api.parse_spec(json.dumps(payload))
    assert spec.render_mode == "2d"


@pytest.mark.parametrize("mode", ["2d", "3d"])
def test_accepts_supported_render_mode(api, payload, mode):
    payload["render_mode"] = mode
    assert api.parse_spec(json.dumps(payload)).render_mode == mode


@pytest.mark.parametrize("mode", ["4d", "", "3D", None, 3])
def test_invalid_render_mode_raises_spec_error(api, payload, mode):
    payload["render_mode"] = mode
    with pytest.raises(api.SpecError) as caught:
        api.parse_spec(json.dumps(payload))
    message = str(caught.value)
    assert "render_mode" in message
    assert "2d" in message and "3d" in message


def test_accepts_all_scene_types_and_adjacent_intervals(api, valid_raw):
    spec = api.parse_spec(valid_raw)
    assert spec.duration == 3
    assert [scene.type for scene in spec.scenes] == ["text", "image", "chart"]
    assert spec.scenes[0].text == "Привет, Москва!"
    assert [list(point) for point in spec.scenes[2].data] == [[1, 2], [2, 4]]


def test_accepts_contract_example_with_unfilled_tail(api, payload):
    payload["duration"] = 30
    spec = api.parse_spec(json.dumps(payload))
    assert spec.duration == 30
    assert spec.scenes[-1].end == 3


@pytest.mark.parametrize("raw", ["", "{", "not json", "[]", "null", "{}"])
def test_invalid_json_or_root_raises_spec_error(api, raw):
    with pytest.raises(api.SpecError) as caught:
        api.parse_spec(raw)
    assert str(caught.value).strip()


@pytest.mark.parametrize(
    "change",
    [
        {"scenes": []},
        {"duration": 0},
        {"duration": -1},
    ],
    ids=["empty-scenes", "zero-duration", "negative-duration"],
)
def test_invalid_spec_raises_spec_error(api, payload, change):
    payload.update(change)
    with pytest.raises(api.SpecError) as caught:
        api.parse_spec(json.dumps(payload))
    assert str(caught.value).strip()


@pytest.mark.parametrize(
    "change",
    [
        {"type": "video"},
        {"end": 4},
        {"start": 1, "end": 1},
        {"start": 2, "end": 1},
        {"end": 1.5},
    ],
    ids=["unknown-type", "past-duration", "zero-length", "reversed", "overlap"],
)
def test_invalid_scene_raises_spec_error(api, payload, change):
    payload["scenes"][0].update(change)
    with pytest.raises(api.SpecError) as caught:
        api.parse_spec(json.dumps(payload))
    assert str(caught.value).strip()


@pytest.mark.parametrize("index,field", [(0, "text"), (1, "path"), (2, "data")])
def test_scene_requires_its_content(api, payload, index, field):
    del payload["scenes"][index][field]
    with pytest.raises(api.SpecError):
        api.parse_spec(json.dumps(payload))
