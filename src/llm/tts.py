"""Voice-over: scene text -> speech files.

Providers: ElevenLabs (cloud, needs a key) and Chatterbox (local model, free,
optional install). Tests use FakeTTSClient.
"""

from __future__ import annotations

import io
import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.request
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Union

API_KEY_ENV = "ELEVENLABS_API_KEY"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
MODEL_ID = "eleven_multilingual_v2"  # speaks Russian
# Premade ElevenLabs voices; override with ELEVENLABS_VOICE_NARRATOR / _ROBOT / _GIRL.
DEFAULT_VOICES = {
    "narrator": "pNInz6obpgDQGcFmaJgB",  # Adam
    "robot": "VR6AewLTigWG4xSOukaG",  # Arnold
    "girl": "21m00Tcm4TlvDq8ikWAM",  # Rachel
}


CHATTERBOX_INSTALL = "pip install -r requirements-chatterbox.txt"
# Chatterbox speaks with its built-in voice unless CHATTERBOX_VOICE_<ROLE> points
# to a 5-10 s reference .wav to clone; emotion strength differs per role.
CHATTERBOX_EXAGGERATION = {"narrator": 0.5, "robot": 0.3, "girl": 0.7}


class TTSError(Exception):
    """Speech could not be generated: missing key or package, network, API error."""


@dataclass(frozen=True)
class VoiceClip:
    """Speech for one scene: plays from start, cut at end (seconds)."""

    path: str
    start: float
    end: float


class TTSClient(Protocol):
    suffix: str  # audio file extension, e.g. ".mp3"

    def synthesize(self, text: str, role: str) -> bytes:
        """Return encoded audio of text spoken by role: "narrator" or a say who."""
        ...


class ElevenLabsClient:
    """ElevenLabs text-to-speech over HTTPS. The key is read from ELEVENLABS_API_KEY."""

    suffix = ".mp3"

    def __init__(self, timeout: float = 60.0):
        self._key = os.environ.get(API_KEY_ENV)
        if not self._key:
            raise TTSError(f"Не задан ключ ElevenLabs: установите переменную окружения {API_KEY_ENV}.")
        self._timeout = timeout

    def synthesize(self, text: str, role: str) -> bytes:
        request = urllib.request.Request(
            API_URL.format(voice_id=voice_id(role)),
            data=json.dumps({"text": text, "model_id": MODEL_ID}).encode("utf-8"),
            headers={
                "xi-api-key": self._key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                raise TTSError(f"Неверный ключ ElevenLabs ({API_KEY_ENV}).") from e
            if e.code == 429:
                raise TTSError("ElevenLabs: превышен лимит запросов или символов.") from e
            raise TTSError(f"Ошибка ElevenLabs ({e.code}): {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise TTSError("Нет соединения с ElevenLabs, проверьте интернет.") from e


class ChatterboxClient:
    """Resemble AI Chatterbox (multilingual) on this computer: no key, no per-use cost.

    The first run downloads the model (several GB) from Hugging Face; without a
    GPU speech is generated slower than real time.
    """

    suffix = ".wav"

    def __init__(self, device: Optional[str] = None):
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError as e:
            help_text = ("запустите ShortsStudio Setup и установите локальную озвучку"
                         if getattr(sys, "frozen", False) else CHATTERBOX_INSTALL)
            raise TTSError(f"Chatterbox не установлен: {help_text}") from e
        if device is None:
            import torch

            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        try:
            self._model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        except Exception as e:  # download or checkpoint errors from torch/huggingface
            raise TTSError(f"Не удалось загрузить модель Chatterbox: {e}") from e
        self._builtin = self._model.conds  # a reference voice replaces conds in generate

    def synthesize(self, text: str, role: str) -> bytes:
        prompt = os.environ.get(f"CHATTERBOX_VOICE_{role.upper()}")
        if prompt and not os.path.isfile(prompt):
            raise TTSError(f"Файл голоса Chatterbox не найден: {prompt}")
        if not prompt:
            self._model.conds = self._builtin
        try:
            wav = self._model.generate(
                text,
                language_id=os.environ.get("CHATTERBOX_LANGUAGE") or language_of(text),
                audio_prompt_path=prompt or None,
                exaggeration=CHATTERBOX_EXAGGERATION[role],
            )
        except Exception as e:  # model errors surface as many torch exception types
            raise TTSError(f"Chatterbox не смог озвучить реплику: {e}") from e
        samples = array("h", (round(max(-1.0, min(1.0, x)) * 32767) for x in wav.squeeze(0).tolist()))
        return wav_bytes(samples, self._model.sr)


class FakeTTSClient:
    """Offline client for tests: a quiet tone of fixed length instead of speech."""

    suffix = ".wav"

    def __init__(self, seconds: float = 1.0, rate: int = 22050):
        self.seconds, self.rate = seconds, rate
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, role: str) -> bytes:
        self.calls.append((text, role))
        n = round(self.seconds * self.rate)
        samples = array("h", (int(3000 * math.sin(2 * math.pi * 440 * i / self.rate)) for i in range(n)))
        return wav_bytes(samples, self.rate)


PROVIDERS = {"elevenlabs": ElevenLabsClient, "chatterbox": ChatterboxClient}


def make_client(provider: str) -> TTSClient:
    """Client by name: "elevenlabs" or "chatterbox"."""
    try:
        return PROVIDERS[provider]()
    except KeyError:
        raise TTSError(f"Неизвестный провайдер озвучки {provider!r}: {', '.join(PROVIDERS)}") from None


def wav_bytes(samples: array, rate: int) -> bytes:
    """16-bit mono WAV file contents."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def language_of(text: str) -> str:
    """Chatterbox language id: Russian if the text has Cyrillic, else English."""
    return "ru" if any("а" <= ch.lower() <= "я" or ch in "ёЁ" for ch in text) else "en"


def voice_id(role: str) -> str:
    """ElevenLabs voice for a role: "narrator" or a say-scene who."""
    return os.environ.get(f"ELEVENLABS_VOICE_{role.upper()}") or DEFAULT_VOICES[role]


def voice_lines(spec) -> list[tuple[str, str, float, float]]:
    """(text, role, start, end) for every spoken scene: text is narrated, say is acted."""
    lines = []
    for scene in sorted(spec.scenes, key=lambda s: s.start):
        if scene.type == "text":
            lines.append((scene.text, "narrator", scene.start, scene.end))
        elif scene.type == "say":
            lines.append((scene.text.replace("*", ""), scene.who, scene.start, scene.end))
    return lines


def synthesize_spec(
    spec, out_dir: str, client: Union[TTSClient, str, None] = None
) -> list[VoiceClip]:
    """Generate one audio file per spoken scene of a parsed Spec into out_dir.

    client is a TTSClient or a provider name (default "elevenlabs").
    """
    if client == "chatterbox":
        root = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[2] / "build")
        python = root / "voice-runtime" / "python.exe"
        if python.is_file():
            return _external_chatterbox(spec, out_dir, root, python)
    if client is None or isinstance(client, str):
        client = make_client(client or "elevenlabs")
    os.makedirs(out_dir, exist_ok=True)
    clips = []
    for i, (text, role, start, end) in enumerate(voice_lines(spec)):
        path = os.path.join(out_dir, f"voice_{i:03d}{client.suffix}")
        with open(path, "wb") as f:
            f.write(client.synthesize(text, role))
        clips.append(VoiceClip(path, start, end))
    return clips


def _external_chatterbox(spec, out_dir, root, python):
    lines = [{"text": text, "role": role, "start": start, "end": end}
             for text, role, start, end in voice_lines(spec)]
    if not lines:
        return []
    request = {"model_dir": str(root / "voice-models"),
               "out_dir": str(Path(out_dir).resolve()), "lines": lines,
               "voices": {role: os.environ.get(f"CHATTERBOX_VOICE_{role.upper()}")
                          for role in CHATTERBOX_EXAGGERATION},
               "language": os.environ.get("CHATTERBOX_LANGUAGE")}
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    for name in ("PYTHONHOME", "PYTHONPATH", "DEEPSEEK_API_KEY", "WIBECODE_LLM_API_KEY",
                 "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY"):
        environment.pop(name, None)
    try:
        result = subprocess.run(
            [str(python), "-X", "utf8", str(Path(__file__).with_name("chatterbox_worker.py"))],
            input=json.dumps(request, ensure_ascii=False), capture_output=True, text=True,
            encoding="utf-8", env=environment, timeout=1800,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise TTSError(f"Локальная озвучка Chatterbox не удалась: {result.stderr[-800:].strip()}")
        return [VoiceClip(**clip) for clip in json.loads(result.stdout)]
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        raise TTSError(f"Не удалось запустить локальную озвучку Chatterbox: {error}") from error
