"""AI scene images via Cloudflare Workers AI (free daily allowance), FLUX.2 [klein].

A character reference image is generated first and passed into every scene,
so the same character appears throughout the video.
"""
import base64
import time
from pathlib import Path

import requests

from .config import CF_ACCOUNT_ID, CF_API_TOKEN

MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
IMG_W, IMG_H = 768, 1344  # ~9:16, upscaled to 1080x1920 at render time
ART_STYLE = ("3D animated movie style, Pixar-like, soft cinematic lighting, expressive cartoon proportions, "
             "rich colors, shallow depth of field, high detail, no text, no watermark")


def available() -> bool:
    return bool(CF_ACCOUNT_ID and CF_API_TOKEN)


def generate(prompt: str, out: Path, refs: list[Path] = (), seed: int | None = None) -> Path:
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{MODEL}"
    form = {"prompt": (None, f"{prompt}. {ART_STYLE}"), "width": (None, str(IMG_W)), "height": (None, str(IMG_H))}
    if seed is not None:
        form["seed"] = (None, str(seed))
    for i, ref in enumerate(refs[:4]):
        form[f"input_image_{i}"] = (ref.name, ref.read_bytes(), "image/jpeg")
    for attempt in range(3):
        r = requests.post(url, headers={"Authorization": f"Bearer {CF_API_TOKEN}"}, files=form, timeout=180)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(10 * (attempt + 1))
            continue
        if not r.ok:
            raise RuntimeError(f"Cloudflare image error {r.status_code}: {r.text[:300]}")
        body = r.json()
        image = (body.get("result") or {}).get("image") or body.get("image")
        if not image:
            raise RuntimeError(f"No image in Cloudflare response: {str(body)[:300]}")
        out.write_bytes(base64.b64decode(image))
        return out
    raise RuntimeError(f"Cloudflare image generation kept failing ({r.status_code}): {r.text[:300]}")
