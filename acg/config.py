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
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
YT_API_KEY = os.getenv("YT_API_KEY", "")
# Gemini Google-search grounding is not included in the free tier; set to 1 if your key has it.
WEB_SEARCH = os.getenv("ACG_WEB_SEARCH", "0") == "1"
MODEL = os.getenv("ACG_MODEL", "gemini-flash-latest")
VOICE = os.getenv("ACG_VOICE", "en-US-AndrewNeural")
# Ending call to action: added to OUTRO_CHANCE of videos, one phrase picked at random ("|"-separated).
OUTROS = [p.strip() for p in os.getenv(
    "ACG_OUTROS", "Follow for more videos like this!|Want to watch more videos? Follow for more!").split("|") if p.strip()]
OUTRO_CHANCE = float(os.getenv("ACG_OUTRO_CHANCE", "0.5"))
TIMEZONE = os.getenv("ACG_TZ", "Asia/Manila")  # for --publish-next
YT_CATEGORY_ID = os.getenv("YT_CATEGORY_ID", "22")  # 22 = People & Blogs, 27 = Education

WIDTH, HEIGHT, FPS = 1080, 1920, 30
