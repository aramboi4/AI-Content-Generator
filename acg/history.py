"""history.json: every video made, so daily runs don't repeat topics. Committed back by the workflow."""
import json
from datetime import datetime

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


def add(entry: dict) -> None:
    entries = load()
    entries.append({"date": datetime.now().isoformat(timespec="minutes"), **entry})
    HISTORY.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
