"""Offline tests for src/llm: FakeLLMClient only, no network."""

import json

import pytest

from src import api
from src.llm import FakeLLMClient, LLMError, SpecGenerationError, generate_spec
from src.llm import client as llm_client
from src.llm.client import OpenAICompatibleClient, rank_models, strip_fences
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


def test_missing_base_url_or_key_is_clear_error():
    with pytest.raises(LLMError, match="адрес API"):
        OpenAICompatibleClient("", "key")
    with pytest.raises(LLMError, match="ключ API"):
        OpenAICompatibleClient("https://api.example.com/v1", "")


def test_settings_fall_back_to_environment(monkeypatch):
    monkeypatch.setenv("WIBECODE_LLM_BASE_URL", "api.example.com/v1/chat/completions")
    monkeypatch.setenv("WIBECODE_LLM_API_KEY", "key")
    assert OpenAICompatibleClient()._base == "https://api.example.com/v1"


def test_deepseek_key_alone_still_works(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    client = OpenAICompatibleClient()
    assert client._base == "https://api.deepseek.com" and client._key == "ds-key"


def test_rank_models_prefers_full_size_then_params_then_newest():
    models = [
        {"id": "text-embedding-3-large", "created": 9},
        {"id": "gpt-x-mini", "created": 8},
        {"id": "whisper-1", "created": 9},
        {"id": "gpt-x", "created": 5},
        {"id": "gpt-y", "created": 7},
        {"id": "meta/llama-3-8b-instruct"},
        {"id": "meta/llama-3-70b-instruct"},
    ]
    assert rank_models(models) == [
        "meta/llama-3-70b-instruct", "meta/llama-3-8b-instruct", "gpt-y", "gpt-x", "gpt-x-mini",
    ]


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def fake_api(monkeypatch, routes):
    """routes: (method, url) -> payload or (status, error payload); records requests."""
    import io
    import urllib.error

    seen = []

    def urlopen(request, timeout):
        body = json.loads(request.data) if request.data else None
        seen.append((request.get_method(), request.full_url, body, request.get_header("Authorization")))
        answer = routes(request.get_method(), request.full_url, body)
        if isinstance(answer, tuple):
            status, payload = answer
            raise urllib.error.HTTPError(
                request.full_url, status, "error", {}, io.BytesIO(json.dumps(payload).encode())
            )
        return _Response(answer)

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", urlopen)
    return seen


def reply(text, finish="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]}


def test_client_picks_model_once_and_sends_system_prompt(monkeypatch):
    def routes(method, url, body):
        if url.endswith("/models"):
            return {"data": [{"id": "small-mini"}, {"id": "big", "created": 2}, {"id": "embed-1"}]}
        return reply(VALID)

    seen = fake_api(monkeypatch, routes)
    client = OpenAICompatibleClient("https://api.example.com/v1/", "secret")
    assert generate_spec(USER_TEXT, client=client, check=contract_check) == VALID
    client.complete("sys", [{"role": "user", "content": "ещё"}])

    assert [(m, u) for m, u, _, _ in seen] == [
        ("GET", "https://api.example.com/v1/models"),
        ("POST", "https://api.example.com/v1/chat/completions"),
        ("POST", "https://api.example.com/v1/chat/completions"),
    ]
    body = seen[1][2]
    assert body["model"] == "big" and client.model == "big"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert body["messages"][1] == {"role": "user", "content": USER_TEXT}
    assert seen[1][3] == "Bearer secret"


def test_base_url_without_v1_and_rejected_model_fall_back(monkeypatch):
    def routes(method, url, body):
        if url == "https://api.example.com/models":
            return 404, {"error": {"message": "not found"}}
        if url == "https://api.example.com/v1/models":
            return {"data": [{"id": "chat-b", "created": 1}, {"id": "chat-a", "created": 2}]}
        if body["model"] == "chat-a":
            return 404, {"error": {"message": "The model chat-a does not exist"}}
        return reply("ответ")

    seen = fake_api(monkeypatch, routes)
    client = OpenAICompatibleClient("https://api.example.com", "k")
    assert client.complete("sys", [{"role": "user", "content": "x"}]) == "ответ"
    assert client.model == "chat-b"
    assert len(seen) == 4


@pytest.mark.parametrize("status, words", [(401, "Неверный ключ"), (402, "балансе"), (429, "лимит"), (500, r"\(500\): упало")])
def test_api_errors_are_readable(monkeypatch, status, words):
    def routes(method, url, body):
        if url.endswith("/models"):
            return {"data": [{"id": "m"}]}
        return status, {"error": {"message": "упало"}}

    fake_api(monkeypatch, routes)
    with pytest.raises(LLMError, match=words):
        OpenAICompatibleClient("https://api.example.com/v1", "k").complete("s", [])


def test_refusal_and_unreachable_host(monkeypatch):
    def routes(method, url, body):
        return {"data": [{"id": "m"}]} if url.endswith("/models") else reply("", "content_filter")

    fake_api(monkeypatch, routes)
    with pytest.raises(LLMError, match="отказалась"):
        OpenAICompatibleClient("https://api.example.com/v1", "k").complete("s", [])

    def unreachable(request, timeout):
        raise llm_client.urllib.error.URLError("no route")

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", unreachable)
    with pytest.raises(LLMError, match="Нет соединения с https://api.example.com/v1"):
        OpenAICompatibleClient("https://api.example.com/v1", "k").complete("s", [])


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


def test_system_prompt_lets_model_pick_music():
    assert '"music"' in SYSTEM_PROMPT
    for mood in api.MUSIC_MOODS:
        assert f'"{mood}"' in SYSTEM_PROMPT
    assert api.parse_spec(EXAMPLE_SPEC).music == "upbeat"
    assert api.parse_spec(EXAMPLE_3D_SPEC).music == "calm"
