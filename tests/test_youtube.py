"""YouTube publishing without network: a fake service stands in for the API."""

import json

import httplib2
import pytest
from googleapiclient.errors import HttpError

from src.publish import youtube


class _Status:
    def __init__(self, sent, total):
        self.resumable_progress, self.total_size = sent, total


class _Request:
    def __init__(self, steps):
        self._steps = list(steps)

    def next_chunk(self):
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _Service:
    def __init__(self, steps):
        self.steps, self.calls = steps, []

    def videos(self):
        return self

    def insert(self, **kwargs):
        self.calls.append(kwargs)
        return _Request(self.steps)


def _http_error(status, reason, message="boom"):
    content = json.dumps({"error": {"message": message, "errors": [{"reason": reason}]}})
    return HttpError(httplib2.Response({"status": status}), content.encode())


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "short.mp4"
    path.write_bytes(b"\0" * 1000)
    return path


def test_upload_sends_metadata_and_reports_progress(video):
    service = _Service([(_Status(400, 1000), None), (_Status(1000, 1000), None), (None, {"id": "abc123"})])
    calls = []
    url = youtube.upload(str(video), "Рост продаж\nподробности", "описание", tags=("продажи", "итоги года"),
                         on_progress=lambda s, t: calls.append((s, t)), service=service)
    assert url == "https://youtube.com/shorts/abc123"
    body = service.calls[0]["body"]
    assert body["snippet"]["title"] == "Рост продаж"
    assert body["snippet"]["description"] == "описание"
    assert body["snippet"]["tags"] == ["продажи", "итоги года"]
    assert body["status"]["privacyStatus"] == "private"
    assert service.calls[0]["part"] == "snippet,status"
    assert calls == [(400, 1000), (999, 1000), (1000, 1000)]


@pytest.mark.parametrize("reason, words", [
    ("quotaExceeded", "квота"),
    ("youtubeSignupRequired", "канала"),
    ("forbidden", "Нет доступа"),
])
def test_api_errors_become_readable_publish_errors(video, reason, words):
    service = _Service([_http_error(403, reason)])
    with pytest.raises(youtube.PublishError) as caught:
        youtube.upload(str(video), "x", service=service)
    assert words in str(caught.value)


def test_missing_video_and_bad_privacy(video, tmp_path):
    with pytest.raises(youtube.PublishError, match="не найдено"):
        youtube.upload(str(tmp_path / "nope.mp4"), "x", service=_Service([]))
    with pytest.raises(youtube.PublishError, match="privacy"):
        youtube.upload(str(video), "x", privacy="secret", service=_Service([]))


def test_missing_client_secret_is_explained(video, tmp_path, monkeypatch):
    monkeypatch.setenv(youtube.CLIENT_SECRET_ENV, str(tmp_path / "absent.json"))
    monkeypatch.setattr(youtube, "CONFIG_DIR", tmp_path / "cfg")
    with pytest.raises(youtube.PublishError) as caught:
        youtube.upload(str(video), "x")
    assert "absent.json" in str(caught.value)
    assert youtube.CLIENT_SECRET_ENV in str(caught.value)


@pytest.mark.parametrize("text, expected", [
    ("  \n Заголовок <b>ролика</b>  \nвторая строка", "Заголовок bролика/b"),
    ("", "Shorts"),
    ("слово " * 40, ("слово " * 16).strip() + "…"),
])
def test_make_title(text, expected):
    title = youtube.make_title(text)
    assert title == expected
    assert len(title) <= youtube.TITLE_MAX


def test_first_upload_runs_oauth_once_and_keeps_token(video, tmp_path, monkeypatch):
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = tmp_path / "client_secret.json"
    secret.write_text(json.dumps({"installed": {
        "client_id": "id.apps.googleusercontent.com", "client_secret": "s",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"],
    }}))
    monkeypatch.setenv(youtube.CLIENT_SECRET_ENV, str(secret))
    monkeypatch.setattr(youtube, "CONFIG_DIR", tmp_path / "cfg")
    logins = []

    def fake_login(self, **kwargs):
        logins.append(kwargs)
        return Credentials("token", refresh_token="r", token_uri="https://oauth2.googleapis.com/token",
                           client_id="id", client_secret="s", scopes=youtube.SCOPES,
                           expiry=__import__("datetime").datetime(2999, 1, 1))

    monkeypatch.setattr(InstalledAppFlow, "run_local_server", fake_login)
    monkeypatch.setattr("googleapiclient.discovery.build",
                        lambda *a, **k: _Service([(None, {"id": "v1"})]))
    assert youtube.upload(str(video), "x").endswith("/v1")
    assert youtube.upload(str(video), "x").endswith("/v1")
    assert len(logins) == 1  # the second upload reused the saved token
    assert (tmp_path / "cfg" / "youtube_token.json").is_file()
