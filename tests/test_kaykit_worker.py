"""UI choices reach the model and mismatching JSON never reaches Blender."""

import json

import pytest

from src.ui import worker


def run_selection(monkeypatch, returned):
    requests, rendered, finished, failures = [], [], [], []

    def generate_spec(text, client=None):
        requests.append(text)
        return json.dumps(returned)

    def render_video(spec, out_path, *, on_progress=None):
        rendered.append((spec.environment, spec.cast))
        return out_path

    monkeypatch.setattr(worker.llm, "connect", lambda base_url, api_key: None)
    monkeypatch.setattr(worker.llm, "generate_spec", generate_spec)
    monkeypatch.setattr(worker.api, "render_video", render_video)
    monkeypatch.setattr(worker.RenderWorker, "_emit_metadata", lambda self, raw: None)
    render = worker.RenderWorker(
        "История", "out.mp4", "3d", environment="forest", cast="ranger_knight",
    )
    render.finished.connect(finished.append)
    render.failed.connect(failures.append)
    render.run()
    return requests, rendered, finished, failures


@pytest.fixture
def selected_spec():
    return {
        "duration": 2, "render_mode": "3d", "environment": "forest", "cast": "ranger_knight",
        "scenes": [
            {"type": "say", "who": "robot", "shot": "wide", "text": "Привет!", "start": 0, "end": 2},
        ],
    }


def test_selected_environment_and_pair_are_hinted_before_generation(monkeypatch, selected_spec):
    requests, rendered, finished, failures = run_selection(monkeypatch, selected_spec)
    assert requests == [
        'История\n\nrender_mode: "3d"\nenvironment: "forest"\ncast: "ranger_knight"'
    ]
    assert rendered == [("forest", "ranger_knight")]
    assert finished == ["out.mp4"]
    assert not failures


@pytest.mark.parametrize("field,value", [("environment", "room"), ("cast", "classic")])
def test_mismatching_model_choices_stop_before_render(monkeypatch, selected_spec, field, value):
    selected_spec[field] = value
    _, rendered, finished, failures = run_selection(monkeypatch, selected_spec)
    assert not rendered and not finished
    assert len(failures) == 1 and "другое окружение или персонажей" in failures[0]
    assert selected_spec[field] == value


@pytest.mark.parametrize("field", ["environment", "cast"])
def test_unknown_model_choices_are_rejected_before_render(monkeypatch, selected_spec, field):
    selected_spec[field] = "unavailable"
    _, rendered, finished, failures = run_selection(monkeypatch, selected_spec)
    assert not rendered and not finished
    assert len(failures) == 1 and field in failures[0]
    assert "Ошибка спецификации" in failures[0]
