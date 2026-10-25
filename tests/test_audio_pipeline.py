"""KayKit, speech and music share one pipeline; tests never call a paid provider."""

import json
import math
import re
import subprocess
from array import array
from pathlib import Path

import pytest

from src import api
from src.llm import tts
from src.ui import worker


def dialogue():
    return {
        "duration": 1.2, "render_mode": "3d", "environment": "forest", "cast": "knight_mage",
        "music": "calm", "scenes": [
            {"type": "say", "who": "robot", "shot": "wide", "text": "Наш *лес*!", "start": 0, "end": .3},
            {"type": "say", "who": "girl", "shot": "medium", "text": "Привет!", "start": .9, "end": 1.2},
        ],
    }


def ffmpeg(*args):
    return subprocess.run(
        ["ffmpeg", "-v", "error", *map(str, args)],
        capture_output=True, check=True, timeout=60,
    ).stdout


def video_hash(path):
    return ffmpeg("-i", path, "-map", "0:v:0", "-c:v", "copy", "-f", "hash", "-hash", "sha256", "-")


def level(path, start, filters):
    result = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-t", "0.1", "-i", str(path), "-vn",
         "-af", filters + ",volumedetect", "-f", "null", "-"],
        capture_output=True, check=True, text=True, encoding="utf-8", timeout=30,
    )
    return float(re.search(r"mean_volume:\s*([-\d.]+) dB", result.stderr)[1])


def test_every_music_mood_has_a_bundled_track():
    for mood in api.MUSIC_MOODS:
        track = api.pick_music(mood)
        if mood == "none":
            assert track is None
        else:
            assert track and Path(track).is_file(), f"No bundled music for {mood}"


@pytest.mark.integration
@pytest.mark.blender
def test_kaykit_voice_then_music_preserves_video_and_both_audio_sources(tmp_path):
    spec = api.parse_spec(json.dumps(dialogue()))
    video = api.render_video(spec, str(tmp_path / "kaykit.mp4"))
    original_hash = video_hash(video)
    fake = tts.FakeTTSClient(seconds=.6)
    clips = tts.synthesize_spec(spec, str(tmp_path / "voice"), fake)
    assert fake.calls == [("Наш лес!", "robot"), ("Привет!", "girl")]
    api.add_voiceover(video, clips)
    assert video_hash(video) == original_hash

    track = tmp_path / "music.wav"
    samples = array("h", (int(8000 * math.sin(2 * math.pi * 110 * i / 44100)) for i in range(22050)))
    track.write_bytes(tts.wav_bytes(samples, 44100))
    api.add_music(video, str(track))

    assert video_hash(video) == original_hash
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,duration,r_frame_rate:"
         "format=duration", "-of", "json", video],
        capture_output=True, check=True, text=True, timeout=30,
    )
    info = json.loads(probe.stdout)
    streams = {stream["codec_type"]: stream for stream in info["streams"]}
    assert streams["video"]["r_frame_rate"] == "30/1"
    assert streams["audio"]["codec_name"] == "aac"
    assert float(streams["audio"]["duration"]) == pytest.approx(1.2, abs=.05)
    assert float(info["format"]["duration"]) == pytest.approx(1.2, abs=.05)
    speech_band = "highpass=f=300,lowpass=f=600"
    assert level(video, .07, speech_band) - level(video, .55, speech_band) > 10
    assert level(video, .55, "lowpass=f=150,lowpass=f=150") > -50


def prepare_worker(monkeypatch, tmp_path, music="auto"):
    events, finished, failures = [], [], []
    output = tmp_path / "готовый.mp4"
    monkeypatch.setattr(worker.llm, "connect", lambda base_url, api_key: None)
    monkeypatch.setattr(worker.llm, "generate_spec", lambda text, client=None: json.dumps(dialogue()))
    monkeypatch.setattr(worker.RenderWorker, "_emit_metadata", lambda self, raw: None)

    def render(spec, path, *, on_progress=None):
        events.append(("render", spec.environment, spec.cast))
        Path(path).write_bytes(b"video")
        return path

    def voice(path, clips):
        events.append(("voice", len(clips)))
        Path(path).write_bytes(Path(path).read_bytes() + b"+voice")

    def pick(mood):
        events.append(("pick", mood))
        return "calm.wav"

    def mix(path, track):
        events.append(("music", track))
        assert Path(path).read_bytes() == b"video+voice"
        Path(path).write_bytes(Path(path).read_bytes() + b"+music")

    def import_track(path):
        events.append(("import", path))
        return "saved/" + Path(path).name

    # Keep an unpatched reference: worker.llm.tts and tts refer to the same module.
    synthesize_spec = tts.synthesize_spec
    monkeypatch.setattr(worker.api, "render_video", render)
    monkeypatch.setattr(worker.llm.tts, "synthesize_spec", lambda spec, directory, provider: (
        events.append(("tts", provider)) or synthesize_spec(spec, directory, tts.FakeTTSClient(seconds=.1))
    ))
    monkeypatch.setattr(worker.api, "add_voiceover", voice)
    monkeypatch.setattr(worker.api, "pick_music", pick)
    monkeypatch.setattr(worker.api, "user_music", lambda: [])
    monkeypatch.setattr(worker.api, "import_music", import_track)
    monkeypatch.setattr(worker.api, "add_music", mix)
    render_worker = worker.RenderWorker(
        "Лесная история", str(output), "3d", "elevenlabs", music=music,
        environment="forest", cast="knight_mage",
    )
    render_worker.finished.connect(finished.append)
    render_worker.failed.connect(failures.append)
    return render_worker, output, events, finished, failures


@pytest.mark.parametrize("music", ["auto", "my-music.wav"])
def test_worker_applies_voice_before_music_with_kaykit_choices(monkeypatch, tmp_path, music):
    render_worker, output, events, finished, failures = prepare_worker(monkeypatch, tmp_path, music)
    render_worker.run()
    expected = [("render", "forest", "knight_mage"), ("tts", "elevenlabs"), ("voice", 2)]
    if music == "auto":
        expected += [("pick", "calm")]
    else:
        expected += [("import", music)]
    expected += [("music", "calm.wav" if music == "auto" else "saved/" + music)]
    assert events == expected
    assert output.read_bytes() == b"video+voice+music"
    assert finished == [str(output)] and not failures


@pytest.mark.parametrize("stage", ["provider", "voice", "import", "music"])
def test_worker_audio_failure_keeps_the_completed_video(monkeypatch, tmp_path, stage):
    render_worker, output, _, finished, failures = prepare_worker(
        monkeypatch, tmp_path, music="custom.wav" if stage == "import" else "auto",
    )

    def fail(*args):
        raise tts.TTSError("no voice") if stage == "provider" else api.RenderError("broken audio")

    if stage == "provider":
        monkeypatch.setattr(worker.llm.tts, "synthesize_spec", fail)
    else:
        target = {"voice": "add_voiceover", "import": "import_music", "music": "add_music"}[stage]
        monkeypatch.setattr(worker.api, target, fail)
    render_worker.run()
    assert output.read_bytes() == (b"video+voice" if stage in ("import", "music") else b"video")
    assert len(failures) == 1 and str(output) in failures[0]
    assert not finished


def test_cancellation_during_tts_keeps_video_without_starting_audio_mix(monkeypatch, tmp_path):
    render_worker, output, events, finished, failures = prepare_worker(monkeypatch, tmp_path)
    cancelled = []
    render_worker.cancelled.connect(lambda: cancelled.append(True))
    synthesize = worker.llm.tts.synthesize_spec

    def cancel_after_synthesis(*args):
        clips = synthesize(*args)
        render_worker.cancel()
        return clips

    monkeypatch.setattr(worker.llm.tts, "synthesize_spec", cancel_after_synthesis)
    render_worker.run()
    assert events == [("render", "forest", "knight_mage"), ("tts", "elevenlabs")]
    assert output.read_bytes() == b"video"
    assert cancelled == [True]
    assert not finished and not failures


def test_cancellation_during_music_does_not_emit_success(monkeypatch, tmp_path):
    render_worker, output, _, finished, failures = prepare_worker(monkeypatch, tmp_path)
    cancelled = []
    render_worker.cancelled.connect(lambda: cancelled.append(True))
    mix = worker.api.add_music

    def cancel_after_mix(*args):
        mix(*args)
        render_worker.cancel()

    monkeypatch.setattr(worker.api, "add_music", cancel_after_mix)
    render_worker.run()
    assert output.read_bytes() == b"video+voice+music"
    assert cancelled == [True]
    assert not finished and not failures
