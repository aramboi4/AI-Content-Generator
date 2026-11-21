# AI Content Generator

Makes faceless vertical short videos (YouTube Shorts / TikTok / Instagram Reels) from a niche:

1. **Trend research** – pulls the most-viewed recent Shorts in your niche from YouTube (their hashtags and tags), plus optional Gemini web search (`ACG_WEB_SEARCH=1`, which isn't included in Gemini's free tier)
2. **Script + post copy** – Gemini writes the script and platform-specific titles, captions and hashtags. If every Gemini model fails, Groq (`openai/gpt-oss-120b`, then `gpt-oss-20b`) and then GitHub Models (`gpt-4o-mini`, using the workflow's own token) take over, and Telegram says which one wrote it
3. **Voiceover** – Inworld's Clive or Dennis (picked at random) while free credits last, otherwise Kokoro `am_adam` (free, runs on the machine itself, can't be blocked), with Piper as a last resort. Microsoft's `edge-tts` voice is off (`ACG_USE_MICROSOFT_VOICE=1` to re-enable)
4. **Visuals** – an AI image for every line (Cloudflare Workers AI, free daily allowance): the same character throughout, in 3D cartoon or realistic style (`ACG_ART_STYLE=3d|realistic`). Gemini reviews each picture against its line and has it redrawn up to twice. Falls back to free stock clips from Pixabay/Pexels. Caption timing comes from Whisper listening to the voice
5. **Render** – 1080×1920 video with slow zoom in/out, one-word pop-in captions (Anton font), a purple title card, optional background music
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

## Branding (Daily Cup of Goodness)

- **Watermark:** the cup icon (`assets/brand/logo_icon.png`) sits small in the top-right corner until the ending. `--no-watermark` turns it off.
- **Ending card:** when a video has a follow-for-more ending, the full logo (`assets/brand/logo.png`) appears above it.
- **Comments prompt:** when the last line is a question, about half of the videos add one of several prompts such as "Let me know in the comments!" (`ACG_COMMENT_CTA_CHANCE`, default `0.5`). Those videos never get the follow-for-more ending.

To change the logo, replace `assets/brand/logo_original.png` and ask Claude to regenerate the transparent versions.

## Daily automation (GitHub Actions, free)

`.github/workflows/daily.yml` runs twice a day:

| Runs at (Manila) | Makes | Goes public on YouTube |
|---|---|---|
| 01:13 (retry 04:13) | fun facts | 08:00 |
| 13:13 (retry 16:13) | inspiring story | 20:00 |
| Saturday 05:13 (retry 08:13) | LogExpense ad (~30s) (pause with `ADS_PAUSED: "true"` in the workflow) | Saturday 12:00 |

GitHub starts scheduled runs 2-7 hours late, so these start about 7 hours before the slot and act as backups for the on-time runs below. A run that finishes before the slot schedules the YouTube video for the slot; a run that's later than that posts it right away (never the next day). The retry only makes a video if the first run didn't upload one. Telegram shows "📅 Post on TikTok/Instagram: <day, time>" for every video. `history.json` is committed after each run so topics don't repeat. For TikTok/Instagram, open the run under the repo's **Actions** tab: the posting guide is shown on the run page, and the video is under **Artifacts** (kept 2 days, then deleted by `cleanup.yml`).

Setup: GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**, add:

- `GEMINI_API_KEY`, `PIXABAY_API_KEY` (and `YT_API_KEY` once you have it)
- `YT_TOKEN_JSON` – the full contents of your local `token.json` (created by the first local `--upload`)

Before creating `token.json`, set the OAuth app to **In production** (Google Cloud → Google Auth Platform → Audience → **Publish app**). Apps left in *Testing* get refresh tokens that expire after 7 days, which would break the daily uploads. No verification is needed for your own channel.

To test without waiting: Actions → **Daily videos** → **Run workflow** (leave *run* on `manual`, choose style, upload on/off).

### On-time runs (cron-job.org, free)

GitHub's own schedules start late, so an outside cron service starts the runs at the exact time by calling GitHub's API. The GitHub schedules above stay as backups. Every automatic run first checks `history.json` and does nothing if that video was already uploaded in the last 9 hours, so a video is never made twice.

1. **GitHub token:** github.com → your photo → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**. Name it `cron-job`, set an expiration, **Repository access → Only select repositories → AI-Content-Generator**, **Permissions → Repository permissions → Actions: Read and write**. Copy the token.
2. **cron-job.org:** sign up free, then **Create cronjob** for each row below:
   - **URL:** `https://api.github.com/repos/aramboi4/AI-Content-Generator/actions/workflows/daily.yml/dispatches`
   - **Schedule:** the time below, time zone **Asia/Manila**
   - **Advanced → Request method:** `POST`
   - **Advanced → Headers:** `Authorization: Bearer <your token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
   - **Advanced → Request body:** `{"ref":"main","inputs":{"run":"facts"}}` (or `story` / `ad`)

| Job | Time (Manila) | Body `run` | Goes public |
|---|---|---|---|
| Fun facts | every day 05:30 | `facts` | 08:00 |
| Fun facts retry | every day 06:45 | `facts` | 08:00 |
| Story | every day 17:30 | `story` | 20:00 |
| Story retry | every day 18:45 | `story` | 20:00 |
| LogExpense ad | Saturday 09:30 | `ad` | 12:00 |
| LogExpense ad retry | Saturday 10:45 | `ad` | 12:00 |

A successful call returns status `204` (or `200`) and a new run appears under **Actions**. The retry jobs cost nothing when the first run worked: they see the upload and stop within a minute.

Videos that end on a statement (e.g. a story's lesson) get a ~5s follow-for-more ending, spoken and shown on screen, picked from 12 variations. Videos that end on a question stop there instead (sometimes adding a comments prompt), with no follow ending. The phrases come from 12 variations ("Follow for more videos like this!", "Hit follow so you don't miss the next one!", "Enjoyed this? Follow for more!", ...). An ending isn't reused until at least 6 other endings have been used. Change the phrases with `ACG_OUTROS` (separated by `|`) and the chance with `ACG_OUTRO_CHANCE` (default `0.5`). Use `--outro` to force it, or `--no-outro` to skip it.

## Weekly product ad (LogExpense)

Every Saturday the workflow makes a ~30s ad for [logexpense.site](https://logexpense.site) using `--style ad`. The script is written only from the product brief in [ads/logexpense.md](ads/logexpense.md), so ads never claim features that don't exist. **Update that file when the app changes** (new features, iOS launch, paid plans going live). Each week picks a different angle (audience, problem, feature) from `history.json`, and every ad ends with "subukan nang libre sa logexpense.site" (Filipino, all lowercase). Captions say "Link in bio", so keep logexpense.site as the link in your TikTok and Instagram bios.

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

Videos over Telegram's 50 MB limit are sent as a compressed copy, followed by a link to the full-quality file from the GitHub run. Each video message says where it came from (a daily GitHub run, with a link, or a test on the laptop).

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
