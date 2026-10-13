"""Text-to-speech with word timings for captions.

Primary: Microsoft's free neural voices via edge-tts (best quality, exact word timings).
Fallback: Piper, an open-source voice that runs locally - used when Microsoft's service refuses
the connection (it sometimes blocks cloud servers like GitHub's), so the video still gets made.
"""
import asyncio
import re
import time
import wave
from pathlib import Path

import edge_tts

from .config import PIPER_DIR, PIPER_VOICE
from .media import probe_duration

TICKS = 10_000_000  # edge-tts offsets are in 100ns units
EDGE_RETRY_WAITS = (15, 45)  # seconds to wait before the 2nd and 3rd edge-tts attempts


async def _edge_synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    words = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS
                words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / TICKS})
    if not words:
        raise RuntimeError("edge-tts returned no audio")
    return words


def _edge_all(narrations: list[str], voice: str, rate: str, paths: list[Path]) -> list[list[dict]]:
    async def run():
        return await asyncio.gather(*(_edge_synth(t, voice, rate, p) for t, p in zip(narrations, paths)))
    return asyncio.run(run())


def _estimate_words(text: str, duration: float) -> list[dict]:
    """Piper gives no word timings: spread the audio over the words by length, with extra time at
    punctuation. Close enough for 3-word caption groups."""
    tokens = text.split()
    weights = [len(re.sub(r"\W", "", w)) + 2 + (4 if re.search(r"[.!?]$", w) else 2 if re.search(r"[,;:]$", w) else 0)
               for w in tokens]
    lead, tail = 0.08, 0.15
    span = max(duration - lead - tail, 0.1)
    words, t = [], lead
    for w, wt in zip(tokens, weights):
        d = span * wt / sum(weights)
        words.append({"text": re.sub(r"^[^\w']+|[^\w']+$", "", w) or w, "start": t, "end": t + d * 0.85})
        t += d
    return words


def _piper_all(narrations: list[str], rate: str, workdir: Path) -> list[tuple[Path, list[dict]]]:
    from piper import PiperVoice, SynthesisConfig

    model = PIPER_DIR / f"{PIPER_VOICE}.onnx"
    if not model.exists():
        from piper.download_voices import download_voice
        PIPER_DIR.mkdir(parents=True, exist_ok=True)
        download_voice(PIPER_VOICE, PIPER_DIR)
    voice = PiperVoice.load(str(model))
    speed = 1 + int(rate.rstrip("%")) / 100  # "+8%" -> 1.08
    cfg = SynthesisConfig(length_scale=1 / speed)
    out = []
    for i, text in enumerate(narrations):
        path = workdir / f"voice_{i:02d}.wav"
        with wave.open(str(path), "wb") as w:
            voice.synthesize_wav(text, w, syn_config=cfg)
        out.append((path, _estimate_words(text, probe_duration(path))))
    return out


def synthesize_scenes(narrations: list[str], voice: str, workdir: Path, rate: str = "+8%") -> list[dict]:
    """Returns per scene: {"audio", "duration", "words", "engine"} with scene-local timings.
    The whole video uses one engine, so the voice never changes mid-video."""
    paths = [workdir / f"voice_{i:02d}.mp3" for i in range(len(narrations))]
    error = None
    for attempt in range(len(EDGE_RETRY_WAITS) + 1):
        try:
            all_words = _edge_all(narrations, voice, rate, paths)
            return [{"audio": p, "duration": probe_duration(p), "words": w, "engine": "edge-tts"}
                    for p, w in zip(paths, all_words)]
        except Exception as e:
            error = e
            if attempt < len(EDGE_RETRY_WAITS):
                wait = EDGE_RETRY_WAITS[attempt]
                print(f"    edge-tts failed ({type(e).__name__}: {str(e)[:80]}) - retrying in {wait}s...")
                time.sleep(wait)
    print(f"    edge-tts unavailable ({type(error).__name__}) - using the Piper fallback voice.")
    for p in paths:
        p.unlink(missing_ok=True)
    return [{"audio": p, "duration": probe_duration(p), "words": w, "engine": "piper",
             "edge_error": f"{type(error).__name__}: {str(error)[:150]}"}
            for p, w in _piper_all(narrations, rate, workdir)]
