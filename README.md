# AI Content Generator

Makes faceless vertical short videos (YouTube Shorts / TikTok / Instagram Reels) from a niche:

1. **Trend research** – Claude searches the web for what's trending now (hashtags, sounds, formats, platform rules)
2. **Script + post copy** – Claude writes the script and platform-specific titles, captions and hashtags
3. **Voiceover** – free Microsoft neural voices via `edge-tts`, with word timings
4. **Footage** – free vertical stock clips from Pexels
5. **Render** – 1080×1920 video with slow zoom, pop-in captions, optional background music
6. **Publish** – auto-upload to YouTube; a `POSTING_GUIDE.md` with copy-paste captions for TikTok and Instagram

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # then fill in the keys
```

- `ANTHROPIC_API_KEY` – from https://console.anthropic.com. Web search must be enabled for your org (Console → Settings → Privacy/Features).
- `PEXELS_API_KEY` – free from https://www.pexels.com/api/
- **Music (optional):** drop royalty-free `.mp3` files into `assets/music/` (e.g. from the YouTube Audio Library). One is picked at random per video.

FFmpeg is bundled through `imageio-ffmpeg`, so you don't need to install it separately.

## Usage

```powershell
# Let it pick a trending topic in the niche
.\.venv\Scripts\python -m acg make --niche "mind-blowing animal facts"

# Specific topic, upload to YouTube as private
.\.venv\Scripts\python -m acg make --niche "space facts" --topic "why Venus spins backwards" --upload

# Schedule a public YouTube release (UTC)
.\.venv\Scripts\python -m acg make --niche "money tips" --upload --publish-at 2026-10-06T17:00:00Z
```

Each run creates `output/<date>-<topic>/` containing:
- `video.mp4` – the finished video
- `POSTING_GUIDE.md` – titles, captions and hashtags for each platform, best posting times, trend notes, checklist
- `package.json` – everything Claude generated · `research.md` – the raw trend research

Options: `--seconds 45`, `--voice en-US-AndrewNeural` (list voices: `.\.venv\Scripts\edge-tts --list-voices`), `--no-research`, `--privacy private|unlisted|public`, `--keep-temp`.

## YouTube setup (one time)

1. Go to https://console.cloud.google.com, create a project, enable **YouTube Data API v3**.
2. **OAuth consent screen** → External → add your Google account as a **Test user**.
3. **Credentials** → Create credentials → **OAuth client ID** → *Desktop app* → download JSON, save it as `client_secret.json` in this folder.
4. The first `--upload` opens a browser to sign in; the token is cached in `token.json`.

Notes: the default API quota allows about 6 uploads/day. Videos from unverified API projects may be locked as private until Google audits the project, so upload as private and publish from YouTube Studio if that happens.

## TikTok and Instagram

These are posted by hand. Open the video's `POSTING_GUIDE.md` and copy the caption. Turn on each platform's AI-content label, as the checklist in the guide says.

## Cost

Roughly $0.05–0.20 per video in Claude API usage, mostly the web-search research step. Voice, footage and rendering are free.
