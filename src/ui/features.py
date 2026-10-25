"""Что окно Shorts Studio показывает само, без правок в shell.py.

Новая настройка (как «Озвучка»): добавьте Choice в CHOICES и параметр с тем же именем
в RenderWorker.__init__ — окно нарисует выбор в левой панели и передаст значение воркеру.
Варианты можно отдавать функцией (например, список треков пользователя), а browse добавляет
пункт «Свой файл…» с выбором файла — тогда в воркер придёт путь к нему. Пример для музыки:

    Choice("music", "Музыка", lambda: [("auto", "Авто, по настроению"), (None, "Без музыки")]
           + [(t, Path(t).stem) for t in api.user_music()], browse="Аудио (*.mp3 *.wav *.m4a *.ogg)")

Новый дополнительный результат (как YouTube-название и теги): заведите в RenderWorker сигнал
Signal(str, bool) — текст и «удалось ли» — и добавьте Extra с его именем в EXTRAS. Окно само
покажет карточку под сценарием, с кнопкой «Копировать», если удалось.
"""
from dataclasses import dataclass
from typing import Callable, Union


@dataclass(frozen=True)
class Choice:
    key: str  # имя параметра RenderWorker
    label: str
    options: Union[tuple, Callable[[], list]]  # пары (значение, подпись); первое — по умолчанию
    hint: str = ""
    browse: str = ""  # фильтр файлов для пункта «Свой файл…», например "Аудио (*.mp3 *.wav)"

    def resolve(self) -> list:
        return list(self.options() if callable(self.options) else self.options)


@dataclass(frozen=True)
class Extra:
    signal: str  # имя сигнала RenderWorker с аргументами (text: str, ok: bool)
    title: str


CHOICES = (
    Choice(
        "voice", "Озвучка",
        ((None, "Без озвучки"), ("elevenlabs", "ElevenLabs"), ("chatterbox", "Chatterbox, локально")),
        hint="ElevenLabs: ключ в ELEVENLABS_API_KEY. Chatterbox: pip install -r requirements-chatterbox.txt",
    ),
)

EXTRAS = (
    Extra("metadata", "Для YouTube"),
)
