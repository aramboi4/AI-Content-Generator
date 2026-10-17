import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUTPUT_DIR = ROOT / "output"
MUSIC_DIR = ROOT / "assets" / "music"
FONTS_DIR = ROOT / "assets" / "fonts"
BRAND_DIR = ROOT / "assets" / "brand"  # logo.png (full logo, ending card), logo_icon.png (watermark)
CHANNEL_NAME = os.getenv("ACG_CHANNEL_NAME", "Daily Cup of Goodness")
YT_CLIENT_SECRET = ROOT / "client_secret.json"
YT_TOKEN = ROOT / "token.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")  # phone delivery of each video + captions
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
YT_API_KEY = os.getenv("YT_API_KEY", "")
# Gemini Google-search grounding is not included in the free tier; set to 1 if your key has it.
WEB_SEARCH = os.getenv("ACG_WEB_SEARCH", "0") == "1"
MODEL = os.getenv("ACG_MODEL", "gemini-flash-latest")
VOICE = os.getenv("ACG_VOICE", "en-US-AndrewNeural")
# Inworld voices (free plan has limited minutes); tried in this order, then edge-tts, then Piper.
INWORLD_API_KEY = os.getenv("INWORLD_API_KEY", "")
INWORLD_VOICES = [v.strip() for v in os.getenv("ACG_INWORLD_VOICES", "Clive,Dennis").split(",") if v.strip()]
INWORLD_MODEL = os.getenv("ACG_INWORLD_MODEL", "inworld-tts-1.5-max")
# Kokoro voices closest to each Inworld voice (matched on pitch and tone against real samples).
KOKORO_MATCH = {"Clive": os.getenv("ACG_KOKORO_CLIVE", "am_michael"), "Dennis": os.getenv("ACG_KOKORO_DENNIS", "am_fenrir")}
KOKORO_DIR = ROOT / "assets" / "kokoro"  # model downloaded here on first use (~340 MB, not in git)
PIPER_VOICE = os.getenv("ACG_PIPER_VOICE", "en_US-ryan-medium")  # fallback voice if edge-tts is blocked
PIPER_DIR = ROOT / "assets" / "piper"  # model downloaded here on first use (~60 MB, not in git)
# Follow-for-more ending: added to videos that DON'T end on a question (questions get a comments prompt
# instead), with probability OUTRO_CHANCE. One phrase picked at random ("|"-separated).
DEFAULT_OUTROS = "|".join([
    "Follow for more videos like this!",
    "Want to watch more videos? Follow for more!",
    "Hit follow so you don't miss the next one!",
    "Follow for a new one every day!",
    "Enjoyed this? Follow for more!",
    "Don't forget to follow for more!",
    "Want more like this? Tap follow!",
    "Follow now, there's more where that came from!",
    "If you liked this, follow for more!",
    "Follow along for more every day!",
    "Stick around and follow for more!",
    "Tap follow for your daily dose of these!",
])
OUTROS = [p.strip() for p in os.getenv("ACG_OUTROS", DEFAULT_OUTROS).split("|") if p.strip()]
COMMENT_CTAS = ["Let me know in the comments!", "Tell me in the comments!", "Drop your answer in the comments!",
                "Let me know what you think below!", "Share your answer in the comments!",
                "I'd love to hear yours in the comments!"]
COMMENT_CTA_CHANCE = float(os.getenv("ACG_COMMENT_CTA_CHANCE", "1.0"))  # when the video ends on a question
OUTRO_CHANCE = float(os.getenv("ACG_OUTRO_CHANCE", "1.0"))
TREND_LANGUAGE = os.getenv("ACG_TREND_LANGUAGE", "en")  # audience for YouTube trend lookups
TREND_REGION = os.getenv("ACG_TREND_REGION", "US")
TIMEZONE = os.getenv("ACG_TZ", "Asia/Manila")  # for --publish-next
# Custom YouTube thumbnail (title card) after upload. Off until the channel is monetized, since YouTube
# only shows custom Shorts thumbnails on Partner Program channels for now. Set to 1 to turn it on.
CUSTOM_THUMBNAIL = os.getenv("ACG_CUSTOM_THUMBNAIL", "0") == "1"
YT_CATEGORY_ID = os.getenv("YT_CATEGORY_ID", "22")  # 22 = People & Blogs, 27 = Education

WIDTH, HEIGHT, FPS = 1080, 1920, 30
