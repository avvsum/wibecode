"""Shared offline policy, including tests kept inside role-owned packages."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def blocked(*args, **kwargs):
        pytest.fail("Тесты не должны обращаться в сеть", pytrace=False)

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    for variable in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "ELEVENLABS_API_KEY",
        "WIBECODE_LLM_BASE_URL", "WIBECODE_LLM_API_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)
    # Tracks imported in tests must not land in the developer's real music folder.
    monkeypatch.setenv("WIBECODE_MUSIC_DIR", str(tmp_path / "user-music"))
    # The window must not read or overwrite the developer's saved API address and key.
    monkeypatch.setenv("WIBECODE_SETTINGS", str(tmp_path / "settings.ini"))
