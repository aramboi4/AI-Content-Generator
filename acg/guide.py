"""Writes POSTING_GUIDE.md: copy-paste titles, captions and hashtags for each platform."""
from pathlib import Path

from .writer import VideoPackage


def write_guide(pkg: VideoPackage, out: Path, youtube_url: str | None = None) -> None:
    yt, tt, ig = pkg.youtube, pkg.tiktok, pkg.instagram
    script = "\n".join(f"{i + 1}. {s.narration}" for i, s in enumerate(pkg.scenes))
    yt_status = f"Uploaded: {youtube_url}" if youtube_url else "Not uploaded - post manually or rerun with --upload."
    out.write_text(f"""# Posting guide: {pkg.topic}

Video file: `video.mp4`

## When to post
{pkg.best_posting_times}

## Trend notes
{pkg.trend_notes}

---

## TikTok (manual)
**Cover / on-screen title:** {tt.on_screen_title}

**Caption (copy-paste):**
```
{tt.caption}
```
Checklist:
- [ ] Turn on **"AI-generated content"** under More options before posting
- [ ] Optional: add a trending sound from the in-app library at low volume (~5-10%) under the voiceover
- [ ] Pick a cover frame and add the on-screen title as text

## Instagram Reels (manual)
**Cover / on-screen title:** {ig.on_screen_title}

**Caption (copy-paste):**
```
{ig.caption}
```
Checklist:
- [ ] Turn on the **AI label** (Advanced settings > "Add AI label")
- [ ] Share to Feed: on
- [ ] Optional: add trending audio from the Reels library at low volume

## YouTube Shorts
{yt_status}

**Title:** {yt.title}

**Description:**
```
{yt.description}
```
**Tags:** {", ".join(yt.tags)}

---

## Script
{script}
""", encoding="utf-8")
