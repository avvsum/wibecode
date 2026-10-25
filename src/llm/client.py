"""User text -> raw JSON spec (and YouTube metadata) via an LLM, with fix-up retries."""

from __future__ import annotations

import os
import re
from typing import Callable, Optional, Protocol

from src.llm.metadata import VideoMetadata, check_metadata, parse_metadata
from src.llm.prompt import METADATA_PROMPT, SYSTEM_PROMPT, fix_message, metadata_request

API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-opus-5-5"
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
    client = client if client is not None else AnthropicClient()
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
    client = client if client is not None else AnthropicClient()
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
