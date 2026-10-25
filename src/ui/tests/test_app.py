"""Связка окна с программой (src/ui/app.py): без сети, на заглушках и быстром «рендере»."""
import inspect
import os
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from src.ui import app as app_module
from src.ui import stubs, worker
from src.ui.features import CHOICES, Extra
from src.ui.shell import ShellWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path)

    def render_video(spec, out_path, *, on_progress=None):
        for done in (0, 30, 60):
            on_progress(done, 60)
        with open(out_path, "wb") as f:
            f.write(b"mp4")
        return out_path

    monkeypatch.setattr(worker, "api", SimpleNamespace(**{**vars(stubs.api), "render_video": render_video}))
    monkeypatch.setattr(worker, "llm", stubs.llm)
    w = ShellWindow()
    controller = app_module.AppController(w)
    yield w, controller
    w.close()


def wait_idle(qapp, controller, timeout=10):
    end = time.time() + timeout
    while controller._thread is not None and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert controller._thread is None, "поток не завершился"


def test_every_choice_is_a_worker_parameter():
    params = inspect.signature(worker.RenderWorker.__init__).parameters
    for choice in CHOICES:
        assert choice.key in params, f"настройка {choice.key!r} не передаётся в RenderWorker"


def test_scene_dicts_from_real_spec():
    from src.api import parse_spec
    spec = parse_spec('{"duration": 4, "scenes": [{"type": "text", "text": "Привет", "start": 0, "end": 4}]}')
    scenes, duration = app_module.scene_dicts(spec)
    assert duration == 4.0 and scenes[0]["type"] == "text" and scenes[0]["text"] == "Привет"


def test_full_run_shows_script_and_video(qapp, window):
    w, controller = window
    controller.start("Ролик про кофе", "2d", {"voice": None})
    wait_idle(qapp, controller)
    assert w.pill.text() == "Готово"
    assert len(w._scenes) == 3 and w._duration == 15.0
    assert w._video_path and os.path.exists(w._video_path)
    assert "Для YouTube" in w._extras, "метаданные воркера сами стали карточкой"
    assert controller._metadata is not None, "метаданные сохранены для публикации"


def test_publish_uses_llm_metadata_and_keeps_video(qapp, window, monkeypatch):
    w, controller = window
    sent = {}

    class FakePublish(QObject):
        uploaded = Signal(int, int)
        finished = Signal(str)
        failed = Signal(str)

        def __init__(self, video_path, title, description, tags=()):
            super().__init__()
            sent.update(path=video_path, title=title, tags=tuple(tags))

        def run(self):
            self.uploaded.emit(50, 100)
            self.finished.emit("https://youtu.be/demo")

    monkeypatch.setattr(app_module, "PublishWorker", FakePublish)
    monkeypatch.setattr(app_module.QDesktopServices, "openUrl", lambda url: True)
    controller.start("Ролик про кофе", "2d", {"voice": None})
    wait_idle(qapp, controller)
    w.publish_button.click()
    wait_idle(qapp, controller)
    assert sent["path"] == w._video_path and sent["title"] == controller._metadata.title
    assert w.pill.text() == "Опубликовано" and "youtu.be/demo" in w.notice.text()
    assert w._video_path is not None, "видео остаётся в превью"


def test_voiceover_failure_keeps_the_video(qapp, window, monkeypatch):
    w, controller = window

    def broken_tts(spec, out_dir, client=None):
        raise stubs.TTSError("нет ключа ELEVENLABS_API_KEY")

    tts = SimpleNamespace(TTSError=stubs.TTSError, synthesize_spec=broken_tts)
    monkeypatch.setattr(worker, "llm", SimpleNamespace(**{**vars(stubs.llm), "tts": tts}))
    controller.start("Ролик с голосом", "2d", {"voice": "elevenlabs"})
    wait_idle(qapp, controller)
    assert w.pill.text() == "Готово", "видео отрендерено — не теряем его"
    assert w._video_path is not None
    assert "озвучка не удалась" in w.notice.text().lower()


def test_new_extra_signal_appears_as_card_by_itself(qapp, window, monkeypatch):
    """Новый результат: сигнал (text, ok) в воркере + Extra в features.EXTRAS — и окно его покажет."""
    w, controller = window

    class WorkerWithHashtags(worker.RenderWorker):
        hashtags = Signal(str, bool)

        def run(self):
            self.hashtags.emit("#кофе #сон", True)
            super().run()

    monkeypatch.setattr(app_module, "RenderWorker", WorkerWithHashtags)
    monkeypatch.setattr(app_module, "EXTRAS", app_module.EXTRAS + (Extra("hashtags", "Хештеги"),))
    controller.start("Ролик про кофе", "2d", {"voice": None})
    wait_idle(qapp, controller)
    card = w._extras.get("Хештеги")
    assert card is not None and card.text.text() == "#кофе #сон" and card.copy_button.isVisibleTo(w)
