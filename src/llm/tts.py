"""Voice-over: scene text -> speech files via ElevenLabs. Tests use FakeTTSClient."""

from __future__ import annotations

import io
import json
import math
import os
import urllib.error
import urllib.request
import wave
from array import array
from dataclasses import dataclass
from typing import Optional, Protocol

API_KEY_ENV = "ELEVENLABS_API_KEY"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
MODEL_ID = "eleven_multilingual_v2"  # speaks Russian
# Premade ElevenLabs voices; override with ELEVENLABS_VOICE_NARRATOR / _ROBOT / _GIRL.
DEFAULT_VOICES = {
    "narrator": "pNInz6obpgDQGcFmaJgB",  # Adam
    "robot": "VR6AewLTigWG4xSOukaG",  # Arnold
    "girl": "21m00Tcm4TlvDq8ikWAM",  # Rachel
}


class TTSError(Exception):
    """Speech could not be generated: missing key, network, API error."""


@dataclass(frozen=True)
class VoiceClip:
    """Speech for one scene: plays from start, cut at end (seconds)."""

    path: str
    start: float
    end: float


class TTSClient(Protocol):
    suffix: str  # audio file extension, e.g. ".mp3"

    def synthesize(self, text: str, voice_id: str) -> bytes:
        """Return encoded audio of text spoken by voice_id."""
        ...


class ElevenLabsClient:
    """ElevenLabs text-to-speech over HTTPS. The key is read from ELEVENLABS_API_KEY."""

    suffix = ".mp3"

    def __init__(self, timeout: float = 60.0):
        self._key = os.environ.get(API_KEY_ENV)
        if not self._key:
            raise TTSError(f"Не задан ключ ElevenLabs: установите переменную окружения {API_KEY_ENV}.")
        self._timeout = timeout

    def synthesize(self, text: str, voice_id: str) -> bytes:
        request = urllib.request.Request(
            API_URL.format(voice_id=voice_id),
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


class FakeTTSClient:
    """Offline client for tests: a quiet tone of fixed length instead of speech."""

    suffix = ".wav"

    def __init__(self, seconds: float = 1.0, rate: int = 22050):
        self.seconds, self.rate = seconds, rate
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, voice_id: str) -> bytes:
        self.calls.append((text, voice_id))
        n = round(self.seconds * self.rate)
        samples = array("h", (int(3000 * math.sin(2 * math.pi * 440 * i / self.rate)) for i in range(n)))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(samples.tobytes())
        return buf.getvalue()


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


def synthesize_spec(spec, out_dir: str, client: Optional[TTSClient] = None) -> list[VoiceClip]:
    """Generate one audio file per spoken scene of a parsed Spec into out_dir."""
    client = client if client is not None else ElevenLabsClient()
    os.makedirs(out_dir, exist_ok=True)
    clips = []
    for i, (text, role, start, end) in enumerate(voice_lines(spec)):
        path = os.path.join(out_dir, f"voice_{i:03d}{client.suffix}")
        with open(path, "wb") as f:
            f.write(client.synthesize(text, voice_id(role)))
        clips.append(VoiceClip(path, start, end))
    return clips
