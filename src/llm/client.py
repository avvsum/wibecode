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

BASE_URL_ENV = "WIBECODE_LLM_BASE_URL"
API_KEY_ENV = "WIBECODE_LLM_API_KEY"
# Старые настройки DeepSeek используются, когда общий адрес и ключ не заданы.
DEEPSEEK_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
DEEPSEEK_MODEL_ENV = "DEEPSEEK_MODEL"
DEEPSEEK_URL = "https://api.deepseek.com"
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


# Model ids that are not chat models: embeddings, speech, images, moderation.
_NOT_CHAT = re.compile(
    r"embed|whisper|tts|transcri|speech|audio|realtime|dall-e|image|moderation|rerank|guard",
    re.IGNORECASE,
)
_SMALL = re.compile(r"mini|nano|small|lite|tiny|haiku", re.IGNORECASE)
_PARAMS = re.compile(r"(\d+(?:\.\d+)?)b(?![a-z])", re.IGNORECASE)


def rank_models(models: list[dict]) -> list[str]:
    """Chat model ids from GET /models, most capable first.

    No list of known names to go stale: full-size models before mini/lite ones,
    then by parameter count in the id (70b > 8b), then the newest by "created".
    """

    def score(model: dict) -> tuple:
        name = str(model["id"]).rsplit("/", 1)[-1]
        sizes = [float(n) for n in _PARAMS.findall(name)]
        return (not _SMALL.search(name), max(sizes, default=0), model.get("created") or 0)

    chat = [m for m in models if m.get("id") and not _NOT_CHAT.search(str(m["id"]))]
    return [str(m["id"]) for m in sorted(chat, key=score, reverse=True)]


class OpenAICompatibleClient:
    """Any OpenAI-compatible API (POST /chat/completions) at the user's base URL.

    The model is chosen automatically from GET /models on the first request; if
    the provider rejects it, the next one in rank_models order is tried.
    Legacy DeepSeek settings may pin a model with DEEPSEEK_MODEL.
    Base URL and key come from the window or WIBECODE_LLM_BASE_URL / WIBECODE_LLM_API_KEY.
    """

    def __init__(self, base_url: str = "", api_key: str = "", timeout: float = 180.0):
        base_url = (base_url or os.environ.get(BASE_URL_ENV, "")).strip()
        self._key = (api_key or os.environ.get(API_KEY_ENV, "")).strip()
        deepseek_model = ""
        if not base_url and not self._key and os.environ.get(DEEPSEEK_KEY_ENV):
            base_url = os.environ.get(DEEPSEEK_BASE_URL_ENV, "").strip() or DEEPSEEK_URL
            self._key = os.environ[DEEPSEEK_KEY_ENV].strip()
            deepseek_model = os.environ.get(DEEPSEEK_MODEL_ENV, "").strip()
        if not base_url:
            raise LLMError(
                "Не указан адрес API нейросети: впишите его в «Дополнительно» "
                f"или в переменную окружения {BASE_URL_ENV}."
            )
        if not self._key:
            raise LLMError(
                "Не указан ключ API нейросети: впишите его в «Дополнительно» "
                f"или в переменную окружения {API_KEY_ENV}."
            )
        if not re.match(r"https?://", base_url):
            base_url = "https://" + base_url
        self._base = base_url.rstrip("/").removesuffix("/chat/completions").removesuffix("/models")
        self._timeout = timeout
        self._models: Optional[list[str]] = [deepseek_model] if deepseek_model else None

    @property
    def model(self) -> Optional[str]:
        """The selected model id, or None before automatic discovery."""
        return self._models[0] if self._models else None

    def _request(self, path: str, body: Optional[dict] = None) -> dict:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(
            self._base + path, data=data, method="GET" if body is None else "POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise _http_error(e.code, e.read().decode("utf-8", "replace")) from e
        except (urllib.error.URLError, OSError) as e:
            raise LLMError(f"Нет соединения с {self._base}: проверьте адрес API и интернет.") from e
        except ValueError as e:  # not JSON: usually a web page instead of an API
            raise LLMError(f"По адресу {self._base} отвечает не API нейросети, проверьте адрес.") from e

    def _list_models(self) -> list[str]:
        try:
            listing = self._request("/models")
        except _HTTPError as e:
            if e.status != 404 or self._base.endswith("/v1"):
                raise
            self._base += "/v1"  # «https://api.example.com» без /v1
            listing = self._request("/models")
        entries = listing.get("data", listing.get("models", [])) if isinstance(listing, dict) else []
        models = rank_models([m for m in entries if isinstance(m, dict)])
        if not models:
            raise LLMError(f"API {self._base} не вернул ни одной текстовой модели.")
        return models

    def complete(self, system: str, messages: list[Message]) -> str:
        if self._models is None:
            self._models = self._list_models()
        while True:
            body = {"model": self._models[0], "messages": [{"role": "system", "content": system}, *messages]}
            try:
                response = self._request("/chat/completions", body)
            except _HTTPError as e:
                # Not a chat model or not available on this key: try the next one.
                if e.status in (400, 403, 404, 422) and "model" in e.detail.lower() and len(self._models) > 1:
                    self._models.pop(0)
                    continue
                raise
            break
        try:
            choice = response["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError("API вернул ответ без текста модели.") from e
        if choice.get("finish_reason") == "content_filter":
            raise LLMError("Модель отказалась отвечать на этот запрос, переформулируйте описание.")
        if isinstance(content, list):  # [{"type": "text", "text": ...}]
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content


class _HTTPError(LLMError):
    def __init__(self, status: int, message: str, detail: str):
        super().__init__(message)
        self.status, self.detail = status, detail


def _http_error(status: int, text: str) -> _HTTPError:
    try:
        error = json.loads(text).get("error", {})
        detail = error.get("message", "") if isinstance(error, dict) else str(error)
    except (ValueError, AttributeError):
        detail = ""
    detail = detail or text.strip()[:300]
    if status in (401, 403) and "model" not in detail.lower():
        message = "Неверный ключ API нейросети или нет доступа."
    elif status == 402:
        message = "На балансе API нейросети закончились средства, пополните счёт."
    elif status == 429:
        message = "Превышен лимит запросов к API нейросети, попробуйте позже."
    else:
        message = f"Ошибка API нейросети ({status}): {detail}"
    return _HTTPError(status, message, detail)


def connect(base_url: str = "", api_key: str = "") -> OpenAICompatibleClient:
    """Client for the user's API; the model is picked on the first request."""
    return OpenAICompatibleClient(base_url, api_key)


def default_client() -> LLMClient:
    """Client from environment variables, for generate_spec without client= (scripts, tests)."""
    return OpenAICompatibleClient()


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
