"""Background music: a track library (bundled by mood + the user's own) mixed into the MP4."""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from src.core.renderer import RenderError, ToolNotFoundError, _ffmpeg

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac")
MUSIC_DIR_ENV = "WIBECODE_MUSIC_DIR"  # overrides the user's music folder
MUSIC_LOUDNESS = -26  # LUFS: well under speech (-14) so words stay clear
FADE_IN, FADE_OUT = 1.0, 2.0  # seconds
# While someone speaks the music drops by ~10 dB, then comes back between lines.
DUCK = "sidechaincompress=threshold=0.05:ratio=4:attack=20:release=400"
STEREO = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"


def bundled_dir() -> Path:
    """assets/music/<mood>/ next to the sources, or inside the PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / "music"


def user_dir() -> Path:
    """Folder for tracks the user added (survives app updates)."""
    if os.environ.get(MUSIC_DIR_ENV):
        return Path(os.environ[MUSIC_DIR_ENV])
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ShortsStudio" / "music"


def _audio_files(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(str(p) for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXTS)


def bundled_tracks(mood: str) -> list[str]:
    return _audio_files(bundled_dir() / mood)


def user_tracks() -> list[str]:
    return _audio_files(user_dir())


def pick_track(mood: str, rng: random.Random = random) -> Optional[str]:
    """A bundled track for the mood the LLM chose; None for "none" or an empty mood folder."""
    tracks = bundled_tracks(mood) if mood != "none" else []
    return rng.choice(tracks) if tracks else None


def _probe(path: str) -> tuple[float, bool]:
    """(duration in seconds, has an audio stream)."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise ToolNotFoundError("ffprobe не найден: он ставится вместе с FFmpeg, добавьте его в PATH")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
        capture_output=True, text=True, errors="replace",
    )  # fmt: skip
    if result.returncode != 0:
        raise RenderError(f"не удалось прочитать {path}: {result.stderr.strip()[-300:]}")
    info = json.loads(result.stdout)
    duration = float(info.get("format", {}).get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return duration, has_audio


def import_track(path: str) -> str:
    """Copy the user's audio file into user_dir() and return the copy's path."""
    src = Path(path)
    if src.suffix.lower() not in AUDIO_EXTS:
        raise RenderError(f"неподдерживаемый формат {src.suffix or src.name}: нужен {', '.join(AUDIO_EXTS)}")
    if not src.is_file():
        raise RenderError(f"файл не найден: {path}")
    if not _probe(str(src))[1]:
        raise RenderError(f"в файле нет звука: {src.name}")
    folder = user_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest, n = folder / src.name, 2
    while dest.exists():
        dest, n = folder / f"{src.stem} ({n}){src.suffix}", n + 1
    shutil.copy2(src, dest)
    return str(dest)


def add_music(video_path: str, track_path: str, out_path: Optional[str] = None) -> str:
    """Mix track_path under the video's audio into out_path (default: in place) atomically.

    The track loops to the video length, fades in and out, sits at -26 LUFS and
    ducks under existing speech. Video frames and duration stay unchanged.
    """
    video = os.path.abspath(video_path)
    out = os.path.abspath(out_path or video_path)
    if not os.path.isfile(track_path):
        raise RenderError(f"файл музыки не найден: {track_path}")
    duration, has_voice = _probe(video)
    if duration <= 0:
        raise RenderError(f"не удалось узнать длину видео {video_path}")
    fade_in, fade_out = min(FADE_IN, duration / 4), min(FADE_OUT, duration / 4)
    music = (
        f"[1:a]{STEREO},atrim=end={duration:.6f},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={MUSIC_LOUDNESS}:TP=-2:LRA=11,{STEREO},"
        f"afade=t=in:d={fade_in:.3f},afade=t=out:st={duration - fade_out:.6f}:d={fade_out:.3f}"
    )
    if has_voice:
        filters = [
            f"{music}[music]",
            f"[0:a]{STEREO},asplit[voice][key]",
            f"[music][key]{DUCK}[ducked]",
            "[voice][ducked]amix=inputs=2:normalize=0:duration=first[aout]",
        ]
    else:
        filters = [f"{music}[aout]"]
    part = f"{out}.{os.getpid()}.part"
    cmd = [
        _ffmpeg(), "-y", "-v", "error", "-i", video, "-stream_loop", "-1", "-i", track_path,
        "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{duration:.6f}",
        "-movflags", "+faststart", "-f", "mp4", part,
    ]  # fmt: skip
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if result.returncode != 0:
            raise RenderError(f"FFmpeg не смог добавить музыку: {result.stderr.strip()[-500:]}")
        os.replace(part, out)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return out
