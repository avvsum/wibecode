"""Единственное место, откуда UI берёт backend и LLM.

Для разработки без сети и ключа API можно временно подключить заглушки:
    from src.ui.stubs import api, llm
"""
from src import api, llm  # noqa: F401
