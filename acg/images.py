"""AI scene images via Cloudflare Workers AI (free daily allowance), FLUX.2 [klein].

A character reference image is generated first and passed into every scene,
so the same character appears throughout the video.
"""
import base64
import os
import time
from pathlib import Path

import requests

from .config import CF_ACCOUNT_ID, CF_API_TOKEN

MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
IMG_W, IMG_H = 768, 1344  # ~9:16, upscaled to 1080x1920 at render time
PASS_SCORE = 7  # every review category must reach this, or the image is redrawn
_COMMON = ("Believable, physically plausible scene at realistic scale with no exaggerated effects. Show only what is "
           "described: no extra people, hands or body parts; anyone described has correct anatomy. "
           "No text, letters, signs or logos anywhere, no watermark. ")
ART_STYLES = {
    "3d": _COMMON + ("3D animated movie style, Pixar-like, soft cinematic lighting, expressive cartoon proportions, "
                     "rich colors, shallow depth of field, high detail"),
    "realistic": _COMMON + ("Photorealistic cinematic photograph, natural light, realistic skin and textures, shot on "
                            "35mm film, shallow depth of field"),
}
ART_STYLE = ART_STYLES.get(os.getenv("ACG_ART_STYLE", "3d"), ART_STYLES["3d"])


def generate_checked(prompt: str, narration: str, out: Path, refs: list[Path] = (), seed: int = 7,
                     attempts: int = 3, plan: str = "") -> tuple[Path, str]:
    """Draws the scene, has Gemini review it (matches the line? believable? correct anatomy?), and redraws
    with the reviewer's feedback if needed, keeping the best attempt. If the review isn't available
    (e.g. Gemini is busy), the drawn image is used as is. Returns (path, summary)."""
    from .writer import check_image

    best, best_score, feedback, summary = None, -1, "", "not reviewed"
    for attempt in range(attempts):
        path = out.with_name(f"{out.stem}_try{attempt}{out.suffix}")
        fix = f". IMPORTANT, fix this problem from the previous attempt: {feedback}" if feedback else ""
        try:
            generate(prompt + fix, path, refs, seed + 37 * attempt)
        except RuntimeError:
            if best is None and attempt == attempts - 1:
                raise
            continue
        try:
            review = check_image(narration, path.read_bytes(), plan or prompt)
        except Exception as e:  # reviewer unavailable: don't spend more images
            if best is None:
                best, summary = path, f"not reviewed ({type(e).__name__})"
            break
        score = min(review.matches_line, review.believable, review.anatomy)
        if score > best_score:
            best, best_score = path, score
            summary = (f"review: line {review.matches_line}/10, believable {review.believable}/10, "
                       f"anatomy {review.anatomy}/10, try {attempt + 1}")
        if score >= PASS_SCORE:
            break
        feedback = review.problem
        print(f"    redrawing: {review.problem[:110]}")
    if best is None:
        raise RuntimeError("no image could be generated")
    out.write_bytes(best.read_bytes())
    for p in out.parent.glob(f"{out.stem}_try*{out.suffix}"):
        p.unlink(missing_ok=True)
    return out, summary


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
        if r.status_code == 400 and "flagged" in r.text.lower() and attempt < 2:
            # The safety filter judges the generated picture, so another seed usually passes a false alarm.
            print(f"    image flagged by the safety filter, trying another seed...")
            form["seed"] = (None, str((seed or 7) + 100 * (attempt + 1)))
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
