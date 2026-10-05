"""Free text-to-speech via edge-tts, with word timings for captions."""
import asyncio
from pathlib import Path

import edge_tts

from .media import probe_duration

TICKS = 10_000_000  # edge-tts offsets are in 100ns units


async def _synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    words = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS
                words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / TICKS})
    return words


def synthesize_scenes(narrations: list[str], voice: str, workdir: Path, rate: str = "+8%") -> list[dict]:
    """Returns per scene: {"audio": Path, "duration": float, "words": [...]} with scene-local timings."""
    paths = [workdir / f"voice_{i:02d}.mp3" for i in range(len(narrations))]

    async def run():
        return await asyncio.gather(*(_synth(t, voice, rate, p) for t, p in zip(narrations, paths)))

    all_words = asyncio.run(run())
    return [
        {"audio": p, "duration": probe_duration(p), "words": w}
        for p, w in zip(paths, all_words)
    ]
