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


def run_with_music(monkeypatch, music, mood="lofi", bundled=None):
    """Worker on stubs; records which track add_music got and what import_music copied."""
    calls = {"added": [], "imported": []}
    library = []

    def import_music(path):
        calls["imported"].append(path)
        library.append(f"/library/{path.rsplit('/', 1)[-1]}")
        return library[-1]

    fake_api = SimpleNamespace(**{
        **vars(stubs.api),
        "render_video": lambda spec, out_path, *, on_progress=None: out_path,
        "pick_music": lambda m: bundled if m == mood else None,
        "user_music": lambda: list(library),
        "import_music": import_music,
        "add_music": lambda video, track, out_path=None: calls["added"].append(track),
    })
    monkeypatch.setattr(worker, "api", fake_api)
    monkeypatch.setattr(worker, "llm", stubs.llm)
    real_parse = stubs.api.parse_spec
    monkeypatch.setattr(
        fake_api, "parse_spec", lambda raw: SimpleNamespace(**{**vars(real_parse(raw)), "music": mood})
    )
    render = worker.RenderWorker("Ролик", "out.mp4", "2d", None, music)
    events = []
    render.finished.connect(lambda path: events.append("finished"))
    render.failed.connect(lambda message: events.append(message))
    render.run()
    return events, calls


def test_auto_music_uses_the_mood_from_the_model(monkeypatch):
    events, calls = run_with_music(monkeypatch, "auto", bundled="/assets/music/lofi/a.mp3")
    assert events == ["finished"]
    assert calls == {"added": ["/assets/music/lofi/a.mp3"], "imported": []}


def test_own_file_is_kept_in_the_users_tracks(monkeypatch):
    events, calls = run_with_music(monkeypatch, "/home/me/Песня.mp3")
    assert events == ["finished"]
    assert calls == {"added": ["/library/Песня.mp3"], "imported": ["/home/me/Песня.mp3"]}


def test_no_music_and_empty_mood_leave_audio_alone(monkeypatch):
    assert run_with_music(monkeypatch, None)[1]["added"] == []
    assert run_with_music(monkeypatch, "auto", bundled=None)[1]["added"] == []
