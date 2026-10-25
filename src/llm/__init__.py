"""LLM layer: user text -> raw JSON spec. Public entry point: generate_spec."""

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
]
