"""User text -> raw JSON spec (and YouTube metadata) via an LLM, with fix-up retries."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Callable, Optional, Protocol

from src.llm.metadata import VideoMetadata, check_metadata, parse_metadata
from src.llm.prompt import METADATA_PROMPT, SYSTEM_PROMPT, fix_message, metadata_request

API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-opus-5-5"
DEEPSEEK_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_MODEL_ENV = "DEEPSEEK_MODEL"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
PROVIDER_ENV = "WIBECODE_LLM"  # "deepseek" | "anthropic"; без него — по заданному ключу
MAX_RETRIES = 2

Message = dict  # {"role": "user" | "assistant", "content": str}
# Returns an error message for an invalid spec, or None if the spec is valid.
SpecCheck = Callable[[str], Optional[str]]


class LLMError(Exception):
    """Provider failure: missing key, network, API error."""


class SpecGenerationError(Exception):
    """The model did not produce a valid spec after all retries."""

    def __init__(self, attempts: int, last_error: str, last_response: str):
        self.attempts = attempts
        self.last_error = last_error
        self.last_response = last_response
        super().__init__(
            f"Модель не смогла вернуть корректный JSON за {attempts} попытки. "
            f"Последняя ошибка: {last_error}"
        )


class LLMClient(Protocol):
    def complete(self, system: str, messages: list[Message]) -> str:
        """Return the model's text reply to the conversation."""
        ...


class AnthropicClient:
    """Claude via the official SDK. The key is read from ANTHROPIC_API_KEY."""

    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 120.0):
        api_key = os.environ.get(API_KEY_ENV)
        if not api_key:
            raise LLMError(f"Не задан ключ API: установите переменную окружения {API_KEY_ENV}.")
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("Пакет anthropic не установлен: pip install -r requirements.txt") from e
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self._model = model

    def complete(self, system: str, messages: list[Message]) -> str:
        anthropic = self._anthropic
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=16000,
                output_config={"effort": "medium"},
                system=system,
                messages=messages,
            )
        except anthropic.AuthenticationError as e:
            raise LLMError(f"Неверный ключ API ({API_KEY_ENV}).") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Превышен лимит запросов к API, попробуйте позже.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Ошибка API ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Нет соединения с API, проверьте интернет.") from e

        if response.stop_reason == "refusal":
            raise LLMError("Модель отказалась отвечать на этот запрос, переформулируйте описание.")
        return "".join(b.text for b in response.content if b.type == "text")


class DeepSeekClient:
    """DeepSeek via its OpenAI-compatible HTTP API, standard library only. Key: DEEPSEEK_API_KEY."""

    def __init__(self, model: Optional[str] = None, timeout: float = 120.0, url: str = DEEPSEEK_URL):
        api_key = os.environ.get(DEEPSEEK_KEY_ENV)
        if not api_key:
            raise LLMError(f"Не задан ключ API: установите переменную окружения {DEEPSEEK_KEY_ENV}.")
        self._key = api_key
        self._model = model or os.environ.get(DEEPSEEK_MODEL_ENV) or DEEPSEEK_MODEL
        self._timeout = timeout
        self._url = url

    def complete(self, system: str, messages: list[Message]) -> str:
        body = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": 8000,
            "stream": False,
        }
        request = urllib.request.Request(
            self._url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # раньше URLError: HTTPError — его наследник
            raise LLMError(_deepseek_http_error(e)) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError("Нет соединения с API DeepSeek, проверьте интернет.") from e
        except ValueError as e:
            raise LLMError("DeepSeek вернул ответ не в формате JSON.") from e
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("Неожиданный ответ DeepSeek: в нём нет текста.") from e
        if choice.get("finish_reason") == "content_filter":
            raise LLMError("Модель отказалась отвечать на этот запрос, переформулируйте описание.")
        return text


def _deepseek_http_error(e: urllib.error.HTTPError) -> str:
    known = {
        401: f"Неверный ключ API ({DEEPSEEK_KEY_ENV}).",
        402: "На балансе DeepSeek закончились средства, пополните счёт.",
        429: "Превышен лимит запросов к API, попробуйте позже.",
    }
    if e.code in known:
        return known[e.code]
    try:
        detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
    except (ValueError, AttributeError, OSError):
        detail = ""
    return f"Ошибка API DeepSeek ({e.code})" + (f": {detail}" if detail else ".")


def default_client() -> LLMClient:
    """Provider from WIBECODE_LLM; otherwise by which key is set. With no keys — DeepSeek."""
    provider = os.environ.get(PROVIDER_ENV, "").strip().lower()
    if not provider:
        only_anthropic = os.environ.get(API_KEY_ENV) and not os.environ.get(DEEPSEEK_KEY_ENV)
        provider = "anthropic" if only_anthropic else "deepseek"
    if provider == "deepseek":
        return DeepSeekClient()
    if provider == "anthropic":
        return AnthropicClient()
    raise LLMError(f"Неизвестный провайдер {provider!r} в {PROVIDER_ENV}: допустимы deepseek и anthropic.")


class FakeLLMClient:
    """Offline client for tests: returns canned replies in order, records calls."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list[Message]] = []

    def complete(self, system: str, messages: list[Message]) -> str:
        self.calls.append([dict(m) for m in messages])
        if not self._responses:
            raise LLMError("FakeLLMClient: заготовленные ответы закончились.")
        return self._responses.pop(0)


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def strip_fences(text: str) -> str:
    """Remove a ```json ... ``` wrapper that models sometimes add."""
    match = _FENCE_RE.match(text)
    return (match.group(1) if match else text).strip()


def check_with_api(raw: str) -> Optional[str]:
    """Validate with the core parser (A): api.parse_spec raises SpecError."""
    from src.api import SpecError, parse_spec

    try:
        parse_spec(raw)
    except SpecError as e:
        return str(e)
    return None


def generate_spec(
    user_text: str,
    *,
    client: Optional[LLMClient] = None,
    check: Optional[SpecCheck] = None,
) -> str:
    """Return a raw JSON spec for user_text that passed validation.

    Raises SpecGenerationError after MAX_RETRIES failed fix-up attempts,
    LLMError if the provider is unavailable.
    """
    client = client if client is not None else default_client()
    check = check if check is not None else check_with_api
    return _complete_checked(client, SYSTEM_PROMPT, user_text, check)


def generate_metadata(
    user_text: str,
    spec_json: str,
    *,
    client: Optional[LLMClient] = None,
) -> VideoMetadata:
    """Return a YouTube title, description and tags for a generated spec.

    Raises SpecGenerationError after MAX_RETRIES failed fix-up attempts,
    LLMError if the provider is unavailable.
    """
    client = client if client is not None else default_client()
    raw = _complete_checked(
        client, METADATA_PROMPT, metadata_request(user_text, spec_json), check_metadata
    )
    return parse_metadata(raw)


def _complete_checked(client: LLMClient, system: str, content: str, check: SpecCheck) -> str:
    """Ask until check() accepts the reply; each fix-up request carries its error."""
    messages: list[Message] = [{"role": "user", "content": content}]
    attempts = 1 + MAX_RETRIES
    for attempt in range(1, attempts + 1):
        reply = client.complete(system, messages)
        raw = strip_fences(reply)
        error = check(raw)
        if error is None:
            return raw
        if attempt == attempts:
            raise SpecGenerationError(attempts, error, reply)
        messages.append({"role": "assistant", "content": reply or "(пустой ответ)"})
        messages.append({"role": "user", "content": fix_message(error)})
    raise AssertionError("unreachable")
