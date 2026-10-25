"""Offline tests for src/llm/tts: FakeTTSClient and a mocked urlopen, no network."""

import io
import json
import urllib.error
import wave

import pytest

from src.api import parse_spec
from src.llm import tts

SPEC_3D = parse_spec(
    json.dumps(
        {
            "duration": 6,
            "render_mode": "3d",
            "scenes": [
                {"type": "say", "who": "girl", "shot": "close", "text": "Привет, *мир*!", "start": 2, "end": 4},
                {"type": "text", "text": "Итоги года", "start": 0, "end": 2},
                {"type": "chart", "data": [[1, 2], [2, 3]], "start": 4, "end": 5},
                {"type": "say", "who": "robot", "shot": "wide", "text": "Пока", "start": 5, "end": 6},
            ],
        },
        ensure_ascii=False,
    )
)


def test_text_is_narrated_and_say_is_acted_in_order(tmp_path):
    fake = tts.FakeTTSClient(seconds=0.5)
    clips = tts.synthesize_spec(SPEC_3D, str(tmp_path), fake)

    assert [(c.start, c.end) for c in clips] == [(0, 2), (2, 4), (5, 6)]
    assert fake.calls == [
        ("Итоги года", tts.DEFAULT_VOICES["narrator"]),
        ("Привет, мир!", tts.DEFAULT_VOICES["girl"]),  # *keyword* marks are not spoken
        ("Пока", tts.DEFAULT_VOICES["robot"]),
    ]
    for clip in clips:
        assert clip.path.endswith(".wav")
        with wave.open(clip.path) as w:
            assert w.getnframes() / w.getframerate() == pytest.approx(0.5)


def test_voice_ids_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_VOICE_GIRL", "my-girl-voice")
    fake = tts.FakeTTSClient()
    tts.synthesize_spec(SPEC_3D, str(tmp_path), fake)
    assert fake.calls[1][1] == "my-girl-voice"


def test_missing_key_is_clear_error():
    with pytest.raises(tts.TTSError, match="ELEVENLABS_API_KEY"):
        tts.ElevenLabsClient()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_elevenlabs_request(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        return FakeResponse(b"ID3 mp3 bytes")

    monkeypatch.setattr(tts.urllib.request, "urlopen", urlopen)
    audio = tts.ElevenLabsClient().synthesize("Привет", "voice-1")

    assert audio == b"ID3 mp3 bytes"
    (request,) = sent
    assert request.full_url.startswith("https://api.elevenlabs.io/v1/text-to-speech/voice-1")
    assert request.get_method() == "POST"
    assert request.get_header("Xi-api-key") == "test-key"
    assert json.loads(request.data) == {"text": "Привет", "model_id": tts.MODEL_ID}


@pytest.mark.parametrize(
    "error, message",
    [
        (urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"")), "Неверный ключ"),
        (urllib.error.HTTPError("u", 429, "Too Many", {}, io.BytesIO(b"")), "лимит"),
        (urllib.error.URLError("offline"), "Нет соединения"),
    ],
)
def test_elevenlabs_errors_are_readable(monkeypatch, error, message):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(tts.urllib.request, "urlopen", urlopen)
    with pytest.raises(tts.TTSError, match=message):
        tts.ElevenLabsClient().synthesize("Привет", "voice-1")
