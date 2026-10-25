"""Mix voice clips into a rendered MP4: video is copied, speech becomes an AAC track."""

from __future__ import annotations

import os
import subprocess
from typing import Optional, Protocol, Sequence

from src.core.renderer import RenderError, _ffmpeg

FADE_OUT = 0.15  # seconds; softens speech cut at the end of its scene
# YouTube plays at -14 LUFS: level speech there so it is neither quiet nor clipped.
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100"


class Clip(Protocol):
    path: str
    start: float
    end: float


def add_voiceover(video_path: str, clips: Sequence[Clip], out_path: Optional[str] = None) -> str:
    """Write video_path with clips mixed in to out_path (default: in place) atomically.

    Each clip starts at its start and is cut at its end, so speech never spills
    into the next scene; the mix is levelled to -14 LUFS. Video frames and
    duration stay unchanged.
    """
    video = os.path.abspath(video_path)
    out = os.path.abspath(out_path or video_path)
    if not clips:
        if out != video:
            raise RenderError("нет реплик для озвучки")
        return out
    for clip in clips:
        if not os.path.isfile(clip.path):
            raise RenderError(f"файл озвучки не найден: {clip.path}")

    cmd = [_ffmpeg(), "-y", "-v", "error", "-i", video]
    filters = []
    for i, clip in enumerate(clips):
        length = clip.end - clip.start
        chain = f"[{i + 1}:a]aresample=44100,atrim=end={length:.6f}"
        if length > 2 * FADE_OUT:
            chain += f",afade=t=out:st={length - FADE_OUT:.6f}:d={FADE_OUT}"
        chain += f",adelay={round(clip.start * 1000)}:all=1[a{i}]"
        filters.append(chain)
        cmd += ["-i", clip.path]
    inputs = "".join(f"[a{i}]" for i in range(len(clips)))
    filters.append(f"{inputs}amix=inputs={len(clips)}:normalize=0,{LOUDNORM},apad[aout]")
    part = f"{out}.{os.getpid()}.part"
    cmd += [
        "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
        "-movflags", "+faststart", "-f", "mp4", part,
    ]  # fmt: skip
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if result.returncode != 0:
            raise RenderError(f"FFmpeg не смог добавить озвучку: {result.stderr.strip()[-500:]}")
        os.replace(part, out)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return out
