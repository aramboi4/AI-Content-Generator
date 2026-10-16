"""Upload a Short to YouTube via the Data API (OAuth, token cached in token.json)."""
import os
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
    if not YT_TOKEN.exists() and os.getenv("YT_TOKEN_JSON"):  # CI: token comes from a secret
        YT_TOKEN.write_text(os.environ["YT_TOKEN_JSON"], encoding="utf-8")
    creds = Credentials.from_authorized_user_file(str(YT_TOKEN), SCOPES) if YT_TOKEN.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if os.getenv("CI"):
            raise RuntimeError("YouTube token is missing or revoked - re-run the local sign-in and update the YT_TOKEN_JSON secret.")
        if not YT_CLIENT_SECRET.exists():
            raise FileNotFoundError("client_secret.json not found - see README 'YouTube setup'.")
        creds = InstalledAppFlow.from_client_secrets_file(str(YT_CLIENT_SECRET), SCOPES).run_local_server(port=0)
    YT_TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


LAST_THUMBNAIL_ERROR: str | None = None  # set when the custom thumbnail couldn't be applied


def _set_thumbnail(yt, video_id: str, thumbnail: Path) -> None:
    """Custom thumbnail so YouTube shows the title card instead of a random mid-video frame.
    Only works on channels with custom thumbnails enabled (phone-verified); never fails the upload."""
    global LAST_THUMBNAIL_ERROR
    LAST_THUMBNAIL_ERROR = None
    try:
        yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
    except Exception as e:
        text = str(e)
        if "forbidden" in text.lower() or "403" in text:
            LAST_THUMBNAIL_ERROR = ("YouTube refused the custom thumbnail - custom thumbnails need a phone-verified "
                                    "channel: https://www.youtube.com/verify")
        else:
            LAST_THUMBNAIL_ERROR = f"Custom thumbnail failed: {text[:150]}"
        print(f"    {LAST_THUMBNAIL_ERROR}")


def upload(video: Path, post: YouTubePost, privacy: str = "private", publish_at: str | None = None,
           thumbnail: Path | None = None) -> str:
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
    if thumbnail and thumbnail.exists():
        _set_thumbnail(yt, resp["id"], thumbnail)
    return f"https://youtube.com/shorts/{resp['id']}"
