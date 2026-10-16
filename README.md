# AI Content Generator

Makes faceless vertical short videos (YouTube Shorts / TikTok / Instagram Reels) from a niche:

1. **Trend research** – pulls the most-viewed recent Shorts in your niche from YouTube (their hashtags and tags), plus optional Gemini web search (`ACG_WEB_SEARCH=1`, which isn't included in Gemini's free tier)
2. **Script + post copy** – Gemini writes the script and platform-specific titles, captions and hashtags
3. **Voiceover** – free Microsoft neural voices via `edge-tts`, with word timings
4. **Visuals** – AI 3D cartoon images (Cloudflare Workers AI, free daily allowance) with the same character in every scene, or free stock clips from Pixabay/Pexels
5. **Render** – 1080×1920 video with slow zoom in/out, pop-in captions, a purple title card for the first 3 seconds and then a small title bar for the rest of the video (so any frame YouTube picks as the thumbnail shows the title; `--no-title-bar` turns it off), optional background music. After upload, a custom thumbnail with the title is set too (needs a phone-verified channel)
6. **Publish** – auto-upload to YouTube; a `POSTING_GUIDE.md` with copy-paste captions for TikTok and Instagram

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # then fill in the keys
```

All keys are free and none needs a credit card:

- `GEMINI_API_KEY` – required. Get it from https://aistudio.google.com/apikey
- `PIXABAY_API_KEY` – recommended, for stock footage. Sign up at https://pixabay.com and the key appears on https://pixabay.com/api/docs/ (`PEXELS_API_KEY` also works, but new Pexels keys are paused)
- `YT_API_KEY` – recommended, for trend data. Use the same Google Cloud project as the YouTube setup below: Credentials → Create credentials → **API key**
- **Music (optional):** drop royalty-free `.mp3` files into `assets/music/` (e.g. from the YouTube Audio Library). One is picked at random per video.

FFmpeg is bundled through `imageio-ffmpeg`, so you don't need to install it separately.

## Usage

```powershell
# Fun facts - let it pick a trending topic
.\.venv\Scripts\python -m acg make --niche "fun facts"

# Short inspiring story
.\.venv\Scripts\python -m acg make --niche "short inspiring stories" --style story

# Specific topic, upload to YouTube as private
.\.venv\Scripts\python -m acg make --niche "fun facts" --topic "weird facts about octopuses" --upload

# Review first, then upload a finished video folder
.\.venv\Scripts\python -m acg upload output\20261006-011706-parable-the-old-carpenter --privacy public

# Schedule a public YouTube release (UTC)
.\.venv\Scripts\python -m acg make --niche "short inspiring stories" --style story --upload --publish-at 2026-10-07T17:00:00Z
```

Each run creates `output/<date>-<topic>/` containing:
- `video.mp4` – the finished video
- `POSTING_GUIDE.md` – titles, captions and hashtags for each platform, best posting times, trend notes, checklist
- `package.json` – everything Gemini generated · `research.md` – the raw trend research

Options: `--style facts|story`, `--seconds 45`, `--voice en-US-AndrewNeural` (list voices: `.\.venv\Scripts\edge-tts --list-voices`), `--no-research`, `--privacy private|unlisted|public`, `--keep-temp`.

## Daily automation (GitHub Actions, free)

`.github/workflows/daily.yml` runs twice a day:

| Runs at (Manila) | Makes | Goes public on YouTube |
|---|---|---|
| 06:00 | fun facts | 08:00 |
| 18:00 | inspiring story | 20:00 |
| Saturday 10:00 | LogExpense ad (~30s), starting Oct 17 (`ADS_START_DATE` in the workflow) | Saturday 12:00 |

Each run uploads the video with a YouTube scheduled publish time, so it goes live exactly on the hour even if GitHub starts the run late. `history.json` is committed after each run so topics don't repeat. For TikTok/Instagram, open the run under the repo's **Actions** tab: the posting guide is shown on the run page, and the video is under **Artifacts** (kept 14 days).

Setup: GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**, add:

- `GEMINI_API_KEY`, `PIXABAY_API_KEY` (and `YT_API_KEY` once you have it)
- `YT_TOKEN_JSON` – the full contents of your local `token.json` (created by the first local `--upload`)

Before creating `token.json`, set the OAuth app to **In production** (Google Cloud → Google Auth Platform → Audience → **Publish app**). Apps left in *Testing* get refresh tokens that expire after 7 days, which would break the daily uploads. No verification is needed for your own channel.

To test without waiting: Actions → **Daily videos** → **Run workflow** (choose style, upload on/off).

About half of the videos (picked at random) end with a ~5s call to action, spoken and shown on screen, picked from 12 variations ("Follow for more videos like this!", "Hit follow so you don't miss the next one!", "Enjoyed this? Follow for more!", ...). An ending isn't reused until at least 6 other endings have been used. Change the phrases with `ACG_OUTROS` (separated by `|`) and the chance with `ACG_OUTRO_CHANCE` (default `0.5`). Use `--outro` to force it, or `--no-outro` to skip it.

## Weekly product ad (LogExpense)

Every Saturday the workflow makes a ~30s ad for [logexpense.site](https://logexpense.site) using `--style ad`. The script is written only from the product brief in [ads/logexpense.md](ads/logexpense.md), so ads never claim features that don't exist. **Update that file when the app changes** (new features, iOS launch, paid plans going live). Each week picks a different angle (audience, problem, feature) from `history.json`, and every ad ends with "Try it free at LOGEXPENSE.SITE". Captions say "Link in bio", so keep logexpense.site as the link in your TikTok and Instagram bios.

Run one by hand:
```powershell
.\.venv\Scripts\python -m acg make --style ad --niche "budgeting tips" --brief ads/logexpense.md --website logexpense.site --cta-voice "Try it free at log expense dot site." --seconds 30
```

## Phone delivery (Telegram, free)

After each video is made, a Telegram bot sends you the video (tap it, then **Save to gallery**) and the TikTok and Instagram captions as separate messages (tap to copy), so you can post from your phone.

1. In Telegram, open **@BotFather**, send `/newbot`, and pick a name and a username ending in `bot`. Copy the token it gives you into `.env` as `TELEGRAM_BOT_TOKEN`.
2. Open your new bot (BotFather links to it), press **Start**, and send it any message.
3. Run `.\.venv\Scripts\python -m acg telegram-setup`, which prints your chat id. Put it in `.env` as `TELEGRAM_CHAT_ID`.
4. Add both as GitHub secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

The bot also alerts you when something breaks: **❌** when a video fails (which step, the likely cause and how to fix it, plus a link to the log), **⚠️** when a video was made but something was degraded (e.g. trend data or footage failed), and a setup-failure alert if the GitHub run breaks before the video code starts.

## AI images setup (one time, free)

1. Sign up at https://dash.cloudflare.com/sign-up (free plan, no card needed).
2. **Account ID:** on the dashboard home, open the account menu (or Workers & Pages) → copy **Account ID** → `CF_ACCOUNT_ID`.
3. **API token:** My Profile → **API Tokens** → Create Token → **Workers AI** template → Create → copy it → `CF_API_TOKEN`.

The free plan gives 10,000 "neurons" per day, which by Cloudflare's published rates should be enough for several videos a day. If the allowance runs out partway through a video, the remaining scenes use stock footage.

Options: `--visuals ai` (default is `stock`), `--seed 7` (change it to get a different-looking character), `--caption-style bold` (one big word + title card).

## YouTube setup (one time)

1. Go to https://console.cloud.google.com, create a project, enable **YouTube Data API v3**.
2. **OAuth consent screen** → External → add your Google account as a **Test user**.
3. **Credentials** → Create credentials → **OAuth client ID** → *Desktop app* → download JSON, save it as `client_secret.json` in this folder.
4. The first `--upload` opens a browser to sign in; the token is cached in `token.json`.

Notes: the default API quota allows about 6 uploads/day. Videos from unverified API projects may be locked as private until Google audits the project, so upload as private and publish from YouTube Studio if that happens.

## TikTok and Instagram

These are posted by hand. Open the video's `POSTING_GUIDE.md` and copy the caption. Turn on each platform's AI-content label, as the checklist in the guide says.

## Cost

Free. Everything runs on free tiers: Gemini, Pixabay, the YouTube Data API, edge-tts and local FFmpeg. Google's free-tier limits for Gemini change over time, so check https://aistudio.google.com if you hit a quota error. Gemini's free tier doesn't include Google Search, so web search is off by default and the trend data comes from YouTube. If a free model is busy, the tool retries with another one.
