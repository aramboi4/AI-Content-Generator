"""FFmpeg helpers: probing, per-scene clips, captions, final render."""
import os
import random
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from .config import FONTS_DIR, FPS, HEIGHT, MUSIC_DIR, WIDTH

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
                          cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-2000:]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        raise RuntimeError(f"Could not read duration of {path}")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def render_segment(clip: Path | None, duration: float, out: Path, zoom_out: bool = False) -> None:
    """Loop/trim a clip or still image to `duration`, crop to vertical, with a slow zoom."""
    d = f"{duration:.3f}"
    factor = f"(1.08-0.08*t/{d})" if zoom_out else f"(1+0.08*t/{d})"
    zoom = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={FPS},"
            f"scale=w='trunc({WIDTH}*{factor}/2)*2':h=-2:eval=frame:flags=bicubic,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,format=yuv420p")  # identical settings in every segment
    if clip and clip.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        src = ["-loop", "1", "-framerate", str(FPS), "-i", str(clip)]
    elif clip:
        src = ["-stream_loop", "-1", "-i", str(clip)]
    else:
        src = ["-f", "lavfi", "-i", f"color=c=0x111111:s={WIDTH}x{HEIGHT}:r={FPS}"]
    _run([*src, "-t", f"{duration:.3f}", "-vf", zoom, "-an",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), str(out)])


def render_browser_outro(page: Path, url: str, duration: float, out: Path) -> None:
    """Ad ending: a browser window where `url` is typed into the address bar, the page loads, and the landing
    page (`page`, a phone screenshot) appears and scrolls gently. Leaves room below for the website card."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    bx0, by0, bw, bh, bar_h, r = 90, 150, 900, 1330, 132, 44  # browser window and its top bar
    shot = Image.open(page).convert("RGB")
    shot = shot.resize((bw, round(shot.height * bw / shot.width)), Image.Resampling.LANCZOS)
    view_h = bh - bar_h
    if shot.height < view_h:  # short screenshot: pad with the page's own background colour
        padded = Image.new("RGB", (bw, view_h), shot.getpixel((5, shot.height - 5)))
        padded.paste(shot, (0, 0))
        shot = padded
    max_scroll = min(260, shot.height - view_h)

    # Background: the page itself, blurred and dimmed; plus the window's shadow.
    bg = shot.resize((WIDTH, round(shot.height * WIDTH / bw))).crop((0, 0, WIDTH, HEIGHT))
    bg = Image.blend(bg.filter(ImageFilter.GaussianBlur(28)), Image.new("RGB", (WIDTH, HEIGHT), (18, 16, 28)), 0.55)
    shadow = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(shadow).rounded_rectangle([bx0, by0 + 16, bx0 + bw, by0 + bh + 16], radius=r, fill=150)
    bg.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(24)))
    window_mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(window_mask).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=r, fill=255)

    font = ImageFont.truetype(str(FONTS_DIR / "Inter.ttf"), 46)
    font.set_variation_by_name("Regular")
    pill = (28, 30, bw - 28, bar_h - 30)  # address field inside the top bar
    tx, ty = pill[0] + 74, (pill[1] + pill[3]) / 2

    type_start, per_char = 0.35, 0.07
    typed_at = type_start + per_char * len(url)
    load_start, load_end = typed_at + 0.25, typed_at + 0.75
    shown_at = load_end - 0.15
    ease = lambda p: p * p * (3 - 2 * p)  # noqa: E731 - smooth start and stop

    proc = subprocess.Popen(
        [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
         "-r", str(FPS), "-i", "-", "-vf",
         "setsar=1,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,format=yuv420p",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), str(out)],
        stdin=subprocess.PIPE)
    for n in range(round(duration * FPS)):
        t = n / FPS
        win = Image.new("RGB", (bw, bh), "white")
        if t >= shown_at:  # the landing page, fading in, then scrolling slowly
            p = min(1.0, max(0.0, (t - shown_at - 0.3) / max(duration - shown_at - 0.6, 0.1)))
            y = round(max_scroll * ease(p))
            view = shot.crop((0, y, bw, y + view_h))
            fade = min(1.0, (t - shown_at) / 0.25)
            win.paste(Image.blend(Image.new("RGB", view.size, "white"), view, fade), (0, bar_h))
        d = ImageDraw.Draw(win)
        d.rectangle([0, 0, bw, bar_h], fill="white")
        d.line([0, bar_h - 1, bw, bar_h - 1], fill=(225, 227, 230), width=2)
        d.rounded_rectangle(pill, radius=(pill[3] - pill[1]) // 2, fill=(236, 238, 241))
        lx, ly = pill[0] + 30, ty  # small padlock
        d.rounded_rectangle([lx, ly - 4, lx + 22, ly + 16], radius=4, fill=(95, 99, 104))
        d.arc([lx + 4, ly - 16, lx + 18, ly + 2], 180, 360, fill=(95, 99, 104), width=4)
        chars = len(url) if t >= typed_at else max(0, int((t - type_start) / per_char))
        text = url[:chars]
        d.text((tx, ty), text, font=font, fill=(32, 33, 36), anchor="lm")
        if t < load_start and int(t * 2.5) % 2 == 0:  # blinking cursor while typing
            cx = tx + d.textlength(text, font=font) + 4
            d.line([cx, ty - 26, cx, ty + 26], fill=(26, 115, 232), width=3)
        if load_start <= t < load_end + 0.15:  # blue loading bar under the address bar
            p = min(1.0, (t - load_start) / (load_end - load_start))
            d.rectangle([0, bar_h - 5, round(bw * ease(p)), bar_h], fill=(26, 115, 232))
        frame = bg.copy()
        frame.paste(win, (bx0, by0), window_mask)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError("FFmpeg failed while rendering the browser ending")


URL_HIGHLIGHT = (229, 32, 45)  # bold red box behind web addresses on cards


def _is_url(word: str) -> bool:
    return bool(re.search(r"[a-z0-9-]\.[a-z]{2,}", word, re.I))


def caps(text: str) -> str:
    """Upper-cases on-screen text but keeps web addresses (e.g. logexpense.site) lowercase."""
    return " ".join(w if _is_url(w) else w.upper() for w in text.split(" "))


def pad_audio(src: Path, seconds: float) -> Path:
    """A copy of `src` with silence added at the end so it lasts `seconds` (same format, so it still joins
    with the other voice files)."""
    out = src.with_name(f"{src.stem}_padded{src.suffix}")
    _run(["-i", src.name, "-af", f"apad=whole_dur={seconds:.2f}", out.name], cwd=src.parent)
    return out


def concat_audio(parts: list[Path], out: Path) -> None:
    listfile = out.with_suffix(".txt")
    listfile.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    _run(["-f", "concat", "-safe", "0", "-i", listfile.name, "-c:a", "aac", "-b:a", "192k", out.name], cwd=out.parent)


def _ass_time(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


CAPTION_STYLES = {
    # 3-word groups in a heavy font, lower-middle (the look of the carpenter video)
    "classic": {"words": 3, "style": "Cap,Archivo Black,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,7,3,2,80,80,620,1"},
    # one huge word at a time in Anton, plus a purple title card
    "bold": {"words": 1, "style": "Cap,Anton,200,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,1,0,1,12,0,2,60,60,560,1"},
}


def write_captions(words: list[dict], out: Path, style: str = "classic", title: str = "", title_secs: float = 3.0,
                   outro: tuple[float, float, str] | None = None) -> None:
    """Pop-in word-group captions plus an opening title card (visible from the first frame, for use as the cover)."""
    per_line = CAPTION_STYLES[style]["words"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {CAPTION_STYLES[style]["style"]}
Style: Outro,{"Anton" if style == "bold" else "Archivo Black"},104,&H00FFFFFF,&H00FFFFFF,&H40642D4A,&H00000000,0,0,0,0,100,100,1,0,3,40,0,5,120,120,0,1
Style: Title,{"Anton" if style == "bold" else "Archivo Black"},{110 if style == "bold" else 100},&H00FFFFFF,&H00FFFFFF,&H40642D4A,&H00000000,0,0,0,0,100,100,1,0,3,34,0,8,120,120,{560 if style == "bold" else 380},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if title:  # translucent purple box with white text near the top, like a hook card
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(title_secs)},Title,,0,0,0,,{{\\fad(0,300)}}{caps(title)}")
    if outro:  # "follow for more" card in the middle of the screen, popping in
        start, end, text = outro
        lines.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Outro,,0,0,0,,"
                     rf"{{\fscx70\fscy70\t(0,160,\fscx100\fscy100)}}{caps(text)}")
    groups: list[list[dict]] = []
    for w in words:  # never let a caption group span two scenes
        if groups and len(groups[-1]) < per_line and groups[-1][-1].get("scene") == w.get("scene"):
            groups[-1].append(w)
        else:
            groups.append([w])
    for i, g in enumerate(groups):
        start = g[0]["start"]
        end = g[-1]["end"] + 0.3
        if i + 1 < len(groups):  # hold until the next group, unless there's a pause
            nxt = groups[i + 1][0]["start"]
            end = nxt if nxt - g[-1]["end"] <= 0.4 else min(end, nxt)
        text = caps(" ".join(w["text"] for w in g)).replace("{", "").replace("}", "")
        pop = r"{\fscx85\fscy85\t(0,90,\fscx100\fscy100)}"
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{pop}{text}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


CARD_FILL = (74, 45, 100, 200)  # purple, slightly see-through


def render_watermark(icon: Path, out: Path, size: int = 150, opacity: float = 0.8, margin: int = 40,
                     top: int = 140) -> Path:
    """Full-frame transparent PNG with the channel icon in the top-right corner (clear of the
    TikTok/Reels/Shorts buttons on the right and the captions in the middle)."""
    from PIL import Image

    logo = Image.open(icon).convert("RGBA")
    logo = logo.resize((int(logo.width * size / logo.height), size), Image.LANCZOS)
    alpha = logo.getchannel("A").point(lambda a: int(a * opacity))
    logo.putalpha(alpha)
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    img.alpha_composite(logo, (WIDTH - logo.width - margin, top))
    img.save(out)
    return out


def logo_badge(logo: Path, out: Path, width: int = 420, pad: int = 30) -> Path:
    """The channel logo on a soft dark rounded backdrop, as a small standalone PNG (for the animated outro)."""
    from PIL import Image, ImageDraw

    lg = Image.open(logo).convert("RGBA")
    lg = lg.resize((width, int(lg.height * width / lg.width)), Image.LANCZOS)
    img = Image.new("RGBA", (lg.width + 2 * pad, lg.height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=36, fill=(0, 0, 0, 150))
    img.alpha_composite(lg, (pad, pad))
    img.save(out)
    return out


def card_top(card: Path) -> int:
    """Top edge (y) of the box drawn in a full-frame card PNG."""
    from PIL import Image

    return Image.open(card).getchannel("A").getbbox()[1]


def add_logo_above(card: Path, logo: Path, width: int = 420, gap: int = 40) -> Path:
    """Places the full channel logo centered just above the box in a rendered card PNG."""
    from PIL import Image

    img = Image.open(card).convert("RGBA")
    box_top = img.getchannel("A").getbbox()[1]
    from PIL import ImageDraw

    lg = Image.open(logo).convert("RGBA")
    lg = lg.resize((width, int(lg.height * width / lg.width)), Image.LANCZOS)
    x, y = (WIDTH - lg.width) // 2, max(30, box_top - gap - lg.height)
    pad = 30  # dark backdrop keeps the logo and its text readable on busy footage
    ImageDraw.Draw(img).rounded_rectangle([x - pad, y - pad, x + lg.width + pad, y + lg.height + pad],
                                          radius=36, fill=(0, 0, 0, 150))
    img.alpha_composite(lg, (x, y))
    img.save(card)
    return card


def make_thumbnail(video: Path, out: Path, first_segment: Path | None = None, title: str = "",
                   style: str = "classic") -> Path:
    """JPEG for YouTube's custom thumbnail (max 2 MB): the first scene's clean frame (no captions) with a big
    title box in the middle, so it survives YouTube cropping Shorts thumbnails to wider shapes.
    Without the segment/title (e.g. re-uploading an old folder), uses the video's first frame."""
    from PIL import Image

    if first_segment and first_segment.exists() and title:
        frame = out.with_name("thumb_frame.png")
        card = render_card(title, out.with_name("thumb_card.png"), style, center_y=HEIGHT // 2,
                           font_size=110, max_width=1000)
        _run(["-ss", "0.1", "-i", str(first_segment), "-frames:v", "1", str(frame)])
        img = Image.alpha_composite(Image.open(frame).convert("RGBA").resize((WIDTH, HEIGHT)), Image.open(card))
        card.unlink(missing_ok=True)
        img.convert("RGB").save(out, quality=88)
        frame.unlink(missing_ok=True)
    else:
        _run(["-ss", "0", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)])
    if out.stat().st_size > 2 * 1024 * 1024:  # YouTube rejects bigger files
        Image.open(out).resize((720, 1280)).save(out, quality=80)
    return out


def render_card(text: str, out: Path, style: str = "classic", center_y: int | None = None,
                top: int = 330, font_size: int = 92, max_width: int = 900, keep_case: bool = False) -> Path:
    """One rounded purple box with the text wrapped and centered inside it (full-frame transparent PNG).
    Drawn as a single shape, so multi-line text never produces overlapping per-line boxes.
    keep_case: show the text exactly as written instead of in capitals."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(FONTS_DIR / ("Anton-Regular.ttf" if style == "bold" else "ArchivoBlack-Regular.ttf")),
                              font_size)
    pad_x, pad_y, gap = 48, 36, int(font_size * 0.22)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines, line = [], ""
    for word in (text if keep_case else caps(text)).split():
        trial = f"{line} {word}".strip()
        # A web address always starts its own line, so it stands out.
        if line and (_is_url(word) or draw.textlength(trial, font=font) > max_width - 2 * pad_x):
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    box_w = int(max(draw.textlength(l, font=font) for l in lines)) + 2 * pad_x
    box_h = len(lines) * line_h + (len(lines) - 1) * gap + 2 * pad_y + (14 if _is_url(lines[-1]) else 0)  # room under a red URL box
    x0 = (WIDTH - box_w) // 2
    y0 = (center_y - box_h // 2) if center_y is not None else top
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=28, fill=CARD_FILL)
    y = y0 + pad_y
    space = d.textlength(" ", font=font)
    for l in lines:
        x = (WIDTH - d.textlength(l, font=font)) / 2
        for word in l.split(" "):  # web addresses get a bold red highlight behind them
            ww = d.textlength(word, font=font)
            if _is_url(word):
                d.rounded_rectangle([x - 18, y - 4, x + ww + 18, y + line_h - 2], radius=16, fill=URL_HIGHLIGHT)
            d.text((x, y), word, font=font, fill="white")
            x += ww + space
        y += line_h + gap
    img.save(out)
    return out


def final_render(segments: list[Path], narration: Path, captions: Path, out: Path, music_volume: float = 0.10,
                 cards: list[tuple[Path, float, float, bool]] = (),
                 pop: tuple[Path, float, float, int] | None = None) -> None:
    """cards: (png, start, end, fade_in) overlays such as the title and the follow-for-more box.
    pop: (png, start, end, center_y) - an image that pops in CapCut-style (zooms up from tiny with a
    slight overshoot, then settles), centered horizontally at center_y. Used for the channel logo."""
    workdir = out.parent
    listfile = workdir / "segments.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for p in segments), encoding="utf-8")

    tracks = sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in {".mp3", ".m4a", ".wav"}) if MUSIC_DIR.exists() else []
    args = ["-reinit_filter", "0", "-f", "concat", "-safe", "0", "-i", listfile.name, "-i", narration.name]
    fonts = os.path.relpath(FONTS_DIR, workdir).replace("\\", "/")
    # Segments must look identical to FFmpeg; a mid-stream change (e.g. pixel shape or color tags) made it
    # rebuild the filter chain, which stalled the render. Normalize, and never rebuild.
    filters = [f"[0:v]setsar=1,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,subtitles={captions.name}:fontsdir={fonts}[v0]"]
    if tracks:
        args += ["-stream_loop", "-1", "-i", str(random.choice(tracks))]
        af = (f"[2:a]volume={music_volume}[m];"
              "[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        af = "[1:a]anull[a]"
    first = 3 if tracks else 2
    for i, (png, start, end, fade_in) in enumerate(cards):
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{end:.3f}", "-i", png.name]
        fades = (f"fade=t=in:st={start:.3f}:d=0.2:alpha=1," if fade_in else "") + \
                f"fade=t=out:st={max(start, end - 0.3):.3f}:d=0.3:alpha=1"
        filters.append(f"[{first + i}:v]format=rgba,{fades}[c{i}]")
        filters.append(f"[v{i}][c{i}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{i + 1}]")
    last = f"v{len(cards)}"
    if pop:
        png, start, end, cy = pop
        k = first + len(cards)
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{end:.3f}", "-i", png.name]
        # p: 0->1 over 0.5s from `start`; ease-out-back gives the pop with a ~10% overshoot.
        p = f"clip((t-{start:.3f})/0.5,0,1)"
        s = f"(1+2.70158*pow({p}-1,3)+1.70158*pow({p}-1,2))"
        filters.append(f"[{k}:v]format=rgba,scale=w='max(2,iw*{s})':h=-1:eval=frame[pop]")
        filters.append(f"[{last}][pop]overlay=x='(W-w)/2':y='{cy}-h/2':eval=frame:"
                       f"enable='between(t,{start:.3f},{end:.3f})'[vpop]")
        last = "vpop"
    filters.append(f"[{last}]null[v]")
    args += ["-filter_complex", ";".join(filters + [af]), "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out.name]
    _run(args, cwd=workdir)
