"""Что окно Shorts Studio показывает само, без правок в shell.py.

Новая настройка (как «Озвучка»): добавьте Choice в CHOICES и параметр с тем же именем
в RenderWorker.__init__ — окно нарисует выбор в левой панели и передаст значение воркеру.
Варианты можно отдавать функцией (например, список треков пользователя), а browse добавляет
пункт «Свой файл…» с выбором файла — тогда в воркер придёт путь к нему. Пример для музыки:

    Choice("music", "Музыка", lambda: [("auto", "Авто, по настроению"), (None, "Без музыки")]
           + [(t, Path(t).stem) for t in api.user_music()], browse="Аудио (*.mp3 *.wav *.m4a *.ogg)")

Текстовая настройка (как адрес и ключ API нейросети): добавьте Field в FIELDS и параметр с тем же
именем в RenderWorker.__init__ — окно нарисует поле ввода и запомнит введённое до следующего запуска.

Новый дополнительный результат (как YouTube-название и теги): заведите в RenderWorker сигнал
Signal(str, bool) — текст и «удалось ли» — и добавьте Extra с его именем в EXTRAS. Окно само
покажет карточку под сценарием, с кнопкой «Копировать», если удалось.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

from src.ui.backend import api


@dataclass(frozen=True)
class Choice:
    key: str  # имя параметра RenderWorker
    label: str
    options: Union[tuple, Callable[[], list]]  # пары (значение, подпись); первое — по умолчанию
    hint: str = ""
    browse: str = ""  # фильтр файлов для пункта «Свой файл…», например "Аудио (*.mp3 *.wav)"
    mode: str = ""  # пусто — оба режима; "3d" — только настройки сцены Blender

    def resolve(self) -> list:
        return list(self.options() if callable(self.options) else self.options)


@dataclass(frozen=True)
class Field:
    key: str  # имя параметра RenderWorker
    label: str
    placeholder: str = ""
    hint: str = ""
    secret: bool = False  # ввод скрыт точками, как пароль


@dataclass(frozen=True)
class Extra:
    signal: str  # имя сигнала RenderWorker с аргументами (text: str, ok: bool)
    title: str


# Нейросеть для сценария: любой OpenAI-совместимый API, модель выбирается автоматически.
FIELDS = (
    Field(
        "llm_base_url", "Адрес API нейросети", "https://api.openai.com/v1",
        hint="Любой OpenAI-совместимый API: OpenAI, OpenRouter, DeepSeek, локальный Ollama. "
             "Модель выбирается автоматически",
    ),
    Field("llm_api_key", "Ключ API", "sk-…", hint="Хранится только на этом компьютере", secret=True),
)


def music_options() -> list:
    return [("auto", "Авто, по настроению"), (None, "Без музыки")] + [
        (track, f"♪ {Path(track).stem}") for track in api.user_music()
    ]


CHOICES = (
    Choice(
        "voice", "Озвучка",
        ((None, "Без озвучки"), ("elevenlabs", "ElevenLabs"), ("chatterbox", "Chatterbox, локально")),
        hint="ElevenLabs: ключ в ELEVENLABS_API_KEY. Chatterbox: pip install -r requirements-chatterbox.txt",
    ),
    Choice(
        "music", "Музыка", music_options,
        hint="Авто берёт встроенный трек по настроению. Если трека нет, видео будет без музыки; выберите свой файл.",
        browse="Аудио (*.mp3 *.wav *.m4a *.ogg *.flac *.aac)",
    ),
    Choice(
        "environment", "Окружение",
        (("room", "Уютная комната"), ("forest", "Лесная поляна"), ("dungeon", "Подземелье"),
         ("space", "Космическая база"), ("city", "Городская площадь"), ("studio", "Исходная студия")),
        mode="3d",
    ),
    Choice(
        "cast", "Персонажи",
        (("knight_mage", "Рыцарь и маг"), ("rogue_duo", "Два разбойника"),
         ("barbarian_mage", "Варвар и маг"), ("ranger_knight", "Лучник и рыцарь"),
         ("classic", "Робот и девушка")),
        mode="3d",
    ),
)

EXTRAS = (
    Extra("metadata", "Для YouTube"),
)
