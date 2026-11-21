"""Real app screens for ads: screenshots of the product website as a phone shows it, placed onto the phone
a person holds in an AI scene image."""
from pathlib import Path

from .config import ROOT

SAVED = ROOT / "ads" / "screens" / "site"  # committed landing-page copies, used when the site can't be reached
APP = ROOT / "ads" / "screens" / "app"  # screenshots from inside the app (signed in), added by hand
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
PHONE = {"width": 390, "height": 844}  # iPhone-sized viewport: same shape as a phone screen
INSET = 0.04  # shrink the detected screen outline by this share so the screenshot stays inside the bezel


def capture(website: str, out_dir: Path) -> list[Path]:
    """Fresh phone screenshots of the site (top of the page, then one screen further down). Falls back to the
    saved copies in ads/screens if the browser isn't installed or the site doesn't load."""
    try:
        from playwright.sync_api import sync_playwright

        shots = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True)
            page.goto(f"https://{website}", wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(1500)
            page.mouse.move(PHONE["width"] / 2, PHONE["height"] / 2)
            seen = set()
            for i in range(2):  # the top of the page, then one screen further down
                if i:  # a wheel scroll works whether the page or an inner box scrolls
                    page.mouse.wheel(0, PHONE["height"] * 0.8)
                    page.wait_for_timeout(800)
                data = page.screenshot()
                if data in seen:  # didn't scroll: keep just the one screen
                    break
                seen.add(data)
                path = out_dir / f"app_screen_{i}.png"
                path.write_bytes(data)
                shots.append(path)
            browser.close()
        return shots
    except Exception as e:
        saved = [p for p in sorted(SAVED.glob("*")) if p.suffix.lower() in IMAGE_TYPES]
        print(f"    couldn't screenshot {website} ({type(e).__name__}: {str(e)[:80]}) - "
              f"using {len(saved)} saved screen(s)")
        return saved


def all_screens(website: str, out_dir: Path) -> list[Path]:
    """Everything a phone scene can show, in random order: the live landing page plus the in-app screenshots."""
    import random

    app = [p for p in sorted(APP.glob("*")) if p.suffix.lower() in IMAGE_TYPES]
    screens = capture(website, out_dir) + app
    random.shuffle(screens)
    return screens


def _perspective_coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    """PIL perspective coefficients mapping output points (dst) back to input points (src)."""
    import numpy as np

    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return list(np.linalg.solve(np.array(rows, float), np.array(rhs, float)))


def _area(q: list[tuple[float, float]]) -> float:
    return abs(sum(q[i][0] * q[i - 1][1] - q[i - 1][0] * q[i][1] for i in range(4))) / 2


def _convex(q: list[tuple[float, float]]) -> bool:
    signs = set()
    for i in range(4):
        (ax, ay), (bx, by), (cx, cy) = q[i], q[(i + 1) % 4], q[(i + 2) % 4]
        signs.add((bx - ax) * (cy - by) - (by - ay) * (cx - bx) > 0)
    return len(signs) == 1


def place_on_phone(image: Path, screen: Path) -> str:
    """Finds the phone screen in the scene image (Gemini vision) and warps the app screenshot onto it.
    Returns "" on success, otherwise why it was skipped (the image is left unchanged)."""
    from google.genai import types
    from PIL import Image, ImageDraw, ImageFilter

    from .writer import PhoneScreen, _generate

    prompt = ("Find the display screen of the smartphone in this picture (the glass area that shows content, not "
              "the phone's frame). If a phone screen is clearly visible and facing the camera at least partly, set "
              "found true and give its 4 corners as [y, x] on a 0-1000 scale, in this order: top-left, top-right, "
              "bottom-right, bottom-left, as the screen is oriented (top = the phone's top edge). Otherwise set "
              "found false.")
    resp = _generate([types.Part.from_text(text=prompt),
                      types.Part.from_bytes(data=image.read_bytes(), mime_type="image/jpeg")],
                     types.GenerateContentConfig(response_mime_type="application/json", response_schema=PhoneScreen),
                     rounds=1)
    found = resp.parsed if isinstance(resp.parsed, PhoneScreen) else PhoneScreen.model_validate_json(resp.text or "{}")
    if not found.found or len(found.corners) != 4 or any(len(c) != 2 for c in found.corners):
        return "no phone screen found"
    scene = Image.open(image).convert("RGB")
    w, h = scene.size
    quad = [(c[1] / 1000 * w, c[0] / 1000 * h) for c in found.corners]
    share = _area(quad) / (w * h)
    if not _convex(quad) or not 0.004 <= share <= 0.6:
        return f"phone screen outline looked wrong ({share:.1%} of the picture)"
    # Pull the corners in a little: the detected outline tends to run onto the phone's frame.
    cx, cy = sum(x for x, _ in quad) / 4, sum(y for _, y in quad) / 4
    quad = [(cx + (x - cx) * (1 - INSET), cy + (y - cy) * (1 - INSET)) for x, y in quad]
    app = Image.open(screen).convert("RGB")
    sw, sh = app.size
    coeffs = _perspective_coeffs(quad, [(0, 0), (sw, 0), (sw, sh), (0, sh)])
    warped = app.transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    # Rounded corners like a real phone screen, warped the same way as the screenshot.
    corners = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(corners).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=int(sw * 0.09), fill=255)
    mask = corners.transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))  # soften the edge so it sits in the phone naturally
    scene.paste(warped, (0, 0), mask)
    scene.save(image, quality=95)
    return ""


def save_reference_copies(shots: list[Path]) -> None:
    """Keeps the latest screenshots as the saved fallback copies (used by the laptop to refresh them)."""
    SAVED.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(shots):
        (SAVED / f"logexpense_{i}.png").write_bytes(p.read_bytes())
