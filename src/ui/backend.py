"""Единственное место, откуда UI берёт backend и LLM.

Сейчас подключены заглушки. Когда src.api (A) и src.llm (C) будут в main, заменить строку на:
    from src import api, llm
"""
from src.ui.stubs import api, llm  # noqa: F401
