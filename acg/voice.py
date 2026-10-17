"""Text-to-speech with word timings for captions. Engines, in order of preference:

1. Inworld (Clive or Dennis, picked at random) - when INWORLD_API_KEY is set and credits remain.
2. Microsoft's free neural voices via edge-tts (exact word timings).
3. Kokoro, a free open-source voice that runs locally, using the voice closest to the picked
   Inworld voice - used when Microsoft's service refuses the connection.
4. Piper, a lighter local voice - last resort, so the video still gets made.
"""
import asyncio
import base64
import random
import re
import time
import wave
from pathlib import Path

import edge_tts
import requests

from .config import (INWORLD_API_KEY, INWORLD_MODEL, INWORLD_VOICES, KOKORO_DIR, KOKORO_MATCH, PIPER_DIR,
                     PIPER_VOICE)

KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
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


class VoiceNotFound(Exception):
    pass


def _inworld_synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    r = requests.post("https://api.inworld.ai/tts/v1/voice", timeout=120,
                      headers={"Authorization": f"Basic {INWORLD_API_KEY}"},
                      json={"text": text, "voiceId": voice, "modelId": INWORLD_MODEL,
                            "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 48000,
                                            "speakingRate": round(1 + int(rate.rstrip("%")) / 100, 2)},
                            "timestampType": "WORD"})
    if r.status_code in (400, 404) and "voice" in r.text.lower():
        raise VoiceNotFound(f"{voice}: {r.text[:150]}")
    if not r.ok:
        raise RuntimeError(f"Inworld {r.status_code}: {r.text[:200]}")
    body = r.json()
    out.write_bytes(base64.b64decode(body["audioContent"]))
    a = (body.get("timestampInfo") or {}).get("wordAlignment") or {}
    words = [{"text": w.strip(), "start": s, "end": e} for w, s, e in
             zip(a.get("words", []), a.get("wordStartTimeSeconds", []), a.get("wordEndTimeSeconds", []))
             if re.search(r"\w", w)]  # Inworld also returns entries for spaces/punctuation
    return words or _estimate_words(text, probe_duration(out))


def _inworld_all(narrations: list[str], rate: str, paths: list[Path],
                 order: list[str] | None = None) -> tuple[str, list[list[dict]]]:
    """Tries each voice in `order`; returns (voice used, word timings per scene)."""
    last = None
    for voice in order or INWORLD_VOICES:
        try:
            return voice, [_inworld_synth(t, voice, rate, p) for t, p in zip(narrations, paths)]
        except VoiceNotFound as e:
            last = e
            print(f"    Inworld voice {voice} not available - trying the next one.")
    raise RuntimeError(f"None of the Inworld voices {INWORLD_VOICES} are available ({last})")


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


def _piper_all(narrations: list[str], rate: str, workdir: Path, prefix: str = "voice") -> list[tuple[Path, list[dict]]]:
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
        path = workdir / f"{prefix}_{i:02d}.wav"
        with wave.open(str(path), "wb") as w:
            voice.synthesize_wav(text, w, syn_config=cfg)
        out.append((path, _estimate_words(text, probe_duration(path))))
    return out


def _kokoro_all(narrations: list[str], kvoice: str, rate: str, workdir: Path,
                prefix: str = "voice") -> list[tuple[Path, list[dict]]]:
    import numpy as np
    from kokoro_onnx import Kokoro

    KOKORO_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        if not (KOKORO_DIR / name).exists():  # ~340 MB once; cached by the GitHub workflow
            print(f"    downloading Kokoro {name}...")
            with requests.get(f"{KOKORO_URL}/{name}", stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(KOKORO_DIR / f"{name}.part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            (KOKORO_DIR / f"{name}.part").rename(KOKORO_DIR / name)
    k = Kokoro(str(KOKORO_DIR / "kokoro-v1.0.onnx"), str(KOKORO_DIR / "voices-v1.0.bin"))
    speed = 1 + int(rate.rstrip("%")) / 100
    lang = "en-gb" if kvoice.startswith("b") else "en-us"
    out = []
    for i, text in enumerate(narrations):
        audio, sr = k.create(text, voice=kvoice, speed=speed, lang=lang)
        path = workdir / f"{prefix}_{i:02d}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        out.append((path, _estimate_words(text, probe_duration(path))))
    return out


def synthesize_scenes(narrations: list[str], voice: str, workdir: Path, rate: str = "+8%",
                      prefix: str = "voice", engine: str | None = None) -> list[dict]:
    """Returns per scene: {"audio", "duration", "words", "engine"} with scene-local timings.

    Order: Inworld (Clive or Dennis, picked at random) -> Microsoft edge-tts -> Kokoro (closest match to
    the picked Inworld voice) -> Piper. Pass `engine` (a previous result's "engine") to reuse the exact
    same voice, e.g. for scenes added later, so the voice never changes mid-video."""
    paths = [workdir / f"{prefix}_{i:02d}.mp3" for i in range(len(narrations))]

    def result(pairs, eng, **extra):
        return [{"audio": p, "duration": probe_duration(p), "words": w, "engine": eng, **extra} for p, w in pairs]

    if engine:  # reuse the voice chosen earlier for this video
        kind, _, name = engine.partition(":")
        if kind == "inworld":
            return result(zip(paths, [_inworld_synth(t, name, rate, p) for t, p in zip(narrations, paths)]), engine)
        if kind == "edge-tts":
            return result(zip(paths, _edge_all(narrations, voice, rate, paths)), engine)
        if kind == "kokoro":
            return result(_kokoro_all(narrations, name, rate, workdir, prefix), engine)
        return result(_piper_all(narrations, rate, workdir, prefix), engine)

    preferred = random.sample(INWORLD_VOICES, len(INWORLD_VOICES))  # random order: Clive or Dennis first
    inworld_error = None
    if INWORLD_API_KEY:
        try:
            used, all_words = _inworld_all(narrations, rate, paths, preferred)
            return result(zip(paths, all_words), f"inworld:{used}")
        except Exception as e:  # free minutes used up, outage, ...: fall back to the free Microsoft voice
            inworld_error = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"    Inworld failed ({inworld_error}) - using Microsoft's voice instead.")
    error = None
    for attempt in range(len(EDGE_RETRY_WAITS) + 1):
        try:
            return result(zip(paths, _edge_all(narrations, voice, rate, paths)), "edge-tts",
                          inworld_error=inworld_error)
        except Exception as e:
            error = e
            if attempt < len(EDGE_RETRY_WAITS):
                wait = EDGE_RETRY_WAITS[attempt]
                print(f"    edge-tts failed ({type(e).__name__}: {str(e)[:80]}) - retrying in {wait}s...")
                time.sleep(wait)
    edge_error = f"{type(error).__name__}: {str(error)[:150]}"
    for p in paths:
        p.unlink(missing_ok=True)
    kvoice = KOKORO_MATCH.get(preferred[0], "am_michael")
    try:
        print(f"    edge-tts unavailable - using Kokoro voice {kvoice} (closest to {preferred[0]}).")
        return result(_kokoro_all(narrations, kvoice, rate, workdir, prefix), f"kokoro:{kvoice}",
                      inworld_error=inworld_error, edge_error=edge_error)
    except Exception as e:
        print(f"    Kokoro failed ({type(e).__name__}: {str(e)[:80]}) - using the Piper fallback voice.")
        return result(_piper_all(narrations, rate, workdir, prefix), "piper", inworld_error=inworld_error,
                      edge_error=edge_error, kokoro_error=f"{type(e).__name__}: {str(e)[:150]}")
