"""python -m acg make --niche "space facts" [--topic ...] [--upload]"""
import argparse
import os
import random
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


def _local_time(iso_utc: str) -> str:
    at = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return at.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%b %d, %I:%M %p").replace(" 0", " ")


def telegram_setup(args: argparse.Namespace) -> None:
    from . import notify
    if not config.TELEGRAM_BOT_TOKEN:
        sys.exit("Add TELEGRAM_BOT_TOKEN to .env first (see README 'Phone delivery').")
    chat_id = notify.find_chat_id()
    if not chat_id:
        sys.exit("No messages found - open your bot in Telegram, press Start (or send 'hi'), then run this again.")
    print(f"Your TELEGRAM_CHAT_ID is: {chat_id}\nAdd it to .env and as a GitHub secret.")


def _publish_at(args: argparse.Namespace) -> str | None:
    return _next_publish_time(args.publish_next) if args.publish_next else args.publish_at


# Current step and non-fatal problems, reported to Telegram by main().
STATE: dict = {"stage": "setup", "warnings": []}


def _warn(msg: str) -> None:
    print(f"    WARNING: {msg}")
    STATE["warnings"].append(msg)


def make(args: argparse.Namespace) -> None:
    if not config.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is not set - add it to .env (free key: https://aistudio.google.com/apikey)")

    from .footage import fetch_clip, provider
    from . import history
    from .guide import write_guide
    from .config import HEIGHT
    from .media import (add_logo_above, concat_audio, final_render, render_card, render_segment,
                        render_watermark, write_captions)
    from .trends import youtube_trends
    from .voice import synthesize_scenes
    from .writer import research_trends, write_package

    research = ""
    if not args.no_research:
        STATE["stage"] = "research"
        print("1/6 Researching current trends (YouTube + web search)...")
        parts = []
        try:
            yt = youtube_trends(args.niche)
            if yt:
                parts.append("## What's performing on YouTube Shorts right now\n" + yt)
            elif config.YT_API_KEY:
                _warn("YouTube trend lookup returned nothing - hashtags weren't based on trend data.")
            else:
                print("    YT_API_KEY not set - skipping YouTube trend data.")
        except Exception as e:
            _warn(f"YouTube trend lookup failed ({str(e)[:150]}) - hashtags weren't based on trend data.")
        web = research_trends(args.niche, args.topic) if config.WEB_SEARCH else ""
        if web:
            parts.append("## Web search findings\n" + web)
        research = "\n\n".join(parts)

    STATE["stage"] = "script"
    print("2/6 Writing script, titles, captions and hashtags...")
    brief = ""
    if args.style == "ad":
        if not args.brief or not args.website:
            sys.exit("--style ad needs --brief (product brief file) and --website.")
        brief = open(args.brief, encoding="utf-8").read()
    pkg = write_package(args.niche, args.topic, research, args.seconds, args.style,
                        avoid=history.recent_topics(args.style), avoid_hooks=history.recent_hooks(),
                        brief=brief, website=args.website or "")
    if args.style == "ad" and args.website.lower() not in pkg.youtube.description.lower():
        pkg.youtube.description = f"Try it free: https://{args.website}\n\n{pkg.youtube.description}"

    workdir = config.OUTPUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(pkg.topic)}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    if research:
        (workdir / "research.md").write_text(research, encoding="utf-8")
    print(f"    Topic: {pkg.topic}  ({len(pkg.scenes)} scenes)  -> {workdir}")

    STATE["stage"] = "voice"
    print("3/6 Generating voiceover...")
    rate = {"facts": "+8%", "ad": "+4%"}.get(args.style, "-4%")  # stories read slower
    outro_text = outro_spoken = None
    if args.style == "ad":  # ads always end with the website call to action
        outro_text = args.cta_text or f"Try it free at {args.website.upper()}"
        outro_spoken = args.cta_voice or outro_text
    elif config.OUTROS and not args.no_outro and (args.outro or random.random() < config.OUTRO_CHANCE):
        # Avoid the endings used in the last few videos so it doesn't feel repetitive.
        recent = set(history.recent_outros(min(6, len(config.OUTROS) - 1)))
        outro_text = outro_spoken = random.choice([o for o in config.OUTROS if o not in recent] or config.OUTROS)
    if outro_text:
        print(f"    ending: {outro_text!r}")
    # When the video ends on a question, about half the time invite viewers to answer in the comments.
    last = pkg.scenes[-1]
    if args.style != "ad" and last.narration.rstrip().endswith("?") and random.random() < config.COMMENT_CTA_CHANCE \
            and "comment" not in last.narration.lower():
        last.narration = f"{last.narration.rstrip()} {random.choice(config.COMMENT_CTAS)}"
        print(f"    comment prompt: {last.narration!r}")
    narrations = [s.narration for s in pkg.scenes] + ([outro_spoken] if outro_spoken else [])
    voices = synthesize_scenes(narrations, args.voice, workdir, rate)
    if voices and voices[0].get("inworld_error"):
        _warn("The Inworld voice (Clive/Dennis) couldn't be used - the free minutes may be used up - so this "
              f"video uses a backup voice. Details: {voices[0]['inworld_error']}")
    if voices and voices[0]["engine"] == "piper":
        _warn("Microsoft's voice service (edge-tts) refused the connection, so this video uses the backup "
              f"Piper voice. Details: {voices[0]['edge_error']}")
    outro = voices[len(pkg.scenes):]
    voices = voices[:len(pkg.scenes)]

    # Make sure the main content (not counting the outro) is at least --min-seconds long.
    from .writer import extend_package
    for round_ in range(1, 3):
        content = sum(v["duration"] for v in voices)
        if content >= args.min_seconds:
            break
        print(f"    content is {content:.0f}s (< {args.min_seconds}s) - adding more "
              f"{'facts' if args.style == 'facts' else 'scenes'}...")
        at, extra = extend_package(pkg, args.style, args.min_seconds - content + 2)
        if not extra:
            continue
        extra_voices = synthesize_scenes([s.narration for s in extra], args.voice, workdir, rate,
                                         prefix=f"extra{round_}")
        pkg.scenes[at:at] = extra
        voices[at:at] = extra_voices
    else:
        if sum(v["duration"] for v in voices) < args.min_seconds:
            _warn(f"Video content is only {sum(v['duration'] for v in voices):.0f}s (target {args.min_seconds}s).")
    (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    print(f"    content length: {sum(v['duration'] for v in voices):.0f}s in {len(pkg.scenes)} scenes"
          + (" + outro" if outro else ""))

    from . import images

    STATE["stage"] = "footage"
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
            _warn("No footage key (PIXABAY_API_KEY) - the video uses plain backgrounds.")
    if visuals == "stock" and source:  # Pixabay/Pexels ask that the footage source be credited
        pkg.youtube.description += f"\n\nStock footage: {source}"
        (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    used: set[int] = set()
    segments, words, t, last_clip = [], [], 0.0, None
    image_fails, footage_errors, unmatched = 0, [], 0
    for i, (scene, v) in enumerate(zip(pkg.scenes, voices)):
        clip = None
        if visuals == "ai":
            try:
                clip = images.generate(
                    f"{scene.image_prompt}. The character looks exactly like the character in image 0: {pkg.character}",
                    workdir / f"scene_{i:02d}.jpg", refs=[char_ref], seed=args.seed + i + 1)
            except RuntimeError as e:  # e.g. daily free allowance used up: fall back to stock footage
                image_fails += 1
                print(f"    scene {i + 1}: image failed ({str(e)[:100]})")
        if clip is None and source:
            try:
                clip = fetch_clip(scene.visual_queries, v["duration"], used, workdir / f"clip_{i:02d}.mp4")
            except Exception as e:  # footage site down: keep going with the previous clip
                footage_errors.append(str(e)[:120])
            unmatched += clip is None
        status = "ok" if clip else "no match, reusing previous" if last_clip else "no match, plain background"
        print(f"    scene {i + 1}: {scene.image_prompt if visuals == 'ai' else scene.visual_queries} -> {status}")
        clip = last_clip = clip or last_clip
        seg = workdir / f"seg_{i:02d}.mp4"
        render_segment(clip, v["duration"], seg, zoom_out=i % 2 == 1)
        segments.append(seg)
        words += [{**w, "start": w["start"] + t, "end": w["end"] + t, "scene": i} for w in v["words"]]
        t += v["duration"]
    STATE["stage"] = "render"
    if image_fails:
        _warn(f"{image_fails} AI image(s) failed (free daily allowance?) - stock footage used instead.")
    if footage_errors:
        _warn(f"Footage site errors on {len(footage_errors)} scene(s): {footage_errors[0]}")
    if unmatched >= max(2, len(pkg.scenes) // 2):
        _warn(f"No matching footage for {unmatched} of {len(pkg.scenes)} scenes - clips were reused.")

    outro_at = None
    if outro:  # call to action over the last clip, shown as a text card instead of captions
        outro_at = t
        seg = workdir / "seg_outro.mp4"
        render_segment(last_clip, outro[0]["duration"] + 0.6, seg, zoom_out=True)
        segments.append(seg)
        t += outro[0]["duration"] + 0.6

    print("5/6 Adding captions, music and final render...")
    narration = workdir / "narration.m4a"
    concat_audio([v["audio"] for v in voices + outro], narration)  # outro voice comes last
    captions = workdir / "captions.ass"
    write_captions(words, captions, style=args.caption_style)
    # Title (first 3s, also the cover frame) and the follow-for-more ending are single purple boxes.
    cards = []
    if not args.no_title:
        cards.append((render_card(pkg.tiktok.on_screen_title, workdir / "card_title.png", args.caption_style,
                                  top=330, font_size=86, max_width=990), 0.0, min(3.0, t), False))
    logo, icon = config.BRAND_DIR / "logo.png", config.BRAND_DIR / "logo_icon.png"
    if outro_at is not None:
        card = render_card(outro_text, workdir / "card_outro.png", args.caption_style,
                           center_y=HEIGHT // 2 + 120, font_size=80, max_width=990)
        if logo.exists():  # channel logo above the follow-for-more box
            add_logo_above(card, logo)
        cards.append((card, outro_at, t, True))
    if icon.exists() and not args.no_watermark:  # small channel watermark until the ending card
        cards.append((render_watermark(icon, workdir / "card_watermark.png"), 0.0,
                      outro_at if outro_at is not None else t, False))
    video = workdir / "video.mp4"
    final_render(segments, narration, captions, video, cards=cards)

    url, publish_at = None, None
    STATE["stage"] = "upload"
    if args.upload:
        print("6/6 Uploading to YouTube...")
        from .youtube import upload
        publish_at = _publish_at(args)
        from . import youtube
        from .media import make_thumbnail
        thumb = (make_thumbnail(video, workdir / "thumbnail.jpg", segments[0], pkg.tiktok.on_screen_title,
                                args.caption_style) if config.CUSTOM_THUMBNAIL and not args.no_title else None)
        url = upload(video, pkg.youtube, privacy=args.privacy, publish_at=publish_at, thumbnail=thumb)
        if youtube.LAST_THUMBNAIL_ERROR:
            _warn(youtube.LAST_THUMBNAIL_ERROR)
        print(f"    {url}" + (f" (goes public {publish_at})" if publish_at else ""))
    else:
        print("6/6 Skipping YouTube upload (use --upload).")

    guide = workdir / "POSTING_GUIDE.md"
    write_guide(pkg, guide, url)
    history.add({"style": args.style, "topic": pkg.topic, "hook": pkg.scenes[0].narration,
                 "outro": outro_text if args.style != "ad" else None, "title": pkg.youtube.title, "youtube": url,
                 "folder": workdir.name})
    if os.getenv("GITHUB_STEP_SUMMARY"):  # show captions on the GitHub Actions run page
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(guide.read_text(encoding="utf-8") + "\n")
    from . import notify
    if notify.enabled():
        print("    Sending video + captions to Telegram...")
        try:
            notify.send_video(video, pkg, url, _local_time(publish_at) if publish_at else None,
                              posting_guide=notify.PH_POSTING_GUIDE.replace("logexpense.site", args.website)
                              if args.style == "ad" else None)
            if STATE["warnings"]:
                notify.send_warnings(f"{args.style.title()} video", STATE["warnings"])
        except Exception as e:  # never fail the run just because the phone notification failed
            print(f"    Telegram send failed: {e}")
    if not args.keep_temp:
        for p in workdir.glob("*"):
            if p.name.startswith(("clip_", "seg_", "voice_", "extra", "card_")) or p.suffix == ".txt":
                p.unlink()
    print(f"\nDone: {video}\nPosting guide: {workdir / 'POSTING_GUIDE.md'}  ({t:.0f}s video)")


def upload_existing(args: argparse.Namespace) -> None:
    from pathlib import Path

    STATE["stage"] = "upload"
    from .guide import write_guide
    from .writer import VideoPackage
    from .youtube import upload

    folder = Path(args.folder)
    video, pkg_file = folder / "video.mp4", folder / "package.json"
    if not video.exists() or not pkg_file.exists():
        sys.exit(f"{folder} needs video.mp4 and package.json (made by 'acg make').")
    pkg = VideoPackage.model_validate_json(pkg_file.read_text(encoding="utf-8-sig"))
    print(f"Uploading '{pkg.youtube.title}' ({args.privacy})...")
    from . import youtube
    from .media import make_thumbnail
    url = upload(video, pkg.youtube, privacy=args.privacy, publish_at=_publish_at(args),
                 thumbnail=make_thumbnail(video, folder / "thumbnail.jpg") if config.CUSTOM_THUMBNAIL else None)
    if youtube.LAST_THUMBNAIL_ERROR:
        print(f"Warning: {youtube.LAST_THUMBNAIL_ERROR}")
    write_guide(pkg, folder / "POSTING_GUIDE.md", url)
    print(f"Done: {url}")


def main() -> None:
    p = argparse.ArgumentParser(prog="acg", description="Faceless short-form video generator")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="Generate one video + posting guide")
    m.add_argument("--niche", required=True, help='e.g. "space facts", "stoic quotes", "money tips"')
    m.add_argument("--style", default="facts", choices=["facts", "story", "ad"],
                   help="fun facts (fast, punchy), inspiring story (slower, narrative), or product ad (needs --brief)")
    m.add_argument("--brief", help="Product brief file for --style ad, e.g. ads/logexpense.md")
    m.add_argument("--website", help="Website for --style ad, e.g. logexpense.site")
    m.add_argument("--cta-text", help='Ad ending shown on screen (default "Try it free at <WEBSITE>")')
    m.add_argument("--cta-voice", help="Ad ending as spoken (e.g. spell the site out for the voice)")
    m.add_argument("--topic", help="Specific topic; omit to let it pick from current trends")
    m.add_argument("--seconds", type=int, default=45, help="Target length (default 45)")
    m.add_argument("--min-seconds", type=int, default=30,
                   help="Minimum length of the main content, not counting the outro (default 30)")
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
    m.add_argument("--no-title", action="store_true", help="Don't show the title card at the start")
    m.add_argument("--no-watermark", action="store_true", help="Don't show the channel logo watermark")
    m.add_argument("--outro", action="store_true", help='Always add the "follow for more" ending (default: 50%% chance)')
    m.add_argument("--no-outro", action="store_true", help='Never add the "follow for more" ending')
    m.add_argument("--keep-temp", action="store_true", help="Keep intermediate files")
    u = sub.add_parser("upload", help="Upload an already-made video folder to YouTube")
    u.add_argument("folder", help="Folder under output/ containing video.mp4 and package.json")
    u.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    u.add_argument("--publish-at", help="Schedule YouTube publish, ISO UTC e.g. 2026-10-05T17:00:00Z")
    u.add_argument("--publish-next", metavar="HH:MM", help="Schedule for the next HH:MM local time")
    sub.add_parser("telegram-setup", help="Print your Telegram chat id (after messaging your bot once)")
    args = p.parse_args()
    try:
        {"make": make, "upload": upload_existing, "telegram-setup": telegram_setup}[args.cmd](args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        _report_failure(args, exc)
        raise


def _report_failure(args: argparse.Namespace, exc: Exception) -> None:
    """Tell the phone what broke. Leaves a marker so the workflow doesn't send a second, vaguer alert."""
    from . import notify
    if args.cmd == "telegram-setup" or not notify.enabled():
        return
    what = f"{args.style.title()} video" if args.cmd == "make" else "Upload"
    try:
        notify.send_failure(what, STATE["stage"], exc)
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        (config.OUTPUT_DIR / ".failure_reported").write_text(STATE["stage"], encoding="utf-8")
    except Exception as e:
        print(f"Could not send failure alert to Telegram: {e}")


if __name__ == "__main__":
    main()
