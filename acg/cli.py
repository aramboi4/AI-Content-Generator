"""python -m acg make --niche "space facts" [--topic ...] [--upload]"""
import argparse
import json
import re
import sys
from datetime import datetime

from . import config


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "video"


def make(args: argparse.Namespace) -> None:
    if not config.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is not set - add it to .env (free key: https://aistudio.google.com/apikey)")

    from .footage import fetch_clip, provider
    from .guide import write_guide
    from .media import concat_audio, final_render, render_segment, write_captions
    from .trends import youtube_trends
    from .voice import synthesize_scenes
    from .writer import research_trends, write_package

    research = ""
    if not args.no_research:
        print("1/6 Researching current trends (YouTube + web search)...")
        parts = []
        try:
            yt = youtube_trends(args.niche)
            if yt:
                parts.append("## What's performing on YouTube Shorts right now\n" + yt)
            else:
                print("    YT_API_KEY not set or no results - skipping YouTube trend data.")
        except Exception as e:
            print(f"    YouTube trend lookup failed ({e}) - continuing.")
        web = research_trends(args.niche, args.topic) if config.WEB_SEARCH else ""
        if web:
            parts.append("## Web search findings\n" + web)
        research = "\n\n".join(parts)

    print("2/6 Writing script, titles, captions and hashtags...")
    pkg = write_package(args.niche, args.topic, research, args.seconds, args.style)

    workdir = config.OUTPUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(pkg.topic)}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    if research:
        (workdir / "research.md").write_text(research, encoding="utf-8")
    print(f"    Topic: {pkg.topic}  ({len(pkg.scenes)} scenes)  -> {workdir}")

    print("3/6 Generating voiceover...")
    rate = "+8%" if args.style == "facts" else "-4%"  # stories read slower
    voices = synthesize_scenes([s.narration for s in pkg.scenes], args.voice, workdir, rate)

    print("4/6 Fetching stock footage and rendering scenes...")
    source = provider()
    if not source:
        print("    PIXABAY_API_KEY not set - using plain backgrounds.")
    else:  # Pixabay/Pexels ask that the footage source be credited
        pkg.youtube.description += f"

Stock footage: {source}"
        (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    used: set[int] = set()
    segments, words, t = [], [], 0.0
    for i, (scene, v) in enumerate(zip(pkg.scenes, voices)):
        clip = fetch_clip(scene.visual_query, v["duration"], used, workdir / f"clip_{i:02d}.mp4")
        print(f"    scene {i + 1}: {scene.visual_query!r} -> {'ok' if clip else 'no footage, plain background'}")
        seg = workdir / f"seg_{i:02d}.mp4"
        render_segment(clip, v["duration"], seg)
        segments.append(seg)
        words += [{**w, "start": w["start"] + t, "end": w["end"] + t, "scene": i} for w in v["words"]]
        t += v["duration"]

    print("5/6 Adding captions, music and final render...")
    narration = workdir / "narration.m4a"
    concat_audio([v["audio"] for v in voices], narration)
    captions = workdir / "captions.ass"
    write_captions(words, captions)
    video = workdir / "video.mp4"
    final_render(segments, narration, captions, video)

    url = None
    if args.upload:
        print("6/6 Uploading to YouTube...")
        from .youtube import upload
        url = upload(video, pkg.youtube, privacy=args.privacy, publish_at=args.publish_at)
        print(f"    {url}")
    else:
        print("6/6 Skipping YouTube upload (use --upload).")

    write_guide(pkg, workdir / "POSTING_GUIDE.md", url)
    if not args.keep_temp:
        for p in workdir.glob("*"):
            if p.name.startswith(("clip_", "seg_", "voice_")) or p.suffix == ".txt":
                p.unlink()
    print(f"\nDone: {video}\nPosting guide: {workdir / 'POSTING_GUIDE.md'}  ({t:.0f}s video)")


def main() -> None:
    p = argparse.ArgumentParser(prog="acg", description="Faceless short-form video generator")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="Generate one video + posting guide")
    m.add_argument("--niche", required=True, help='e.g. "space facts", "stoic quotes", "money tips"')
    m.add_argument("--style", default="facts", choices=["facts", "story"], help="fun facts (fast, punchy) or inspiring story (slower, narrative)")
    m.add_argument("--topic", help="Specific topic; omit to let it pick from current trends")
    m.add_argument("--seconds", type=int, default=45, help="Target length (default 45)")
    m.add_argument("--voice", default=config.VOICE, help="edge-tts voice (run: edge-tts --list-voices)")
    m.add_argument("--no-research", action="store_true", help="Skip the live trend web search")
    m.add_argument("--upload", action="store_true", help="Upload to YouTube when done")
    m.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    m.add_argument("--publish-at", help="Schedule YouTube publish, ISO UTC e.g. 2026-10-05T17:00:00Z")
    m.add_argument("--keep-temp", action="store_true", help="Keep intermediate files")
    args = p.parse_args()
    try:
        make(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
