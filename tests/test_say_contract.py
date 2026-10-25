"""Acceptance checks for the 3D contract approved by Lev on 25.10.2026."""

import json

import pytest

from src import api


def say_payload():
    return {"duration": 4, "render_mode": "3d", "scenes": [
        {"type": "say", "who": "robot", "shot": "close", "text": "Привет!",
         "start": 0, "end": 4},
    ]}


@pytest.mark.parametrize("who", ["robot", "girl"])
@pytest.mark.parametrize("shot", ["wide", "medium", "close"])
def test_accepts_each_say_character_and_shot(who, shot):
    payload = say_payload()
    payload["scenes"][0].update(who=who, shot=shot)
    spec = api.parse_spec(json.dumps(payload))
    scene = spec.scenes[0]
    assert spec.render_mode == "3d"
    assert (scene.type, scene.who, scene.shot, scene.text) == ("say", who, shot, "Привет!")


@pytest.mark.parametrize("field", ["who", "shot", "text", "start", "end"])
def test_say_requires_every_field(field):
    payload = say_payload()
    del payload["scenes"][0][field]
    with pytest.raises(api.SpecError) as caught:
        api.parse_spec(json.dumps(payload))
    assert field in str(caught.value)


@pytest.mark.parametrize("field,value", [
    ("who", "Robot"), ("who", "unknown"), ("who", None), ("who", 1),
    ("shot", "Close"), ("shot", "unknown"), ("shot", None), ("shot", 1),
    ("text", ""), ("text", None),
])
def test_say_rejects_invalid_content(field, value):
    payload = say_payload()
    payload["scenes"][0][field] = value
    with pytest.raises(api.SpecError) as caught:
        api.parse_spec(json.dumps(payload))
    assert field in str(caught.value)


@pytest.mark.parametrize("explicit_mode", [False, True])
def test_say_is_rejected_in_legacy_and_explicit_2d(explicit_mode):
    payload = say_payload()
    if explicit_mode:
        payload["render_mode"] = "2d"
    else:
        del payload["render_mode"]
    with pytest.raises(api.SpecError):
        api.parse_spec(json.dumps(payload))


def test_3d_can_mix_legacy_scenes_and_say():
    payload = say_payload()
    payload["scenes"] = [
        {"type": "text", "text": "Заголовок", "start": 0, "end": 1},
        {"type": "image", "path": "a.png", "start": 1, "end": 2},
        {"type": "chart", "data": [[1, 2], [2, 4]], "start": 2, "end": 3},
        {**payload["scenes"][0], "start": 3},
    ]
    spec = api.parse_spec(json.dumps(payload))
    assert [scene.type for scene in spec.scenes] == ["text", "image", "chart", "say"]


@pytest.mark.parametrize("change", [
    {"start": -1}, {"start": 4}, {"end": 5}, {"end": 0},
    {"start": float("nan")}, {"end": float("inf")},
])
def test_say_uses_existing_timeline_validation(change):
    payload = say_payload()
    payload["scenes"][0].update(change)
    with pytest.raises(api.SpecError):
        api.parse_spec(json.dumps(payload))


def test_say_cannot_overlap_another_scene():
    payload = say_payload()
    payload["scenes"].append({"type": "text", "text": "Заголовок", "start": 0, "end": 1})
    with pytest.raises(api.SpecError):
        api.parse_spec(json.dumps(payload))


def test_api_exposes_fixed_say_choices_for_llm_prompt():
    assert set(api.SAY_WHO) == {"robot", "girl"}
    assert set(api.SAY_SHOTS) == {"wide", "medium", "close"}
