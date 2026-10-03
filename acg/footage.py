"""Free vertical stock footage from Pexels."""
from pathlib import Path

import requests

from .config import PEXELS_API_KEY

API = "https://api.pexels.com/videos/search"


def _search(query: str) -> list[dict]:
    r = requests.get(
        API,
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": query, "orientation": "portrait", "per_page": 15},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("videos", [])


def _best_file(video: dict) -> dict | None:
    files = [
        f for f in video.get("video_files", [])
        if f.get("file_type") == "video/mp4" and f.get("height") and 1280 <= f["height"] <= 2160
    ]
    return min(files, key=lambda f: abs(f["height"] - 1920), default=None)


def fetch_clip(query: str, min_seconds: float, used: set[int], out: Path) -> Path | None:
    """Download a portrait clip for the query; falls back to a shorter query. None if nothing found."""
    if not PEXELS_API_KEY:
        return None
    words = query.split()
    for q in dict.fromkeys([query, " ".join(words[:2]), words[0]]):
        for video in _search(q):
            if video["id"] in used or video.get("duration", 0) < min(min_seconds, 4):
                continue
            f = _best_file(video)
            if not f:
                continue
            used.add(video["id"])
            with requests.get(f["link"], stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(out, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            return out
    return None
