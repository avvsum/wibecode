import importlib
import json

import pytest


@pytest.fixture
def api():
    module = importlib.import_module("src.api")
    for name in ("parse_spec", "render_video", "SpecError"):
        if not hasattr(module, name):
            pytest.fail(f"Зона A: src.api ещё не экспортирует {name}", pytrace=False)
    return module


@pytest.fixture
def payload():
    return {
        "duration": 3,
        "scenes": [
            {"type": "text", "text": "Привет, Москва!", "start": 0, "end": 1},
            {"type": "image", "path": "a.png", "start": 1, "end": 2},
            {"type": "chart", "data": [[1, 2], [2, 4]], "start": 2, "end": 3},
        ],
    }


@pytest.fixture
def valid_raw(payload):
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def fake_llm(monkeypatch):
    try:
        client = importlib.import_module("src.llm.client")
    except ModuleNotFoundError as error:
        if error.name != "src.llm.client":
            raise
        pytest.fail("Зона C: src/llm/client.py ещё не реализован", pytrace=False)

    def install(responses):
        fake = client.FakeLLMClient(responses)
        monkeypatch.setattr(client, "AnthropicClient", lambda: fake)
        generate_spec = importlib.import_module("src.llm").generate_spec
        return generate_spec, fake.calls

    return install
