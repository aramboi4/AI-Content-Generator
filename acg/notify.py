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


# ---- health alerts -------------------------------------------------------------------------

STAGES = {
    "research": "YouTube trend lookup",
    "script": "writing the script (Gemini)",
    "voice": "voiceover (edge-tts)",
    "footage": "stock footage (Pixabay)",
    "render": "video rendering (FFmpeg)",
    "upload": "YouTube upload",
}


def diagnose(stage: str, exc: BaseException) -> tuple[str, str]:
    """Best guess at which service broke and what to do about it."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if "invalid_grant" in text or "refresherror" in text or "token is missing or revoked" in text:
        return ("🔑 YouTube login expired or was revoked",
                "On the laptop: delete token.json, run any 'acg make ... --upload' to sign in again, then paste "
                "the new token.json into the YT_TOKEN_JSON GitHub secret.")
    if "quotaexceeded" in text or ("quota" in text and stage in ("upload", "research")):
        return ("YouTube daily API quota used up", "It resets at midnight Pacific time - the next run should work.")
    if "uploadlimitexceeded" in text:
        return ("YouTube upload limit reached for the channel", "Wait 24 hours; YouTube limits uploads per day.")
    if stage == "script" or "genai" in text or "gemini" in text:
        if "429" in text or "resource_exhausted" in text:
            return ("Gemini free-tier limit reached", "Usually resets within a day. If it keeps happening, check "
                    "limits at https://aistudio.google.com")
        if "404" in text or "not_found" in text:
            return ("Gemini model retired", "Google removed the model - set ACG_MODEL to a current one (ask Claude).")
        if "api key" in text or "permission" in text or "401" in text or "403" in text:
            return ("Gemini API key rejected", "Create a new key at https://aistudio.google.com/apikey and update "
                    "GEMINI_API_KEY in .env and GitHub secrets.")
        return ("Gemini (script writer) error", "Often temporary (servers busy). If it repeats, check the log.")
    if stage == "voice":
        return ("Voice service (edge-tts) not responding", "Usually temporary or blocked by Microsoft; a library "
                "update normally fixes it within days. If it repeats for 2+ days, ask Claude to switch voices.")
    if stage == "footage":
        return ("Pixabay footage error", "Check the key at https://pixabay.com/api/docs/ (PIXABAY_API_KEY).")
    if stage == "render":
        return ("Video rendering (FFmpeg) failed", "Likely a code issue - send the log to Claude.")
    if stage == "upload":
        return ("YouTube upload failed", "Check YouTube Studio and the log; the video is still in the GitHub run.")
    return ("Unexpected error", "Send the log to Claude.")


def _run_link() -> str:
    import os
    if os.getenv("GITHUB_RUN_ID"):
        return f"{os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
    return ""


def send_failure(what: str, stage: str, exc: BaseException) -> None:
    problem, fix = diagnose(stage, exc)
    link = _run_link()
    _send_text(f"❌ <b>{html.escape(what)} failed</b>\n"
               f"Step: {html.escape(STAGES.get(stage, stage))}\n"
               f"Problem: {html.escape(problem)}\n"
               f"Fix: {html.escape(fix)}\n\n"
               f"<code>{html.escape(f'{type(exc).__name__}: {exc}'[:500])}</code>"
               + (f'\n\n<a href="{link}">Open the full log</a>' if link else ""))


def send_warnings(what: str, warnings: list[str]) -> None:
    _send_text(f"⚠️ <b>{html.escape(what)}: made, with warnings</b>\n" +
               "\n".join(f"• {html.escape(w)}" for w in warnings))
