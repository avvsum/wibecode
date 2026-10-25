"""DeepSeekClient и выбор провайдера: без сети, urlopen подменяется."""
import io
import json
import urllib.error
import urllib.request

import pytest

from src.llm import LLMError
from src.llm.client import AnthropicClient, DeepSeekClient, default_client, generate_spec

SPEC = '{"duration": 4, "scenes": [{"type": "text", "text": "Привет", "start": 0, "end": 4}]}'


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def reply(content, finish_reason="stop"):
    body = {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}]}
    return FakeResponse(json.dumps(body).encode("utf-8"))


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


def test_missing_key_names_the_variable():
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        DeepSeekClient()


def test_request_has_system_prompt_model_and_key(key, monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return reply("готово")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    text = DeepSeekClient().complete("системный промпт", [{"role": "user", "content": "привет"}])
    assert text == "готово"
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "deepseek-chat"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "системный промпт"}
    assert seen["body"]["messages"][1] == {"role": "user", "content": "привет"}


def test_model_can_be_overridden_by_env(key, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    seen = {}
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout: seen.update(json.loads(request.data)) or reply("ок"))
    DeepSeekClient().complete("s", [{"role": "user", "content": "u"}])
    assert seen["model"] == "deepseek-reasoner"


@pytest.mark.parametrize("code, message", [
    (401, "Неверный ключ API"),
    (402, "балансе DeepSeek"),
    (429, "лимит запросов"),
    (500, "Ошибка API DeepSeek (500): server down"),
])
def test_http_errors_become_readable(key, monkeypatch, code, message):
    def urlopen(request, timeout):
        body = io.BytesIO(json.dumps({"error": {"message": "server down"}}).encode("utf-8"))
        raise urllib.error.HTTPError(request.full_url, code, "error", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(LLMError, match=message.replace("(", r"\(").replace(")", r"\)")):
        DeepSeekClient().complete("s", [{"role": "user", "content": "u"}])


def test_no_network_is_readable(key, monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(LLMError, match="Нет соединения"):
        DeepSeekClient().complete("s", [{"role": "user", "content": "u"}])


def test_content_filter_is_a_refusal(key, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: reply("", "content_filter"))
    with pytest.raises(LLMError, match="отказалась"):
        DeepSeekClient().complete("s", [{"role": "user", "content": "u"}])


def test_default_is_deepseek_without_keys():
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        default_client()


def test_default_follows_the_only_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert isinstance(default_client(), AnthropicClient)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    assert isinstance(default_client(), DeepSeekClient), "при обоих ключах — DeepSeek"


def test_provider_env_wins_and_unknown_is_an_error(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("WIBECODE_LLM", "anthropic")
    assert isinstance(default_client(), AnthropicClient)
    monkeypatch.setenv("WIBECODE_LLM", "gpt")
    with pytest.raises(LLMError, match="Неизвестный провайдер"):
        default_client()


def test_generate_spec_goes_through_deepseek_by_default(key, monkeypatch):
    replies = iter(["```json\n" + SPEC + "\n```"])
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: reply(next(replies)))
    assert json.loads(generate_spec("ролик про приветствие"))["scenes"][0]["text"] == "Привет"
