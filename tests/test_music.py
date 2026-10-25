import json
import math
import random
import shutil
import subprocess
from array import array

import pytest

from src.core import music
from src.llm import tts

AUDIO_ONLY_SPEC = {"duration": 6, "scenes": [
    {"type": "text", "text": "Привет", "start": 0, "end": 3},
    {"type": "chart", "data": [[1, 2], [2, 4]], "start": 3, "end": 6},
]}  # fmt: skip


def tone(path, seconds, freq, amplitude=8000, rate=44100):
    n = round(seconds * rate)
    samples = array("h", (int(amplitude * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))
    path.write_bytes(tts.wav_bytes(samples, rate))
    return str(path)


def need_ffmpeg():
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            pytest.fail(f"Для integration необходим {executable} в PATH", pytrace=False)


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,duration,"
         "r_frame_rate", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    return json.loads(result.stdout)


def bass_level(path, start, length=1):
    """Mean level of the 110 Hz test "music": steep low-pass removes the 440 Hz test voice."""
    result = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", str(path), "-vn",
         "-af", "lowpass=150," * 4 + "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    line = next(x for x in result.stderr.splitlines() if "mean_volume" in x)
    return float(line.split("mean_volume:")[1].split()[0])


def test_music_mood_is_optional_and_validated(api):
    raw = json.dumps(AUDIO_ONLY_SPEC, ensure_ascii=False)
    assert api.parse_spec(raw).music == "none"
    assert api.parse_spec(json.dumps({**AUDIO_ONLY_SPEC, "music": "lofi"})).music == "lofi"
    with pytest.raises(api.SpecError, match="неизвестный music 'jazz', допустимы: none, calm"):
        api.parse_spec(json.dumps({**AUDIO_ONLY_SPEC, "music": "jazz"}))


def test_pick_track_uses_mood_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(music, "bundled_dir", lambda: tmp_path)
    (tmp_path / "lofi").mkdir()
    for name in ("b.mp3", "a.WAV", "notes.txt"):
        (tmp_path / "lofi" / name).write_bytes(b"")

    assert music.bundled_tracks("lofi") == [str(tmp_path / "lofi" / "a.WAV"),
                                            str(tmp_path / "lofi" / "b.mp3")]  # fmt: skip
    assert music.pick_track("lofi", random.Random(1)) in music.bundled_tracks("lofi")
    assert music.pick_track("epic") is None  # no tracks for this mood: video stays silent
    assert music.pick_track("none") is None


def test_bundled_tracks_are_readable():
    for mood in music.bundled_dir().iterdir() if music.bundled_dir().is_dir() else []:
        for track in music.bundled_tracks(mood.name):
            duration, has_audio = music._probe(track)
            assert has_audio and duration > 0, track


@pytest.mark.integration
def test_import_track_copies_into_user_folder(tmp_path):
    need_ffmpeg()
    source = tone(tmp_path / "Моя песня.wav", 0.5, 220)

    first, second = music.import_track(source), music.import_track(source)

    assert set(music.user_tracks()) == {first, second}
    assert first.endswith("Моя песня.wav") and second.endswith("Моя песня (2).wav")
    with pytest.raises(music.RenderError, match="неподдерживаемый формат"):
        music.import_track(str(tmp_path / "notes.txt"))
    fake = tmp_path / "broken.mp3"
    fake.write_bytes(b"not audio")
    with pytest.raises(music.RenderError):
        music.import_track(str(fake))
    assert len(music.user_tracks()) == 2


@pytest.mark.integration
def test_music_loops_to_video_length(api, tmp_path):
    need_ffmpeg()
    video = api.render_video(api.parse_spec(json.dumps(AUDIO_ONLY_SPEC)), str(tmp_path / "v.mp4"))
    track = tone(tmp_path / "short.wav", 2, 110)  # shorter than the 6 s video

    assert api.add_music(video, track) == video

    metadata = probe(video)
    streams = {s["codec_type"]: s for s in metadata["streams"]}
    assert float(metadata["format"]["duration"]) == pytest.approx(6, abs=0.1)
    assert float(streams["audio"]["duration"]) == pytest.approx(6, abs=0.1)
    assert bass_level(video, 4) > -40  # still playing after the 2 s track ran out


@pytest.mark.integration
def test_music_ducks_under_speech(api, tmp_path):
    need_ffmpeg()
    spec = api.parse_spec(json.dumps(AUDIO_ONLY_SPEC))
    video = api.render_video(spec, str(tmp_path / "v.mp4"))
    speech = tts.synthesize_spec(spec, str(tmp_path / "voice"), tts.FakeTTSClient(seconds=3))
    api.add_voiceover(video, speech)  # 440 Hz "speech" during the first scene, 0-3 s

    api.add_music(video, tone(tmp_path / "bass.wav", 6, 110))

    under_speech, alone = bass_level(video, 1.5), bass_level(video, 4)
    assert alone - under_speech > 5  # music dips while someone speaks
    assert float(probe(video)["format"]["duration"]) == pytest.approx(6, abs=0.1)


def test_missing_track_keeps_video(api, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"original")
    with pytest.raises(api.RenderError, match="не найден"):
        api.add_music(str(video), str(tmp_path / "nope.mp3"))
    assert video.read_bytes() == b"original"
