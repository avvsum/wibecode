"""LLM layer: user text -> raw JSON spec and YouTube metadata.

Public entry points: generate_spec, generate_metadata.
Provider: DeepSeek (DEEPSEEK_API_KEY) by default, Anthropic optionally; see default_client.
Voice-over (ElevenLabs text-to-speech) lives in src.llm.tts.
"""

from src.llm import tts
from src.llm.client import (
    AnthropicClient,
    DeepSeekClient,
    FakeLLMClient,
    LLMClient,
    LLMError,
    SpecGenerationError,
    default_client,
    generate_metadata,
    generate_spec,
)
from src.llm.metadata import MetadataError, VideoMetadata

__all__ = [
    "AnthropicClient",
    "DeepSeekClient",
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "MetadataError",
    "SpecGenerationError",
    "VideoMetadata",
    "default_client",
    "generate_metadata",
    "generate_spec",
    "tts",
]
