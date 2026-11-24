# Platforms and Services

Every outside service the video generator uses, where to log in, and what it does.
All are on free plans. Keys live in `.env` on the laptop and in
[GitHub Actions secrets](https://github.com/aramboi4/AI-Content-Generator/settings/secrets/actions) for the daily runs.
Never put key values in this file.

## Making the videos

| Service | Login | What it's used for | Key / secret | Free limit and status |
|---|---|---|---|---|
| **GitHub** | [github.com/aramboi4/AI-Content-Generator](https://github.com/aramboi4/AI-Content-Generator) | Stores the code. **Actions** runs the daily videos when cron-job.org starts them ([runs](https://github.com/aramboi4/AI-Content-Generator/actions)), keeps each video for 2 days (runs older than that are deleted daily by `cleanup.yml`, also started by cron-job.org), and saves `history.json` so topics don't repeat. | Secrets page above | Free for this repo. Runs often start 2–7 hours late. |
| **cron-job.org** | [console.cron-job.org](https://console.cron-job.org) | Starts every daily and Saturday run at the exact time by calling GitHub's API (the workflow has no GitHub schedule). Setup in README → *On-time runs*. | GitHub fine-grained token with **Actions: Read and write** on this repo only (stored in cron-job.org) | Free. Renew the token before it expires. |
| **Google AI Studio (Gemini)** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Main script writer: picks the topic, writes the narration, titles, captions and hashtags. Also reviews each AI image, checks for repeated topics, picks matching stock clips, and is the Filipino voice for the Saturday ads (voice "Puck", change with `ACG_GEMINI_VOICE`). | `GEMINI_API_KEY` | Free tier. Sometimes busy (429/503), then backups take over. |
| **Groq** | [console.groq.com](https://console.groq.com) | Backup script writer when Gemini is down (gpt-oss models). | `GROQ_API_KEY` | Free, low per-minute limit. |
| **GitHub Models** | [github.com/marketplace/models](https://github.com/marketplace/models) | Last-resort backup script writer (gpt-4o-mini). Uses GitHub's built-in token, nothing to set up. | Built-in `GITHUB_TOKEN` | Free. Never actually used yet. |
| **Cloudflare Workers AI** | [dash.cloudflare.com](https://dash.cloudflare.com) → Workers AI | Draws a realistic AI picture for every line of the video (FLUX.2 klein model). Check usage under **Workers AI → Usage by model type**. | `CF_ACCOUNT_ID`, `CF_API_TOKEN` | 10,000 neurons/day, resets 8:00 AM Manila. About 2,000–3,000 per video. |
| **Pixabay** | [pixabay.com/api/docs](https://pixabay.com/api/docs/) | Free stock video clips, used only if AI images fail or the Cloudflare keys are missing. | `PIXABAY_API_KEY` | Free. |
| **Pexels** | [pexels.com/api](https://www.pexels.com/api/) | Second stock video source. | `PEXELS_API_KEY` | Optional. Pexels paused new API keys, so it's not set up. |
| **Inworld** | [platform.inworld.ai](https://platform.inworld.ai) | First-choice voice ("Clive" / "Dennis"). | `INWORLD_API_KEY` | Free credits used up, so videos use Kokoro below. Works again only if credits are added. |

## Publishing and delivery

| Service | Login | What it's used for | Key / secret | Notes |
|---|---|---|---|---|
| **Google Cloud Console** | [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials) | Holds the YouTube app login (OAuth client) that lets the code upload videos, and the YouTube Data API key used for trend research. | `client_secret.json`, `token.json` (laptop), `YT_TOKEN_JSON`, `YT_API_KEY` | Free. Keep the OAuth app in **Production** so the login doesn't expire. |
| **YouTube Studio** | [studio.youtube.com](https://studio.youtube.com) | Channel "Daily Cup of Goodness" (@DailyCupOFGoodnes). Videos are uploaded automatically and go public at 8 AM, 8 PM and Saturday 12 noon (Manila). | Same as above | Delete unwanted uploads here. |
| **Telegram** | [@BotFather](https://t.me/BotFather) (bot settings), bot **@ACG_Videos_Bot** | Sends each finished video with captions, hashtags and posting time to the phone, plus ❌ failure alerts and ⚠️ warnings. | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Free. Videos over 50 MB arrive compressed, with a full-quality download link. |
| **TikTok** | [tiktok.com/login](https://www.tiktok.com/login) | Posted manually from the phone using the Telegram video and captions. | None | Turn on the **AI-generated content** label for every post. |
| **Instagram** | [instagram.com/accounts/login](https://www.instagram.com/accounts/login/) | Posted manually from the phone (Reels). | None | Turn on the **AI info** label for every post. |
| **LogExpense** | [logexpense.site](https://logexpense.site) | The product advertised in the Saturday ad. Ad claims come only from `ads/logexpense.md`. | None | Your own app. |

## Free tools that run inside the code (no login)

| Tool | What it's used for |
|---|---|
| **Kokoro** (voice `am_adam`) | Main voice now that Inworld credits are gone. Downloaded once and cached. |
| **Piper** (voice `en_US-ryan-medium`) | Backup voice if Kokoro fails. |
| **faster-whisper** | Listens to the voice to time each caption word exactly. |
| **FFmpeg** | Builds the final video: pictures, zoom, captions, logo, music. |
| **Microsoft edge-tts** | Turned off at your request (`ACG_USE_MICROSOFT_VOICE=1` turns it back on). |

## If something stops working

- **Telegram says ❌ failed:** open the log link in the message, or send it to Claude.
- **Telegram says ⚠️ stock footage:** the Cloudflare secrets are missing or wrong on GitHub.
- **Every Cloudflare image fails:** the daily 10,000 neurons are used up; wait until 8:00 AM Manila.
- **YouTube upload fails with an auth error:** `token.json` expired; log in again on the laptop and update `YT_TOKEN_JSON`.
- **A key was leaked or changed:** create a new one on the service's site, then update both `.env` and the GitHub secret.
