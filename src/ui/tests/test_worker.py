"""RenderWorker: YouTube metadata arrives before the render and never blocks it."""

from types import SimpleNamespace

from src.ui import stubs, worker


def run_worker(monkeypatch, generate_metadata):
    rendered = []

    def render_video(spec, out_path, *, on_progress=None):
        rendered.append(out_path)
        return out_path

    monkeypatch.setattr(worker, "api", SimpleNamespace(**{**vars(stubs.api), "render_video": render_video}))
    monkeypatch.setattr(
        worker, "llm", SimpleNamespace(**{**vars(stubs.llm), "generate_metadata": generate_metadata})
    )
    render = worker.RenderWorker("Ролик про рост продаж", "out.mp4", "2d")
    events = []
    render.metadata.connect(lambda text, ok: events.append(("metadata", text, ok)))
    render.finished.connect(lambda path: events.append(("finished", path)))
    render.failed.connect(lambda message: events.append(("failed", message)))
    render.run()
    return events, rendered


def test_metadata_is_emitted_before_the_video(monkeypatch):
    events, rendered = run_worker(monkeypatch, stubs.generate_metadata)

    assert [event[0] for event in events] == ["metadata", "finished"]
    _, text, ok = events[0]
    assert ok and "Ролик про рост продаж" in text and "#Shorts" in text
    assert rendered == ["out.mp4"]


def test_metadata_failure_does_not_stop_the_render(monkeypatch):
    def unavailable(user_text, spec_json):
        raise stubs.LLMError("Нет соединения с API, проверьте интернет.")

    events, rendered = run_worker(monkeypatch, unavailable)

    assert events == [
        (
            "metadata",
            "Не удалось подготовить название, описание и теги: "
            "Нет соединения с API, проверьте интернет.",
            False,
        ),
        ("finished", "out.mp4"),
    ]
    assert rendered == ["out.mp4"]
