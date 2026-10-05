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
            f"crop={WIDTH}:{HEIGHT},format=yuv420p")
    if clip and clip.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        src = ["-loop", "1", "-framerate", str(FPS), "-i", str(clip)]
    elif clip:
        src = ["-stream_loop", "-1", "-i", str(clip)]
    else:
        src = ["-f", "lavfi", "-i", f"color=c=0x111111:s={WIDTH}x{HEIGHT}:r={FPS}"]
    _run([*src, "-t", f"{duration:.3f}", "-vf", zoom, "-an",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), str(out)])


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
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(title_secs)},Title,,0,0,0,,{{\\fad(0,300)}}{title.upper()}")
    if outro:  # "follow for more" card in the middle of the screen, popping in
        start, end, text = outro
        lines.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Outro,,0,0,0,,"
                     rf"{{\fscx70\fscy70\t(0,160,\fscx100\fscy100)}}{text.upper()}")
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
        text = " ".join(w["text"] for w in g).upper().replace("{", "").replace("}", "")
        pop = r"{\fscx85\fscy85\t(0,90,\fscx100\fscy100)}"
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{pop}{text}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def final_render(segments: list[Path], narration: Path, captions: Path, out: Path, music_volume: float = 0.10) -> None:
    workdir = out.parent
    listfile = workdir / "segments.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for p in segments), encoding="utf-8")

    tracks = sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in {".mp3", ".m4a", ".wav"}) if MUSIC_DIR.exists() else []
    args = ["-f", "concat", "-safe", "0", "-i", listfile.name, "-i", narration.name]
    fonts = os.path.relpath(FONTS_DIR, workdir).replace("\\", "/")
    vf = f"[0:v]subtitles={captions.name}:fontsdir={fonts}[v]"
    if tracks:
        args += ["-stream_loop", "-1", "-i", str(random.choice(tracks))]
        af = (f"[2:a]volume={music_volume}[m];"
              "[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        af = "[1:a]anull[a]"
    args += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out.name]
    _run(args, cwd=workdir)
