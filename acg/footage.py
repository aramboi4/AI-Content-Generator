"""Free stock footage: Pixabay (default) or Pexels, whichever key is set."""
import re
from pathlib import Path

import requests

from .config import PEXELS_API_KEY, PIXABAY_API_KEY

MAX_BYTES = 60 * 1024 * 1024  # skip huge 4K files


def provider() -> str | None:
    return "Pixabay" if PIXABAY_API_KEY else "Pexels" if PEXELS_API_KEY else None


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2}


def _pixabay(query: str) -> list[tuple[int, float, str, str]]:
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query[:100], "video_type": "film", "safesearch": "true", "per_page": 20,
    })
    r.raise_for_status()
    out = []
    for hit in r.json().get("hits", []):
        # Landscape clips get center-cropped to 9:16, so prefer the tallest file under the size cap.
        tiers = [v for v in hit.get("videos", {}).values()
                 if v.get("url") and v.get("height", 0) >= 1080 and 0 < v.get("size", 0) <= MAX_BYTES]
        if tiers:
            best = max(tiers, key=lambda v: v["height"])
            out.append((hit["id"], hit.get("duration", 0), best["url"], hit.get("tags", "")))
    return out


def _pexels(query: str) -> list[tuple[int, float, str, str]]:
    r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                     headers={"Authorization": PEXELS_API_KEY},
                     params={"query": query, "orientation": "portrait", "per_page": 15})
    r.raise_for_status()
    out = []
    for video in r.json().get("videos", []):
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("height") and 1280 <= f["height"] <= 2160]
        best = min(files, key=lambda f: abs(f["height"] - 1920), default=None)
        if best:
            out.append((video["id"], video.get("duration", 0), best["link"], video.get("url", "")))  # page slug ~ tags
    return out


def fetch_clip(queries: list[str], min_seconds: float, used: set[int], out: Path) -> Path | None:
    """Download the best-matching clip, trying queries from specific to generic. None if nothing fits."""
    search = {"Pixabay": _pixabay, "Pexels": _pexels}.get(provider())
    if not search:
        return None
    for q in queries:
        wanted = _words(q)
        candidates = []
        for rank, (vid, duration, url, tags) in enumerate(search(q)):
            if vid in used or duration < min(min_seconds, 4):
                continue
            # Search engines match loosely; insist the clip is tagged with every word of the query.
            if wanted <= _words(tags):
                candidates.append((rank, vid, url))
        if not candidates:
            continue
        _, vid, url = min(candidates)
        used.add(vid)
        with requests.get(url, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(out, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        return out
    return None
