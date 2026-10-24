"""history.json: every video made, so daily runs don't repeat topics. Committed back by the workflow."""
import json
from datetime import datetime, timedelta, timezone

from .config import ROOT

HISTORY = ROOT / "history.json"


def load() -> list[dict]:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def recent_topics(style: str, n: int = 80) -> list[str]:
    return [e["topic"] for e in load() if e.get("style") == style][-n:]


def recent_hooks(n: int = 15) -> list[str]:
    """Opening lines of recent videos (any style), so new ones don't start the same way."""
    return [e["hook"] for e in load() if e.get("hook")][-n:]


def recent_outros(n: int = 6) -> list[str]:
    """Endings used by the most recent videos that had one."""
    return [e["outro"] for e in load() if e.get("outro")][-n:] if n > 0 else []


def uploaded_recently(style: str, hours: float) -> dict | None:
    """The most recent video of `style` uploaded to YouTube in the last `hours`, if any (used by the
    retry runs to skip when the normal run already succeeded)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for e in reversed(load()):
        if e.get("style") == style and e.get("youtube") and e.get("date_utc"):
            if datetime.fromisoformat(e["date_utc"]) >= cutoff:
                return e
    return None


def add(entry: dict) -> None:
    entries = load()
    entries.append({"date": datetime.now().isoformat(timespec="minutes"),
                    "date_utc": datetime.now(timezone.utc).isoformat(timespec="minutes"), **entry})
    HISTORY.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
