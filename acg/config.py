import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUTPUT_DIR = ROOT / "output"
MUSIC_DIR = ROOT / "assets" / "music"
FONTS_DIR = ROOT / "assets" / "fonts"
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
PIPER_VOICE = os.getenv("ACG_PIPER_VOICE", "en_US-ryan-medium")  # fallback voice if edge-tts is blocked
PIPER_DIR = ROOT / "assets" / "piper"  # model downloaded here on first use (~60 MB, not in git)
# Ending call to action: added to OUTRO_CHANCE of videos, one phrase picked at random ("|"-separated).
OUTROS = [p.strip() for p in os.getenv(
    "ACG_OUTROS", "Follow for more videos like this!|Want to watch more videos? Follow for more!").split("|") if p.strip()]
OUTRO_CHANCE = float(os.getenv("ACG_OUTRO_CHANCE", "0.5"))
TREND_LANGUAGE = os.getenv("ACG_TREND_LANGUAGE", "en")  # audience for YouTube trend lookups
TREND_REGION = os.getenv("ACG_TREND_REGION", "US")
TIMEZONE = os.getenv("ACG_TZ", "Asia/Manila")  # for --publish-next
YT_CATEGORY_ID = os.getenv("YT_CATEGORY_ID", "22")  # 22 = People & Blogs, 27 = Education

WIDTH, HEIGHT, FPS = 1080, 1920, 30
