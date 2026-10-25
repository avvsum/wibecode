"""Связка окна с программой (src/ui/app.py): без сети, на заглушках и быстром «рендере»."""
import inspect
import json
import os
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal, Slot
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


def test_choice_with_computed_options_and_own_file(qapp, monkeypatch):
    """Динамический список + «Свой файл…»: выбранный путь уходит в воркер, отмена — откат."""
    from src.ui import shell as shell_module
    from src.ui.features import Choice
    music = Choice("music", "Музыка", lambda: [("auto", "Авто"), (None, "Без музыки")], browse="Аудио (*.mp3)")
    monkeypatch.setattr(shell_module, "CHOICES", shell_module.CHOICES + (music,))
    w = ShellWindow()
    box = w._choices["music"]
    assert [box.itemText(i) for i in range(box.count())] == ["Авто", "Без музыки", "Свой файл…"]
    assert w.options()["music"] == "auto"
    monkeypatch.setattr(shell_module.QFileDialog, "getOpenFileName", lambda *a: ("C:/music/track.mp3", ""))
    box.setCurrentIndex(2)
    box.activated.emit(2)
    assert w.options()["music"] == "C:/music/track.mp3" and box.currentText() == "track.mp3"
    monkeypatch.setattr(shell_module.QFileDialog, "getOpenFileName", lambda *a: ("", ""))
    box.setCurrentIndex(box.count() - 1)
    box.activated.emit(box.count() - 1)
    assert w.options()["music"] == "C:/music/track.mp3", "отмена диалога возвращает прежний выбор"
    w.close()


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


def test_audio_stages_reach_window_without_resetting_frames_or_busy_state(qapp, monkeypatch, tmp_path):
    class RecordingWindow(ShellWindow):
        def __init__(self):
            super().__init__()
            self.stages = []

        @Slot(str)
        def set_stage(self, text):
            super().set_stage(text)
            self.stages.append((
                self.stage.text(), self.progress.maximum(), self.progress.value(),
                self.create_button.isEnabled(), self.cancel_button.isEnabled(),
                any(box.isEnabled() for box in self._choices.values()),
            ))

    def render_video(spec, path, *, on_progress=None):
        on_progress(60, 60)
        with open(path, "wb") as output:
            output.write(b"mp4")
        return path

    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(worker, "api", SimpleNamespace(**{
        **vars(stubs.api), "render_video": render_video, "pick_music": lambda mood: "music.wav",
    }))
    monkeypatch.setattr(worker, "llm", stubs.llm)
    w = RecordingWindow()
    controller = app_module.AppController(w)
    try:
        controller.start("Короткий ролик", "2d", {"voice": "elevenlabs", "music": "auto"})
        wait_idle(qapp, controller)
        audio = [state for state in w.stages if state[0].startswith(("Озвучка", "Музыка"))]
        assert [state[0] for state in audio] == ["Озвучка…", "Музыка: none…"]
        assert all(state[1:] == (60, 60, False, True, False) for state in audio), audio
        assert w.pill.text() == "Готово"
    finally:
        w.close()


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


def test_window_opens_prompt_only(qapp):
    """По умолчанию — только описание: режим «Авто», остальные настройки свёрнуты."""
    w = ShellWindow()
    assert w.mode.value() == "auto"
    assert w.options() == {choice.key: choice.resolve()[0][0] for choice in CHOICES}
    assert not w.advanced.isVisibleTo(w) and w.advanced_button.text() == "Дополнительно  ▸"

    w.advanced_button.setChecked(True)
    assert w.advanced.isVisibleTo(w) and w.advanced_button.text() == "Дополнительно  ▾"
    w.mode.set_value("3d")
    w._choices["voice"].setCurrentIndex(1)
    w.advanced_button.setChecked(False)
    assert not w.advanced.isVisibleTo(w)
    assert w.advanced_button.text() == "Дополнительно: 3D, ElevenLabs  ▸", "скрытый выбор виден на кнопке"
    w.close()


def test_auto_mode_sends_only_the_description(qapp, window, monkeypatch):
    """«Авто»: в LLM уходит одно описание, режим из сценария модели принимается как есть."""
    w, controller = window
    prompts = []
    spec_3d = json.dumps({"duration": 4, "render_mode": "3d",
                          "scenes": [{"type": "text", "text": "Привет", "start": 0, "end": 4}]})

    def generate_spec(user_text):
        prompts.append(user_text)
        return spec_3d

    monkeypatch.setattr(worker, "llm", SimpleNamespace(**{**vars(stubs.llm), "generate_spec": generate_spec}))
    w.input.setPlainText("Диалог робота и девушки в 3D")
    w._request_render()
    wait_idle(qapp, controller)
    assert prompts == ["Диалог робота и девушки в 3D"], "без подсказок render_mode/environment/cast"
    assert w.pill.text() == "Готово"
    assert "30 кадров/с" in w.format_label.text(), "кадры/с — по режиму, который выбрала модель"


def test_scene_summary_hides_highlight_marks_and_counts_points():
    from src.ui.widgets import scene_summary

    say = {"type": "say", "who": "robot", "text": "Почему *так быстро*?", "start": 0, "end": 1}
    assert scene_summary(say).endswith("«Почему так быстро?»")
    assert "*" in scene_summary({**say, "text": "звёздочка * одна"})
    chart = {"type": "chart", "start": 0, "end": 1}
    assert [scene_summary({**chart, "data": [[0, 0]] * n}) for n in (1, 2, 5, 11, 21)] == [
        "1 точка на графике", "2 точки на графике", "5 точек на графике",
        "11 точек на графике", "21 точка на графике"]
