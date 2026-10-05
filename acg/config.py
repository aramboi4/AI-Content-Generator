import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUTPUT_DIR = ROOT / "output"
MUSIC_DIR = ROOT / "assets" / "music"
YT_CLIENT_SECRET = ROOT / "client_secret.json"
YT_TOKEN = ROOT / "token.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
YT_API_KEY = os.getenv("YT_API_KEY", "")
# Gemini Google-search grounding is not included in the free tier; set to 1 if your key has it.
WEB_SEARCH = os.getenv("ACG_WEB_SEARCH", "0") == "1"
MODEL = os.getenv("ACG_MODEL", "gemini-flash-latest")
VOICE = os.getenv("ACG_VOICE", "en-US-AndrewNeural")
YT_CATEGORY_ID = os.getenv("YT_CATEGORY_ID", "22")  # 22 = People & Blogs, 27 = Education

WIDTH, HEIGHT, FPS = 1080, 1920, 30
