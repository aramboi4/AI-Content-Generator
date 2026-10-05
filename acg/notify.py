"""Send each finished video + its captions to your phone via a free Telegram bot."""
import html
from pathlib import Path

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .writer import VideoPackage

MAX_VIDEO_BYTES = 49 * 1024 * 1024  # bot upload limit is 50 MB


def enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _api(method: str, **kwargs) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", timeout=300, **kwargs)
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
    return body["result"]


def _send_text(text: str) -> None:
    _api("sendMessage", data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                              "disable_web_page_preview": "true"})


def send_video(video: Path, pkg: VideoPackage, youtube_url: str | None = None, when: str | None = None) -> None:
    title = html.escape(pkg.tiktok.on_screen_title)
    yt = f"\nYouTube: {youtube_url}" + (f" (goes public {when})" if when else "") if youtube_url else ""
    header = f"🎬 <b>{title}</b>\n{html.escape(pkg.topic)}{html.escape(yt)}"
    if video.stat().st_size <= MAX_VIDEO_BYTES:
        with open(video, "rb") as f:
            _api("sendVideo", data={"chat_id": TELEGRAM_CHAT_ID, "caption": header, "parse_mode": "HTML",
                                    "supports_streaming": "true", "width": 1080, "height": 1920},
                 files={"video": (video.name, f, "video/mp4")})
    else:
        _send_text(header + "\n⚠️ Video is over 50 MB - download it from the GitHub Actions run instead.")
    # Each caption in its own message inside <code>, so one tap copies it.
    _send_text(f"📱 <b>TikTok caption</b> (tap to copy)\n<code>{html.escape(pkg.tiktok.full_caption())}</code>")
    _send_text(f"📸 <b>Instagram caption</b> (tap to copy)\n<code>{html.escape(pkg.instagram.full_caption())}</code>")
    _send_text("✅ Cover: pick the first frame (title is on it). Turn on the AI-content label on both apps.")


def find_chat_id() -> str | None:
    """Chat id of the most recent message sent to the bot (used once during setup)."""
    updates = _api("getUpdates")
    chats = [u["message"]["chat"] for u in updates if "message" in u]
    return str(chats[-1]["id"]) if chats else None
