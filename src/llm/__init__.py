"""LLM layer: user text -> raw JSON spec and YouTube metadata.

Public entry points: generate_spec, generate_metadata.
Provider: DeepSeek (DEEPSEEK_API_KEY) by default, Anthropic optionally; see default_client.
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
    default_client,
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
    "default_client",
    "generate_metadata",
    "generate_spec",
    "tts",
]
