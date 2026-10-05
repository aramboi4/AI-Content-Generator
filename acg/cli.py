"""python -m acg make --niche "space facts" [--topic ...] [--upload]"""
import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "video"


def _next_publish_time(hhmm: str) -> str:
    """Next occurrence of local HH:MM (in ACG_TZ) as ISO UTC, at least 15 minutes from now."""
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    h, m = map(int, hhmm.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if at < now + timedelta(minutes=15):
        at += timedelta(days=1)
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _publish_at(args: argparse.Namespace) -> str | None:
    return _next_publish_time(args.publish_next) if args.publish_next else args.publish_at


def make(args: argparse.Namespace) -> None:
    if not config.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is not set - add it to .env (free key: https://aistudio.google.com/apikey)")

    from .footage import fetch_clip, provider
    from . import history
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
    pkg = write_package(args.niche, args.topic, research, args.seconds, args.style,
                        avoid=history.recent_topics(args.style))

    workdir = config.OUTPUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(pkg.topic)}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    if research:
        (workdir / "research.md").write_text(research, encoding="utf-8")
    print(f"    Topic: {pkg.topic}  ({len(pkg.scenes)} scenes)  -> {workdir}")

    print("3/6 Generating voiceover...")
    rate = "+8%" if args.style == "facts" else "-4%"  # stories read slower
    narrations = [s.narration for s in pkg.scenes] + ([config.OUTRO] if config.OUTRO and not args.no_outro else [])
    voices = synthesize_scenes(narrations, args.voice, workdir, rate)
    outro = voices[len(pkg.scenes):]

    from . import images

    visuals = args.visuals
    if visuals == "ai" and not images.available():
        sys.exit("--visuals ai needs CF_ACCOUNT_ID and CF_API_TOKEN in .env (see README).")
    source = provider()
    char_ref = None
    if visuals == "ai":
        print("4/6 Generating AI scene images and rendering scenes...")
        print("    character reference...")
        char_ref = images.generate(
            f"Character design reference: {pkg.character}. Full body, front view, friendly expression, "
            "plain soft background", workdir / "character.jpg", seed=args.seed)
    else:
        print("4/6 Fetching stock footage and rendering scenes...")
        if not source:
            print("    PIXABAY_API_KEY not set - using plain backgrounds.")
    if visuals == "stock" and source:  # Pixabay/Pexels ask that the footage source be credited
        pkg.youtube.description += f"\n\nStock footage: {source}"
        (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    used: set[int] = set()
    segments, words, t, last_clip = [], [], 0.0, None
    for i, (scene, v) in enumerate(zip(pkg.scenes, voices)):
        clip = None
        if visuals == "ai":
            try:
                clip = images.generate(
                    f"{scene.image_prompt}. The character looks exactly like the character in image 0: {pkg.character}",
                    workdir / f"scene_{i:02d}.jpg", refs=[char_ref], seed=args.seed + i + 1)
            except RuntimeError as e:  # e.g. daily free allowance used up: fall back to stock footage
                print(f"    scene {i + 1}: image failed ({str(e)[:100]})")
        if clip is None and source:
            clip = fetch_clip(scene.visual_queries, v["duration"], used, workdir / f"clip_{i:02d}.mp4")
        status = "ok" if clip else "no match, reusing previous" if last_clip else "no match, plain background"
        print(f"    scene {i + 1}: {scene.image_prompt if visuals == 'ai' else scene.visual_queries} -> {status}")
        clip = last_clip = clip or last_clip
        seg = workdir / f"seg_{i:02d}.mp4"
        render_segment(clip, v["duration"], seg, zoom_out=i % 2 == 1)
        segments.append(seg)
        words += [{**w, "start": w["start"] + t, "end": w["end"] + t, "scene": i} for w in v["words"]]
        t += v["duration"]

    outro_at = None
    if outro:  # call to action over the last clip, shown as a text card instead of captions
        outro_at = t
        seg = workdir / "seg_outro.mp4"
        render_segment(last_clip, outro[0]["duration"] + 0.6, seg, zoom_out=True)
        segments.append(seg)
        t += outro[0]["duration"] + 0.6

    print("5/6 Adding captions, music and final render...")
    narration = workdir / "narration.m4a"
    concat_audio([v["audio"] for v in voices], narration)
    captions = workdir / "captions.ass"
    write_captions(words, captions, style=args.caption_style, title=pkg.tiktok.on_screen_title,
                   outro=(outro_at, t, config.OUTRO) if outro_at is not None else None)
    video = workdir / "video.mp4"
    final_render(segments, narration, captions, video)

    url = None
    if args.upload:
        print("6/6 Uploading to YouTube...")
        from .youtube import upload
        publish_at = _publish_at(args)
        url = upload(video, pkg.youtube, privacy=args.privacy, publish_at=publish_at)
        print(f"    {url}" + (f" (goes public {publish_at})" if publish_at else ""))
    else:
        print("6/6 Skipping YouTube upload (use --upload).")

    guide = workdir / "POSTING_GUIDE.md"
    write_guide(pkg, guide, url)
    history.add({"style": args.style, "topic": pkg.topic, "title": pkg.youtube.title, "youtube": url,
                 "folder": workdir.name})
    if os.getenv("GITHUB_STEP_SUMMARY"):  # show captions on the GitHub Actions run page
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(guide.read_text(encoding="utf-8") + "\n")
    if not args.keep_temp:
        for p in workdir.glob("*"):
            if p.name.startswith(("clip_", "seg_", "voice_")) or p.suffix == ".txt":
                p.unlink()
    print(f"\nDone: {video}\nPosting guide: {workdir / 'POSTING_GUIDE.md'}  ({t:.0f}s video)")


def upload_existing(args: argparse.Namespace) -> None:
    from pathlib import Path

    from .guide import write_guide
    from .writer import VideoPackage
    from .youtube import upload

    folder = Path(args.folder)
    video, pkg_file = folder / "video.mp4", folder / "package.json"
    if not video.exists() or not pkg_file.exists():
        sys.exit(f"{folder} needs video.mp4 and package.json (made by 'acg make').")
    pkg = VideoPackage.model_validate_json(pkg_file.read_text(encoding="utf-8-sig"))
    print(f"Uploading '{pkg.youtube.title}' ({args.privacy})...")
    url = upload(video, pkg.youtube, privacy=args.privacy, publish_at=_publish_at(args))
    write_guide(pkg, folder / "POSTING_GUIDE.md", url)
    print(f"Done: {url}")


def main() -> None:
    p = argparse.ArgumentParser(prog="acg", description="Faceless short-form video generator")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="Generate one video + posting guide")
    m.add_argument("--niche", required=True, help='e.g. "space facts", "stoic quotes", "money tips"')
    m.add_argument("--style", default="facts", choices=["facts", "story"], help="fun facts (fast, punchy) or inspiring story (slower, narrative)")
    m.add_argument("--topic", help="Specific topic; omit to let it pick from current trends")
    m.add_argument("--seconds", type=int, default=45, help="Target length (default 45)")
    m.add_argument("--visuals", default="stock", choices=["stock", "ai"],
                   help="stock footage (default) or AI 3D images (needs free Cloudflare setup)")
    m.add_argument("--seed", type=int, default=7, help="Image seed; change it for a different-looking character")
    m.add_argument("--caption-style", default="classic", choices=["classic", "bold"],
                   help="classic: 3-word captions (default); bold: one big word + title card")
    m.add_argument("--voice", default=config.VOICE, help="edge-tts voice (run: edge-tts --list-voices)")
    m.add_argument("--no-research", action="store_true", help="Skip the live trend web search")
    m.add_argument("--upload", action="store_true", help="Upload to YouTube when done")
    m.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    m.add_argument("--publish-at", help="Schedule YouTube publish, ISO UTC e.g. 2026-10-05T17:00:00Z")
    m.add_argument("--publish-next", metavar="HH:MM", help="Schedule for the next HH:MM local time (ACG_TZ, default Asia/Manila)")
    m.add_argument("--no-outro", action="store_true", help='Skip the "follow for more" ending')
    m.add_argument("--keep-temp", action="store_true", help="Keep intermediate files")
    u = sub.add_parser("upload", help="Upload an already-made video folder to YouTube")
    u.add_argument("folder", help="Folder under output/ containing video.mp4 and package.json")
    u.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    u.add_argument("--publish-at", help="Schedule YouTube publish, ISO UTC e.g. 2026-10-05T17:00:00Z")
    u.add_argument("--publish-next", metavar="HH:MM", help="Schedule for the next HH:MM local time")
    args = p.parse_args()
    try:
        make(args) if args.cmd == "make" else upload_existing(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
