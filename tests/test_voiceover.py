import json
import shutil
import subprocess
from fractions import Fraction

import pytest

from src.llm import tts


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,r_frame_rate,width,height",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    return json.loads(result.stdout)


def loudness(path, start, length):
    """Max volume in dB of the audio between start and start + length seconds."""
    result = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", str(path),
         "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    line = next(x for x in result.stderr.splitlines() if "max_volume" in x)
    return float(line.split("max_volume:")[1].split()[0])


def integrated_loudness(path):
    """EBU R128 integrated loudness of the whole audio track in LUFS."""
    result = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    line = [x for x in result.stderr.splitlines() if x.strip().startswith("I:")][-1]
    return float(line.split()[1])


@pytest.mark.integration
def test_voiceover_adds_audio_cut_at_scene_end(api, tmp_path):
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            pytest.fail(f"Для integration необходим {executable} в PATH", pytrace=False)
    spec = api.parse_spec(json.dumps({"duration": 3, "scenes": [
        {"type": "text", "text": "Привет", "start": 0, "end": 1},
        {"type": "chart", "data": [[1, 2], [2, 4]], "start": 1, "end": 2},
        {"type": "text", "text": "Пока", "start": 2, "end": 3},
    ]}, ensure_ascii=False))  # fmt: skip
    video = api.render_video(spec, str(tmp_path / "ролик.mp4"))
    # Fake speech is longer than its 1 s scene: it must be cut at the scene end.
    clips = tts.synthesize_spec(spec, str(tmp_path / "voice"), tts.FakeTTSClient(seconds=1.6))

    assert api.add_voiceover(video, clips) == video

    metadata = probe(video)
    streams = {s["codec_type"]: s for s in metadata["streams"]}
    assert streams["audio"]["codec_name"] == "aac"
    assert (streams["video"]["width"], streams["video"]["height"]) == (1080, 1920)
    assert Fraction(streams["video"]["r_frame_rate"]) == 60
    assert float(metadata["format"]["duration"]) == pytest.approx(3, abs=0.1)
    assert loudness(video, 0.2, 0.6) > -40  # first line is heard
    assert loudness(video, 1.2, 0.6) < -60  # chart scene is silent
    # The quiet fake tone (about -24 LUFS) is levelled towards YouTube's -14 LUFS.
    assert -17 < integrated_loudness(video) < -11


def test_missing_voice_file_keeps_video(api, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"original")
    with pytest.raises(api.RenderError, match="не найден"):
        api.add_voiceover(str(video), [tts.VoiceClip(str(tmp_path / "nope.mp3"), 0, 1)])
    assert video.read_bytes() == b"original"
