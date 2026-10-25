"""Scene spec (JSON contract) as pydantic models with validation."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError, model_validator

RenderMode = Literal["2d", "3d"]


class SpecError(ValueError):
    """Spec is not valid JSON or breaks the contract. Message is user-readable."""


class _Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: FiniteFloat = Field(ge=0)
    end: FiniteFloat

    @model_validator(mode="after")
    def _check_times(self):
        if self.start >= self.end:
            raise ValueError(f"start ({self.start:g}) должен быть меньше end ({self.end:g})")
        return self


class TextScene(_Scene):
    type: Literal["text"]
    text: str = Field(min_length=1)


class ImageScene(_Scene):
    type: Literal["image"]
    path: str = Field(min_length=1)


class ChartScene(_Scene):
    type: Literal["chart"]
    data: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=2)


Scene = Annotated[Union[TextScene, ImageScene, ChartScene], Field(discriminator="type")]


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration: FiniteFloat = Field(gt=0)
    render_mode: RenderMode = "2d"
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_timeline(self):
        for i, scene in enumerate(self.scenes):
            if scene.end > self.duration:
                raise ValueError(
                    f"scenes[{i}]: end ({scene.end:g}) больше duration ({self.duration:g})"
                )
        ordered = sorted(enumerate(self.scenes), key=lambda p: p[1].start)
        for (i, a), (j, b) in zip(ordered, ordered[1:]):
            if b.start < a.end:
                raise ValueError(f"scenes[{i}] и scenes[{j}] пересекаются по времени")
        return self


def _format_errors(e: ValidationError) -> str:
    lines = []
    for err in e.errors():
        parts = list(err["loc"])
        # Drop the union tag: ("scenes", 1, "chart", "end") -> scenes[1].end
        if len(parts) >= 3 and parts[0] == "scenes" and parts[2] in ("text", "image", "chart"):
            del parts[2]
        loc = ""
        for part in parts:
            loc += f"[{part}]" if isinstance(part, int) else (f".{part}" if loc else str(part))
        msg = err["msg"].removeprefix("Value error, ")
        if err["type"] == "union_tag_not_found":
            msg = "не указан type (text, image или chart)"
        elif err["type"] == "union_tag_invalid":
            msg = f"неизвестный type {err['input'].get('type')!r}, допустимы: text, image, chart"
        elif err["type"] == "literal_error" and loc == "render_mode":
            msg = f"неизвестный render_mode {err['input']!r}, допустимы: 2d, 3d"
        lines.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(lines)


def parse(raw: str) -> Spec:
    """Parse and validate a raw JSON spec. Raises SpecError."""
    if not isinstance(raw, (str, bytes)):
        raise SpecError(f"ожидалась строка с JSON, получено {type(raw).__name__}")
    try:
        return Spec.model_validate_json(raw)
    except ValidationError as e:
        if any(err["type"] == "json_invalid" for err in e.errors()):
            detail = e.errors()[0]["msg"].removeprefix("Invalid JSON: ")
            raise SpecError(f"невалидный JSON: {detail}") from None
        raise SpecError(_format_errors(e)) from None
