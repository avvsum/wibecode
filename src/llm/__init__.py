"""LLM layer: user text -> raw JSON spec and YouTube metadata.

Public entry points: generate_spec, generate_metadata.
Voice-over (ElevenLabs text-to-speech) lives in src.llm.tts.
"""

from src.llm import tts
from src.llm.client import (
    AnthropicClient,
    FakeLLMClient,
    LLMClient,
    LLMError,
    SpecGenerationError,
    generate_metadata,
    generate_spec,
)
from src.llm.metadata import MetadataError, VideoMetadata

__all__ = [
    "AnthropicClient",
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "MetadataError",
    "SpecGenerationError",
    "VideoMetadata",
    "generate_metadata",
    "generate_spec",
    "tts",
]
