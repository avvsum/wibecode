"""YouTube metadata for a generated video: title, description and tags."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

# YouTube limits.
TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_TOTAL_MAX = 500

SHORTS_HASHTAG = "#Shorts"
_SHORTS_RE = re.compile(r"#shorts\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"[<>]")  # YouTube rejects angle brackets in all three fields


class MetadataError(ValueError):
    """Metadata JSON is invalid or breaks YouTube limits. Message is user-readable."""


@dataclass(frozen=True)
class VideoMetadata:
    title: str
    description: str
    tags: tuple[str, ...]

    def as_text(self) -> str:
        """Plain text to paste into YouTube Studio."""
        return (
            f"Название:\n{self.title}\n\n"
            f"Описание:\n{self.description}\n\n"
            f"Теги:\n{', '.join(self.tags)}"
        )


def tags_length(tags) -> int:
    """Length as YouTube counts it: commas between tags, quotes around tags with spaces."""
    return sum(len(tag) + (2 if " " in tag else 0) for tag in tags) + max(len(tags) - 1, 0)


def _text(data: dict, field: str, limit: int) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MetadataError(f"{field}: нужна непустая строка")
    value = value.strip()
    if len(value) > limit:
        raise MetadataError(f"{field}: {len(value)} символов, допустимо не больше {limit}")
    if _FORBIDDEN_RE.search(value):
        raise MetadataError(f"{field}: символы < и > YouTube не принимает")
    return value


def _tags(data: dict) -> tuple[str, ...]:
    value = data.get("tags")
    if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
        raise MetadataError("tags: нужен список строк")
    tags, seen = [], set()
    for tag in value:
        tag = " ".join(tag.strip().lstrip("#").split())
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    if not tags:
        raise MetadataError("tags: нужен хотя бы один тег")
    if any(_FORBIDDEN_RE.search(tag) for tag in tags):
        raise MetadataError("tags: символы < и > YouTube не принимает")
    total = tags_length(tags)
    if total > TAGS_TOTAL_MAX:
        raise MetadataError(f"tags: вместе {total} символов, допустимо не больше {TAGS_TOTAL_MAX}")
    return tuple(tags)


def parse_metadata(raw: str) -> VideoMetadata:
    """Parse and validate the model's metadata JSON. Raises MetadataError.

    Tags lose a leading # and duplicates; #Shorts is added to the description if missing.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MetadataError(f"невалидный JSON: {e.msg}") from None
    if not isinstance(data, dict):
        raise MetadataError("JSON должен быть объектом")
    title = _text(data, "title", TITLE_MAX)
    description = _text(data, "description", DESCRIPTION_MAX)
    tags = _tags(data)
    if not _SHORTS_RE.search(description):
        description = f"{description}\n\n{SHORTS_HASHTAG}"
        if len(description) > DESCRIPTION_MAX:
            raise MetadataError(f"description: с {SHORTS_HASHTAG} длиннее {DESCRIPTION_MAX} символов")
    return VideoMetadata(title, description, tags)


def check_metadata(raw: str) -> Optional[str]:
    """Error message for invalid metadata, or None if it is valid."""
    try:
        parse_metadata(raw)
    except MetadataError as e:
        return str(e)
    return None
