"""Scene spec (JSON contract) as pydantic models with validation."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError, model_validator

RenderMode = Literal["2d", "3d"]
SceneType = Literal["text", "image", "chart", "say"]
SayWho = Literal["robot", "girl"]
SayShot = Literal["wide", "medium", "close"]
# Post-processing look of the whole video, picked by the LLM (see core/styles.py).
Style = Literal[
    "none", "cinematic", "vivid", "bw", "sepia", "pixel", "retro", "warm", "cold", "dreamy"
]

SCENE_TYPES: tuple[str, ...] = SceneType.__args__
SAY_WHO: tuple[str, ...] = SayWho.__args__
SAY_SHOTS: tuple[str, ...] = SayShot.__args__
STYLES: tuple[str, ...] = Style.__args__
# Background music mood, picked by the LLM (see core/music.py).
Music = Literal["none", "calm", "upbeat", "epic", "lofi", "retro", "tense", "happy"]
MUSIC_MOODS: tuple[str, ...] = Music.__args__


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


class SayScene(_Scene):
    """A character line, 3D only. *word* in text marks a highlighted keyword."""

    type: Literal["say"]
    who: SayWho
    shot: SayShot
    text: str = Field(min_length=1)


Scene = Annotated[
    Union[TextScene, ImageScene, ChartScene, SayScene], Field(discriminator="type")
]


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration: FiniteFloat = Field(gt=0)
    render_mode: RenderMode = "2d"
    style: Style = "none"
    music: Music = "none"
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_timeline(self):
        for i, scene in enumerate(self.scenes):
            if scene.type == "say" and self.render_mode != "3d":
                raise ValueError(f'scenes[{i}]: тип say доступен только при render_mode "3d"')
            if scene.end > self.duration:
                raise ValueError(
                    f"scenes[{i}]: end ({scene.end:g}) больше duration ({self.duration:g})"
                )
        ordered = sorted(enumerate(self.scenes), key=lambda p: p[1].start)
        for (i, a), (j, b) in zip(ordered, ordered[1:]):
            if b.start < a.end:
                raise ValueError(f"scenes[{i}] и scenes[{j}] пересекаются по времени")
        return self


def _choices(values) -> str:
    return ", ".join(values)


# Russian texts for pydantic error types; shown to the user as is.
_MESSAGES = {
    "missing": lambda ctx: "обязательное поле не указано",
    "extra_forbidden": lambda ctx: "лишнее поле, в контракте его нет",
    "finite_number": lambda ctx: "должно быть конечным числом",
    "float_type": lambda ctx: "должно быть числом",
    "float_parsing": lambda ctx: "должно быть числом",
    "string_type": lambda ctx: "должно быть строкой",
    "string_too_short": lambda ctx: "не должно быть пустым",
    "too_short": lambda ctx: f"слишком мало элементов, нужно минимум {ctx['min_length']}",
    "too_long": lambda ctx: f"слишком много элементов, допустимо не больше {ctx['max_length']}",
    "greater_than": lambda ctx: f"должно быть больше {ctx['gt']:g}",
    "greater_than_equal": lambda ctx: f"должно быть не меньше {ctx['ge']:g}",
    "list_type": lambda ctx: "должно быть списком",
    "tuple_type": lambda ctx: "должно быть парой чисел [x, y]",
    "model_type": lambda ctx: "должно быть объектом",
    "model_attributes_type": lambda ctx: "должно быть объектом",
    "dict_type": lambda ctx: "должно быть объектом",
    "union_tag_not_found": lambda ctx: f"не указан type ({_choices(SCENE_TYPES)})",
}

_LITERAL_FIELDS = {
    "render_mode": RenderMode, "who": SayWho, "shot": SayShot, "style": Style, "music": Music,
}


def _location(loc: tuple) -> str:
    parts = list(loc)
    # Drop the union tag: ("scenes", 1, "chart", "end") -> scenes[1].end
    if len(parts) >= 3 and parts[0] == "scenes" and parts[2] in SCENE_TYPES:
        del parts[2]
    text = ""
    for part in parts:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def _message(err: dict) -> str:
    kind, ctx, field = err["type"], err.get("ctx", {}), err["loc"][-1] if err["loc"] else None
    if kind == "union_tag_invalid":
        tag = err["input"].get("type") if isinstance(err["input"], dict) else None
        return f"неизвестный type {tag!r}, допустимы: {_choices(SCENE_TYPES)}"
    if kind == "literal_error" and field in _LITERAL_FIELDS:
        allowed = _choices(_LITERAL_FIELDS[field].__args__)
        return f"неизвестный {field} {err['input']!r}, допустимы: {allowed}"
    if kind == "value_error":
        return err["msg"].removeprefix("Value error, ")
    if kind in _MESSAGES:
        return _MESSAGES[kind](ctx)
    return err["msg"]


def _format_errors(e: ValidationError) -> str:
    lines = []
    for err in e.errors():
        loc, msg = _location(err["loc"]), _message(err)
        if not loc and err["type"] in ("model_type", "model_attributes_type", "dict_type"):
            msg = "JSON должен быть объектом"
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
