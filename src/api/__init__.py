"""Public API: the only entry points UI and LLM layers should use."""

from __future__ import annotations

from src.core import music, renderer, schema, voiceover
from src.core.renderer import ProgressCallback, RenderCancelled, RenderError, ToolNotFoundError
from src.core.schema import (
    CASTS, ENVIRONMENTS, MUSIC_MOODS, SAY_SHOTS, SAY_WHO, STYLES, Spec, SpecError,
)

__all__ = [
    "CASTS",
    "ENVIRONMENTS",
    "MUSIC_MOODS",
    "SAY_SHOTS",
    "SAY_WHO",
    "STYLES",
    "ProgressCallback",
    "RenderCancelled",
    "RenderError",
    "Spec",
    "SpecError",
    "ToolNotFoundError",
    "add_music",
    "add_voiceover",
    "import_music",
    "pick_music",
    "parse_spec",
    "render_video",
    "user_music",
]


def parse_spec(raw: str) -> Spec:
    """Parse a raw JSON spec. Raises SpecError on invalid JSON or contract violation."""
    return schema.parse(raw)


def render_video(
    spec: Spec, out_path: str, *, on_progress: ProgressCallback | None = None
) -> str:
    """Render spec to an MP4 at out_path and return its absolute path.

    on_progress(done_frames, total_frames) is called from the rendering thread:
    total is fixed for one render (0 if unknown), done grows from 0 to total and
    the last call on success has done == total. Returning False cancels the
    render with RenderCancelled. out_path is written atomically: on failure or
    cancel it is not created and an existing file is left untouched.

    Raises RenderError if the video cannot be produced (ToolNotFoundError,
    also a FileNotFoundError, when FFmpeg is missing; RenderCancelled on
    cancel). render_mode "3d" needs Blender (ToolNotFoundError without it).
    """
    return renderer.render(spec, out_path, on_progress)


def add_voiceover(video_path: str, clips, out_path: str | None = None) -> str:
    """Mix voice clips (objects with path, start, end in seconds) into a rendered MP4.

    Writes out_path (default: video_path in place) atomically and returns it.
    Each clip is cut at its end; video frames are copied unchanged.
    Raises RenderError (ToolNotFoundError without FFmpeg).
    """
    return voiceover.add_voiceover(video_path, clips, out_path)


def pick_music(mood: str) -> str | None:
    """A bundled track for spec.music (assets/music/<mood>/); None if "none" or no track."""
    return music.pick_track(mood)


def user_music() -> list[str]:
    """Tracks the user added with import_music, sorted by file name."""
    return music.user_tracks()


def import_music(path: str) -> str:
    """Copy the user's audio file (mp3, wav, ogg, m4a, flac, aac) into their music
    folder and return the copy's path. Raises RenderError for a non-audio file."""
    return music.import_track(path)


def add_music(video_path: str, track_path: str, out_path: str | None = None) -> str:
    """Mix a music track under the rendered MP4's audio; returns out_path (default: in place).

    The track loops to the video length, fades in/out, sits at -26 LUFS and ducks
    under speech added by add_voiceover, so call it after add_voiceover.
    Raises RenderError (ToolNotFoundError without FFmpeg/ffprobe).
    """
    return music.add_music(video_path, track_path, out_path)
