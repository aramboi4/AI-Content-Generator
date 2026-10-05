"""Free trend signal from YouTube: tags and hashtags on the most-viewed recent Shorts in a niche."""
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

from .config import YT_API_KEY

API = "https://www.googleapis.com/youtube/v3"
HASHTAG = re.compile(r"#\w+")


def youtube_trends(niche: str, days: int = 14, limit: int = 25) -> str:
    """Summarise what's working on YouTube right now for this niche. Empty string if no API key."""
    if not YT_API_KEY:
        return ""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    search = requests.get(f"{API}/search", timeout=30, params={
        "key": YT_API_KEY, "q": f"{niche} #shorts", "part": "id", "type": "video",
        "videoDuration": "short", "order": "viewCount", "publishedAfter": since, "maxResults": limit,
    })
    search.raise_for_status()
    ids = [i["id"]["videoId"] for i in search.json().get("items", [])]
    if not ids:
        return ""
    videos = requests.get(f"{API}/videos", timeout=30, params={
        "key": YT_API_KEY, "id": ",".join(ids), "part": "snippet,statistics",
    })
    videos.raise_for_status()

    tags, hashtags, top = Counter(), Counter(), []
    for v in videos.json().get("items", []):
        sn, views = v["snippet"], int(v.get("statistics", {}).get("viewCount", 0))
        top.append((views, sn["title"]))
        tags.update(t.lower() for t in sn.get("tags", []))
        hashtags.update(h.lower() for h in HASHTAG.findall(f"{sn['title']} {sn.get('description', '')}"))
    top.sort(reverse=True)

    lines = [f"Most-viewed '{niche}' Shorts from the last {days} days (views - title):"]
    lines += [f"- {views:,} - {title}" for views, title in top[:12]]
    lines.append("\nHashtags used most by these videos (count): " +
                 ", ".join(f"{h} ({n})" for h, n in hashtags.most_common(25)))
    lines.append("Search tags used most (count): " + ", ".join(f"{t} ({n})" for t, n in tags.most_common(25)))
    return "\n".join(lines)
