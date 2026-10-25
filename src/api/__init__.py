"""Public API: the only entry points UI and LLM layers should use."""

from __future__ import annotations

from src.core import renderer, schema
from src.core.renderer import RenderError
from src.core.schema import Spec, SpecError

__all__ = ["RenderError", "Spec", "SpecError", "parse_spec", "render_video"]


def parse_spec(raw: str) -> Spec:
    """Parse a raw JSON spec. Raises SpecError on invalid JSON or contract violation."""
    return schema.parse(raw)


def render_video(spec: Spec, out_path: str) -> str:
    """Render spec to an MP4 at out_path and return its absolute path.

    Raises RenderError if the video cannot be produced and
    NotImplementedError for render_mode "3d" (not implemented yet).
    """
    return renderer.render(spec, out_path)
