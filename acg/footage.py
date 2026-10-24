"""Free stock footage: Pixabay (default) or Pexels, whichever key is set.

Clips are chosen by looking at them: preview images of up to MAX_CANDIDATES clips are shown to Gemini
together with the scene's narration, and it picks the one that literally shows what's being said.
If that check isn't available, the first clip tagged with every query word is used, as before.
"""
import re
from pathlib import Path

import requests

from .config import PEXELS_API_KEY, PIXABAY_API_KEY

MAX_BYTES = 60 * 1024 * 1024  # skip huge 4K files
MAX_CANDIDATES = 8


def provider() -> str | None:
    return "Pixabay" if PIXABAY_API_KEY else "Pexels" if PEXELS_API_KEY else None


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2}


def _pixabay(query: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query[:100], "video_type": "film", "safesearch": "true", "per_page": 20,
    })
    r.raise_for_status()
    out = []
    for hit in r.json().get("hits", []):
        videos = hit.get("videos", {})
        # Landscape clips get center-cropped to 9:16, so prefer the tallest file under the size cap.
        tiers = [v for v in videos.values()
                 if v.get("url") and v.get("height", 0) >= 1080 and 0 < v.get("size", 0) <= MAX_BYTES]
        if tiers:
            best = max(tiers, key=lambda v: v["height"])
            thumb = next((videos[s]["thumbnail"] for s in ("small", "tiny", "medium")
                          if videos.get(s, {}).get("thumbnail")), "")
            out.append({"id": hit["id"], "duration": hit.get("duration", 0), "url": best["url"],
                        "tags": hit.get("tags", ""), "thumb": thumb})
    return out


def _pexels(query: str) -> list[dict]:
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
            out.append({"id": video["id"], "duration": video.get("duration", 0), "url": best["link"],
                        "tags": video.get("url", ""), "thumb": video.get("image", "")})  # page slug ~ tags
    return out


def _candidates(queries: list[str], min_seconds: float, used: set[int]) -> list[dict]:
    """Up to MAX_CANDIDATES unused clips across the queries, tag-matching ones first within each query."""
    search = {"Pixabay": _pixabay, "Pexels": _pexels}[provider()]
    picked, seen = [], set()
    for q in queries[:3]:
        wanted = _words(q)
        hits = [h for h in search(q) if h["id"] not in used and h["id"] not in seen
                and h["duration"] >= min(min_seconds, 4)]
        hits.sort(key=lambda h: not wanted <= _words(h["tags"]))  # stable: keeps search order otherwise
        for h in hits[:4]:
            seen.add(h["id"])
            picked.append({**h, "query": q, "tag_match": wanted <= _words(h["tags"])})
        if len(picked) >= MAX_CANDIDATES:
            break
    return picked[:MAX_CANDIDATES]


def _download(url: str, out: Path) -> Path:
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(out, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    return out


def fetch_clip(queries: list[str], min_seconds: float, used: set[int], out: Path,
               narration: str = "") -> tuple[Path | None, str]:
    """Downloads the clip that best shows the narration. Returns (path or None, how it was chosen)."""
    if not provider():
        return None, "no footage key"
    cands = _candidates(queries, min_seconds, used)
    if not cands:
        return None, "no results"
    choice, how = None, ""
    if narration:
        try:
            from .writer import pick_clip
            images = []
            for c in cands:
                r = requests.get(c["thumb"], timeout=30) if c["thumb"] else None
                images.append(r.content if r is not None and r.ok else None)
            usable = [i for i, img in enumerate(images) if img]
            if usable:
                best, score = pick_clip(narration, [images[i] for i in usable])
                if best is not None:
                    choice, how = cands[usable[best]], f"visual match {score}/10"
                else:  # nothing fits well - a loosely related clip still beats an empty background
                    how = "no close visual match"
        except Exception as e:  # vision check unavailable: fall back to tags
            how = f"tags only ({type(e).__name__})"
    if choice is None:
        tagged = [c for c in cands if c["tag_match"]] or cands
        choice, how = tagged[0], f"{how}, using best tag match" if how else "tags only"
    used.add(choice["id"])
    return _download(choice["url"], out), f"{how}, query '{choice['query']}'"
