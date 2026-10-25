"""Installed speech uses the bundled Python worker, without network or PyTorch in tests."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import parse_spec
from src.llm import tts
from src.llm.chatterbox_worker import lazy_chinese


@pytest.fixture
def installed(monkeypatch, tmp_path):
    monkeypatch.setattr(tts.sys, "frozen", True, raising=False)
    monkeypatch.setattr(tts.sys, "executable", str(tmp_path / "ShortsStudio.exe"))
    runtime = tmp_path / "voice-runtime"
    runtime.mkdir()
    (runtime / "python.exe").touch()
    return tmp_path


def test_installed_chatterbox_synthesizes_all_lines_in_one_worker(installed, monkeypatch, tmp_path):
    spec = parse_spec(json.dumps({"duration": 2, "render_mode": "3d", "scenes": [
        {"type": "text", "text": "Привет", "start": 0, "end": 1},
        {"type": "say", "who": "girl", "shot": "close", "text": "*Мир*!", "start": 1, "end": 2},
    ]}))
    calls = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-key")
    monkeypatch.setenv("CHATTERBOX_VOICE_GIRL", "reference.wav")

    def worker(command, **options):
        calls.append((command, options))
        request = json.loads(options["input"])
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            {"path": str(Path(request["out_dir"]) / f"{i}.wav"), "start": line["start"], "end": line["end"]}
            for i, line in enumerate(request["lines"])
        ]))

    monkeypatch.setattr(tts.subprocess, "run", worker)
    clips = tts.synthesize_spec(spec, str(tmp_path / "speech"), "chatterbox")
    assert [(clip.start, clip.end) for clip in clips] == [(0, 1), (1, 2)]
    assert len(calls) == 1
    command, options = calls[0]
    assert command[0] == str(installed / "voice-runtime" / "python.exe")
    request = json.loads(options["input"])
    assert [line["text"] for line in request["lines"]] == ["Привет", "Мир!"]
    assert request["model_dir"] == str(installed / "voice-models")
    assert request["voices"]["girl"] == "reference.wav"
    assert options["env"]["HF_HUB_OFFLINE"] == "1"
    assert "DEEPSEEK_API_KEY" not in options["env"]


def test_installed_worker_failure_is_readable(installed, monkeypatch, tmp_path):
    spec = parse_spec('{"duration":1,"scenes":[{"type":"text","text":"Hi","start":0,"end":1}]}')
    monkeypatch.setattr(tts.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="Model files missing",
    ))
    with pytest.raises(tts.TTSError, match="Model files missing"):
        tts.synthesize_spec(spec, str(tmp_path / "voice"), "chatterbox")


def test_missing_installed_voice_points_to_setup(monkeypatch):
    monkeypatch.setattr(tts.sys, "frozen", True, raising=False)
    monkeypatch.setitem(tts.sys.modules, "chatterbox", None)
    with pytest.raises(tts.TTSError, match="ShortsStudio Setup"):
        tts.ChatterboxClient()


def test_chinese_segmenter_initializes_only_when_chinese_is_used():
    calls = []

    class Converter:
        def __init__(self, model_dir):
            calls.append(model_dir)

        def __call__(self, text):
            return text + " converted"

    module = SimpleNamespace(ChineseCangjieConverter=Converter)
    lazy_chinese(module)
    converter = module.ChineseCangjieConverter("models")
    assert calls == []
    assert converter("text") == "text converted"
    assert converter("again") == "again converted"
    assert calls == ["models"]
