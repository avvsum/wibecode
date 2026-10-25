"""The active UI keeps music, voice and KayKit choices in one render request."""

import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.ui import features, shell
from src.ui.worker import RenderWorker


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(features.api, "user_music", lambda: [])
    window = shell.ShellWindow()
    yield window
    window.close()


def test_choice_names_match_render_worker():
    params = inspect.signature(RenderWorker.__init__).parameters
    assert {choice.key for choice in features.CHOICES} == {"voice", "music", "environment", "cast"}
    assert all(choice.key in params for choice in features.CHOICES)


def test_music_lists_user_tracks_without_promising_an_auto_track(monkeypatch):
    monkeypatch.setattr(features.api, "user_music", lambda: ["C:/music/my-track.mp3"])
    options = features.music_options()
    assert options[:2] == [("auto", "Авто, по настроению"), (None, "Без музыки")]
    assert options[2] == ("C:/music/my-track.mp3", "♪ my-track")
    choice = next(choice for choice in features.CHOICES if choice.key == "music")
    assert "Если трека нет" in choice.hint


@pytest.mark.parametrize("mode", ["auto", "2d"])
def test_new_ui_hides_3d_choices_in_2d_and_keeps_defaults(window, mode):
    window.mode.set_value(mode)
    assert window.options() == {"voice": None, "music": "auto"}
    assert window._choice_rows["environment"].isHidden()
    assert window._choice_rows["cast"].isHidden()
    window.mode.set_value("3d")
    assert window.options() == {
        "voice": None, "music": "auto", "environment": "room", "cast": "knight_mage",
    }
    assert not window._choice_rows["environment"].isHidden()
    assert not window._choice_rows["cast"].isHidden()


def test_switching_mode_preserves_kaykit_choices_without_applying_them_in_auto_or_2d(window):
    window.mode.set_value("3d")
    for key, value in (("environment", "forest"), ("cast", "ranger_knight")):
        box = window._choices[key]
        box.setCurrentIndex(box.findData(value))
    expected = {"environment": "forest", "cast": "ranger_knight"}
    assert window.options() == {"voice": None, "music": "auto", **expected}
    assert window.advanced_button.text() == "Дополнительно: 3D, Лесная поляна, Лучник и рыцарь  ▸"

    for mode, label in (("auto", "Дополнительно  ▸"), ("2d", "Дополнительно: 2D  ▸")):
        window.mode.set_value(mode)
        assert window.options() == {"voice": None, "music": "auto"}
        assert all(window._choice_rows[key].isHidden() for key in expected)
        assert window.advanced_button.text() == label

    window.mode.set_value("3d")
    assert window.options() == {"voice": None, "music": "auto", **expected}
    assert all(not window._choice_rows[key].isHidden() for key in expected)
    assert window.advanced_button.text() == "Дополнительно: 3D, Лесная поляна, Лучник и рыцарь  ▸"


def test_voice_music_and_kaykit_reach_the_same_request(window):
    window.mode.set_value("3d")
    for key, value in (
        ("voice", "elevenlabs"), ("music", None), ("environment", "forest"), ("cast", "ranger_knight"),
    ):
        box = window._choices[key]
        box.setCurrentIndex(box.findData(value))
    window.input.setPlainText("Короткая история")
    requests = []
    window.render_requested.connect(lambda text, mode, options: requests.append((text, mode, options)))
    window._request_render()
    assert requests == [("Короткая история", "3d", {
        "voice": "elevenlabs", "music": None, "environment": "forest", "cast": "ranger_knight",
    })]


def test_long_advanced_summary_keeps_arrow_and_full_accessible_selection(window):
    window.mode.set_value("3d")
    for key, value in (("voice", "chatterbox"), ("environment", "forest"), ("cast", "ranger_knight")):
        box = window._choices[key]
        box.setCurrentIndex(box.findData(value))
    button = window.advanced_button
    button.resize(220, 40)
    for expanded, arrow in ((False, "▸"), (True, "▾")):
        button.setChecked(expanded)
        displayed = button.display_text()
        assert "…" in displayed and displayed.endswith(f"  {arrow}")
        assert button.fontMetrics().horizontalAdvance(displayed) <= button.width()
        assert button.toolTip() == button.accessibleName() == button.text()
        assert "Chatterbox, локально, Лесная поляна, Лучник и рыцарь" in button.toolTip()


def test_own_music_path_and_dialog_cancel_preserve_choice(window, monkeypatch):
    monkeypatch.setattr(shell.QFileDialog, "getOpenFileName", lambda *args: ("C:/music/own.wav", ""))
    box = window._choices["music"]
    browse = box.findData(shell._BROWSE)
    box.setCurrentIndex(browse)
    box.activated.emit(browse)
    assert window.options()["music"] == "C:/music/own.wav"
    monkeypatch.setattr(shell.QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    browse = box.findData(shell._BROWSE)
    box.setCurrentIndex(browse)
    box.activated.emit(browse)
    assert window.options()["music"] == "C:/music/own.wav"


def test_render_locks_all_choices_and_unlocks_after_error(window):
    window.mode.set_value("3d")
    window.set_generating()
    assert not any(box.isEnabled() for box in window._choices.values())
    window.set_error("Ошибка")
    assert all(box.isEnabled() for box in window._choices.values())
