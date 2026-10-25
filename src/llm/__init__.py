"""LLM layer: user text -> raw JSON spec and YouTube metadata.

Public entry points: generate_spec, generate_metadata.
Voice-over (ElevenLabs text-to-speech) lives in src.llm.tts.
"""

from src.llm import tts
from src.llm.client import (
    FakeLLMClient,
    LLMClient,
    LLMError,
    OpenAICompatibleClient,
    SpecGenerationError,
    connect,
    generate_metadata,
    generate_spec,
)
from src.llm.metadata import MetadataError, VideoMetadata

__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "MetadataError",
    "OpenAICompatibleClient",
    "SpecGenerationError",
    "VideoMetadata",
    "connect",
    "generate_metadata",
    "generate_spec",
    "tts",
]
