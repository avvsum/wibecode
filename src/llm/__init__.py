"""LLM layer: user text -> raw JSON spec. Public entry point: generate_spec.

Voice-over (ElevenLabs text-to-speech) lives in src.llm.tts.
"""

from src.llm import tts

from src.llm.client import (
    AnthropicClient,
    FakeLLMClient,
    LLMClient,
    LLMError,
    SpecGenerationError,
    generate_spec,
)

__all__ = [
    "AnthropicClient",
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "SpecGenerationError",
    "generate_spec",
    "tts",
]
