"""Public API: the only entry points UI and LLM layers should use."""

from __future__ import annotations

from src.core import renderer, schema
from src.core.renderer import ProgressCallback, RenderCancelled, RenderError, ToolNotFoundError
from src.core.schema import SAY_SHOTS, SAY_WHO, Spec, SpecError

__all__ = [
    "SAY_SHOTS",
    "SAY_WHO",
    "ProgressCallback",
    "RenderCancelled",
    "RenderError",
    "Spec",
    "SpecError",
    "ToolNotFoundError",
    "parse_spec",
    "render_video",
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
