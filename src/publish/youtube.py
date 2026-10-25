"""Upload a rendered MP4 to YouTube Shorts (YouTube Data API v3, OAuth for a desktop app).

The OAuth client file comes from Google Cloud (Desktop app) and stays outside the
repository: WIBECODE_YT_CLIENT_SECRET or ~/.shortsstudio/client_secret.json. On the
first upload a browser asks for access; the token is kept in ~/.shortsstudio.
A vertical video up to 3 minutes becomes a Short automatically.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable, Optional

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CONFIG_DIR = Path.home() / ".shortsstudio"
CLIENT_SECRET_ENV = "WIBECODE_YT_CLIENT_SECRET"
PRIVACY = ("private", "unlisted", "public")
TITLE_MAX, DESCRIPTION_MAX = 100, 5000
CHUNK = 8 * 1024 * 1024

# upload_progress(sent_bytes, total_bytes)
UploadProgress = Callable[[int, int], None]


class PublishError(RuntimeError):
    """The video could not be published. Message is user-readable."""


def client_secret_path() -> Path:
    return Path(os.environ.get(CLIENT_SECRET_ENV) or CONFIG_DIR / "client_secret.json")


def token_path() -> Path:
    return CONFIG_DIR / "youtube_token.json"


def make_title(text: str) -> str:
    """First non-empty line, without "<" ">" (rejected by YouTube), cut to 100 chars on a word."""
    line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    line = re.sub(r"\s+", " ", line.replace("<", "").replace(">", "")).strip()
    if len(line) > TITLE_MAX:
        line = line[: TITLE_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,.;:—-") + "…"
    return line or "Shorts"


def _credentials(secret: Path, token: Path):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.is_file() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:  # tokens of apps in "Testing" expire after 7 days
            creds = None
    if not (creds and creds.valid):
        if not secret.is_file():
            raise PublishError(
                f"Не найден файл OAuth-клиента YouTube: {secret}. Скачайте JSON клиента "
                f"Desktop app из Google Cloud и положите его туда или укажите путь в "
                f"{CLIENT_SECRET_ENV}."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
        creds = flow.run_local_server(
            port=0, open_browser=True,
            success_message="Доступ к YouTube получен, вернитесь в приложение.",
        )  # fmt: skip
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    try:
        token.chmod(0o600)
    except OSError:
        pass
    return creds


def _explain(error) -> str:
    """Turn a googleapiclient HttpError into a readable message."""
    try:
        details = json.loads(error.content.decode("utf-8"))["error"]
        reason = (details.get("errors") or [{}])[0].get("reason", "")
        message = details.get("message", "")
    except (ValueError, KeyError, AttributeError):
        reason, message = "", str(error)
    status = getattr(error.resp, "status", 0)
    if reason in ("quotaExceeded", "rateLimitExceeded", "dailyLimitExceeded"):
        return "Дневная квота YouTube API исчерпана (около 6 загрузок в день). Попробуйте завтра."
    if reason == "uploadLimitExceeded":
        return "YouTube ограничил загрузки для этого канала. Попробуйте позже."
    if reason == "youtubeSignupRequired":
        return "У этого Google-аккаунта нет YouTube-канала. Создайте канал и повторите."
    if status in (401, 403):
        return f"Нет доступа к YouTube ({reason or status}): войдите заново или проверьте проект в Google Cloud. {message}"
    return f"Ошибка YouTube API ({status} {reason}): {message}".strip()


def upload(
    video_path: str,
    title: str,
    description: str = "",
    privacy: str = "private",
    *,
    on_progress: Optional[UploadProgress] = None,
    service=None,
) -> str:
    """Upload video_path and return its Shorts URL. Raises PublishError.

    Until the Google Cloud project passes the YouTube API audit, YouTube keeps every
    uploaded video private whatever privacy is requested.
    """
    path = Path(video_path)
    if not path.is_file():
        raise PublishError(f"Видео не найдено: {video_path}")
    if privacy not in PRIVACY:
        raise PublishError(f"privacy должен быть одним из {', '.join(PRIVACY)}")

    from google.auth.exceptions import GoogleAuthError
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    from httplib2 import HttpLib2Error

    try:
        if service is None:
            from googleapiclient.discovery import build

            creds = _credentials(client_secret_path(), token_path())
            service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        body = {
            "snippet": {
                "title": make_title(title),
                "description": description[:DESCRIPTION_MAX],
                "categoryId": "22",  # People & Blogs
            },
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=CHUNK, resumable=True)
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)
        size, response = path.stat().st_size, None
        while response is None:
            status, response = request.next_chunk()
            if status is not None and on_progress is not None:
                on_progress(min(status.resumable_progress, size - 1), size)
    except HttpError as e:
        raise PublishError(_explain(e)) from None
    except (OSError, HttpLib2Error) as e:  # network, local OAuth server
        raise PublishError(f"Не удалось связаться с YouTube: {e}") from None
    except GoogleAuthError as e:
        raise PublishError(f"Не удалось войти в Google: {e}") from None
    except ValueError as e:  # malformed client_secret.json
        raise PublishError(f"Файл OAuth-клиента {client_secret_path()} повреждён: {e}") from None
    if on_progress is not None:
        on_progress(size, size)
    return f"https://youtube.com/shorts/{response['id']}"
