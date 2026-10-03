"""Upload a Short to YouTube via the Data API (OAuth, token cached in token.json)."""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import YT_CATEGORY_ID, YT_CLIENT_SECRET, YT_TOKEN
from .writer import YouTubePost

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _credentials() -> Credentials:
    creds = Credentials.from_authorized_user_file(str(YT_TOKEN), SCOPES) if YT_TOKEN.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not YT_CLIENT_SECRET.exists():
            raise FileNotFoundError("client_secret.json not found - see README 'YouTube setup'.")
        creds = InstalledAppFlow.from_client_secrets_file(str(YT_CLIENT_SECRET), SCOPES).run_local_server(port=0)
    YT_TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload(video: Path, post: YouTubePost, privacy: str = "private", publish_at: str | None = None) -> str:
    """Returns the video URL. publish_at (ISO 8601 UTC, e.g. 2026-10-05T17:00:00Z) schedules it."""
    status = {
        "privacyStatus": "private" if publish_at else privacy,
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,  # YouTube's AI/altered-content disclosure
    }
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {
            "title": post.title[:100],
            "description": post.description,
            "tags": post.tags,
            "categoryId": YT_CATEGORY_ID,
        },
        "status": status,
    }
    yt = build("youtube", "v3", credentials=_credentials())
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"https://youtube.com/shorts/{resp['id']}"
