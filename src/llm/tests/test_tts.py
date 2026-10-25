"""Offline tests for src/llm/tts: FakeTTSClient and a mocked urlopen, no network."""

import io
import json
import sys
import types
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
        ("Итоги года", "narrator"),
        ("Привет, мир!", "girl"),  # *keyword* marks are not spoken
        ("Пока", "robot"),
    ]
    for clip in clips:
        assert clip.path.endswith(".wav")
        with wave.open(clip.path) as w:
            assert w.getnframes() / w.getframerate() == pytest.approx(0.5)


def test_elevenlabs_voice_ids_can_be_overridden(monkeypatch):
    assert tts.voice_id("girl") == tts.DEFAULT_VOICES["girl"]
    monkeypatch.setenv("ELEVENLABS_VOICE_GIRL", "my-girl-voice")
    assert tts.voice_id("girl") == "my-girl-voice"


def test_unknown_provider_is_clear_error(tmp_path):
    with pytest.raises(tts.TTSError, match="elevenlabs, chatterbox"):
        tts.synthesize_spec(SPEC_3D, str(tmp_path), "nope")


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
    monkeypatch.setenv("ELEVENLABS_VOICE_GIRL", "voice-1")
    audio = tts.ElevenLabsClient().synthesize("Привет", "girl")

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
        tts.ElevenLabsClient().synthesize("Привет", "girl")


class FakeWave:
    """Stands in for the torch tensor Chatterbox returns: shape (1, samples)."""

    def __init__(self, values):
        self.values = values

    def squeeze(self, dim):
        return self

    def tolist(self):
        return self.values


@pytest.fixture
def chatterbox(monkeypatch):
    """Fake chatterbox.mtl_tts module: records calls, no torch, no model download."""
    calls = []

    class Model:
        sr = 24000
        conds = "builtin"

        @classmethod
        def from_pretrained(cls, device):
            calls.append(("load", device))
            return cls()

        def generate(self, text, language_id, audio_prompt_path=None, exaggeration=0.5):
            calls.append((text, language_id, audio_prompt_path, exaggeration, self.conds))
            if audio_prompt_path:
                self.conds = audio_prompt_path  # like the real model: reference replaces conds
            return FakeWave([0.0, 0.5, -2.0])

    package = types.ModuleType("chatterbox")
    module = types.ModuleType("chatterbox.mtl_tts")
    module.ChatterboxMultilingualTTS = Model
    monkeypatch.setitem(sys.modules, "chatterbox", package)
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", module)
    return calls


def test_chatterbox_voices_spec_locally(chatterbox, monkeypatch, tmp_path):
    reference = tmp_path / "girl.wav"
    reference.write_bytes(b"RIFF")
    monkeypatch.setenv("CHATTERBOX_VOICE_GIRL", str(reference))

    client = tts.ChatterboxClient(device="cpu")
    clips = tts.synthesize_spec(SPEC_3D, str(tmp_path / "out"), client)

    assert chatterbox == [
        ("load", "cpu"),
        ("Итоги года", "ru", None, 0.5, "builtin"),
        ("Привет, мир!", "ru", str(reference), 0.7, "builtin"),
        # The robot has no reference: back to the built-in voice, not the girl's.
        ("Пока", "ru", None, 0.3, "builtin"),
    ]
    with wave.open(clips[0].path) as w:
        assert w.getframerate() == 24000
        assert list(memoryview(w.readframes(3)).cast("h")) == [0, 16384, -32767]  # clipped


def test_chatterbox_language_follows_text(chatterbox):
    tts.ChatterboxClient(device="cpu").synthesize("Hello there", "narrator")
    assert chatterbox[-1][1] == "en"


def test_chatterbox_missing_reference_is_clear_error(chatterbox, monkeypatch):
    monkeypatch.setenv("CHATTERBOX_VOICE_ROBOT", "/nope/robot.wav")
    with pytest.raises(tts.TTSError, match="не найден"):
        tts.ChatterboxClient(device="cpu").synthesize("Пока", "robot")


def test_chatterbox_not_installed_is_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "chatterbox", None)  # import raises ImportError
    with pytest.raises(tts.TTSError, match="requirements-chatterbox.txt"):
        tts.ChatterboxClient()
