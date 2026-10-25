"""Offline tests for src/llm: FakeLLMClient only, no network."""

import json

import pytest

from src import api
from src.llm import FakeLLMClient, LLMError, SpecGenerationError, generate_spec
from src.llm.client import AnthropicClient, strip_fences
from src.llm.prompt import EXAMPLE_3D_SPEC, EXAMPLE_SPEC, SYSTEM_PROMPT

USER_TEXT = (
    "Сделай ролик про рост продаж. "
    "Сначала заголовок «Итоги года». "
    "Потом график продаж по кварталам."
)

VALID = json.dumps(
    {
        "duration": 10,
        "scenes": [
            {"type": "text", "text": "Итоги года", "start": 0, "end": 5},
            {"type": "chart", "data": [[1, 10], [2, 15], [3, 22], [4, 30]], "start": 5, "end": 10},
        ],
    },
    ensure_ascii=False,
)

KNOWN_TYPES = {"text", "image", "chart"}
RENDER_MODES = ("2d", "3d")


def contract_check(raw):
    """Stand-in for api.parse_spec: contract rules from the project brief."""
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"невалидный JSON: {e}"
    if not isinstance(spec, dict) or not spec.get("scenes"):
        return "нужен объект с непустым списком scenes"
    if spec.get("render_mode", "2d") not in RENDER_MODES:
        return f"render_mode: неизвестный render_mode {spec['render_mode']!r}, допустимы: 2d, 3d"
    for i, scene in enumerate(spec["scenes"]):
        if scene.get("type") not in KNOWN_TYPES:
            return f"scenes[{i}]: неизвестный type {scene.get('type')!r}"
        if not scene["start"] < scene["end"] <= spec["duration"]:
            return f"scenes[{i}]: нужно start < end <= duration"
    return None


def test_valid_spec_from_three_sentences():
    fake = FakeLLMClient([VALID])
    raw = generate_spec(USER_TEXT, client=fake, check=contract_check)

    assert contract_check(raw) is None
    assert len(fake.calls) == 1
    assert fake.calls[0] == [{"role": "user", "content": USER_TEXT}]


def test_retry_sends_error_and_accepts_fixed_spec():
    fake = FakeLLMClient(["Вот ваш ролик!", VALID])
    raw = generate_spec(USER_TEXT, client=fake, check=contract_check)

    assert raw == VALID
    assert len(fake.calls) == 2
    retry = fake.calls[1]
    assert retry[1] == {"role": "assistant", "content": "Вот ваш ролик!"}
    assert retry[2]["role"] == "user"
    assert "невалидный JSON" in retry[2]["content"]


def test_gives_up_after_two_retries_with_clear_error():
    bad = json.dumps({"duration": 5, "scenes": [{"type": "video", "start": 0, "end": 5}]})
    fake = FakeLLMClient(["мусор", "{", bad, VALID])

    with pytest.raises(SpecGenerationError) as exc:
        generate_spec(USER_TEXT, client=fake, check=contract_check)

    assert len(fake.calls) == 3  # 1 attempt + 2 retries
    assert exc.value.attempts == 3
    assert "неизвестный type 'video'" in str(exc.value)
    assert exc.value.last_response == bad


def test_markdown_fences_are_stripped():
    fake = FakeLLMClient([f"```json\n{VALID}\n```"])
    assert generate_spec(USER_TEXT, client=fake, check=contract_check) == VALID
    assert strip_fences("  {\"a\": 1}  ") == '{"a": 1}'


def test_missing_api_key_is_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        AnthropicClient()


def test_system_prompt_demands_json_and_shows_contract():
    assert "ТОЛЬКО" in SYSTEM_PROMPT
    for field in ('"duration"', '"scenes"', '"text"', '"image"', '"chart"', '"start"', '"end"'):
        assert field in SYSTEM_PROMPT
    assert contract_check(EXAMPLE_SPEC) is None


def test_system_prompt_describes_optional_render_mode():
    for value in ('"render_mode"', '"2d"', '"3d"'):
        assert value in SYSTEM_PROMPT
    assert "необязательное" in SYSTEM_PROMPT
    # UI (B) appends this hint to user_text when the 3D toggle is on.
    assert 'render_mode: "3d"' in SYSTEM_PROMPT
    # The example stays in the old format: no render_mode means 2D.
    assert "render_mode" not in json.loads(EXAMPLE_SPEC)


def with_mode(mode):
    return json.dumps({**json.loads(VALID), "render_mode": mode}, ensure_ascii=False)


def test_3d_spec_is_returned_unchanged():
    fake = FakeLLMClient([with_mode("3d")])
    raw = generate_spec("Сделай 3D-ролик про рост продаж.", client=fake, check=contract_check)

    assert json.loads(raw)["render_mode"] == "3d"
    assert len(fake.calls) == 1


def test_wrong_render_mode_triggers_fix_up():
    fake = FakeLLMClient([with_mode("3D"), with_mode("3d")])
    raw = generate_spec("Сделай 3D-ролик про рост продаж.", client=fake, check=contract_check)

    assert json.loads(raw)["render_mode"] == "3d"
    assert len(fake.calls) == 2
    assert "render_mode" in fake.calls[1][-1]["content"]


def test_system_prompt_lists_say_choices_from_api():
    assert '"say"' in SYSTEM_PROMPT
    for value in (*api.SAY_WHO, *api.SAY_SHOTS):
        assert f'"{value}"' in SYSTEM_PROMPT


def test_examples_pass_real_parser():
    assert api.parse_spec(EXAMPLE_SPEC).render_mode == "2d"
    spec = api.parse_spec(EXAMPLE_3D_SPEC)
    assert spec.render_mode == "3d"
    assert {scene.type for scene in spec.scenes} == {"text", "say"}


def test_say_spec_passes_real_parser():
    fake = FakeLLMClient([EXAMPLE_3D_SPEC])
    raw = generate_spec('Диалог робота и девушки. render_mode: "3d"', client=fake)

    assert raw == EXAMPLE_3D_SPEC.strip()
    assert len(fake.calls) == 1


def test_say_without_3d_triggers_fix_up():
    payload = json.loads(EXAMPLE_3D_SPEC)
    del payload["render_mode"]
    in_2d = json.dumps(payload, ensure_ascii=False)
    with pytest.raises(api.SpecError) as rejected:
        api.parse_spec(in_2d)

    fake = FakeLLMClient([in_2d, EXAMPLE_3D_SPEC])
    raw = generate_spec('Диалог робота и девушки. render_mode: "3d"', client=fake)

    assert api.parse_spec(raw).render_mode == "3d"
    assert len(fake.calls) == 2
    assert str(rejected.value) in fake.calls[1][-1]["content"]


def test_system_prompt_lets_model_pick_style():
    assert '"style"' in SYSTEM_PROMPT
    for style in api.STYLES:
        assert f'"{style}"' in SYSTEM_PROMPT or f"{style} —" in SYSTEM_PROMPT
    assert api.parse_spec(EXAMPLE_SPEC).style == "vivid"
    assert api.parse_spec(EXAMPLE_3D_SPEC).style == "cinematic"
