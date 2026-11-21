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
    return at.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def check_recent(args: argparse.Namespace) -> None:
    from . import history
    e = history.uploaded_recently(args.style, args.hours)
    if e:
        print(f"Already uploaded in the last {args.hours:g}h: {e['topic']} ({e['youtube']})")
        sys.exit(0)
    print(f"No {args.style} video uploaded in the last {args.hours:g}h.")
    sys.exit(1)


def refresh_screens(args: argparse.Namespace) -> None:
    import tempfile
    from pathlib import Path
    from .screens import SAVED, capture, save_reference_copies
    with tempfile.TemporaryDirectory() as tmp:
        shots = capture(args.website, Path(tmp))
        if not shots or shots[0].parent == SAVED:
            sys.exit(f"Couldn't screenshot {args.website} - is Playwright installed (pip install playwright, "
                     "python -m playwright install chromium)?")
        save_reference_copies(shots)
    print(f"Saved {len(shots)} screenshot(s) to {SAVED}")


def telegram_setup(args: argparse.Namespace) -> None:
    from . import notify
    if not config.TELEGRAM_BOT_TOKEN:
        sys.exit("Add TELEGRAM_BOT_TOKEN to .env first (see README 'Phone delivery').")
    chat_id = notify.find_chat_id()
    if not chat_id:
        sys.exit("No messages found - open your bot in Telegram, press Start (or send 'hi'), then run this again.")
    print(f"Your TELEGRAM_CHAT_ID is: {chat_id}\nAdd it to .env and as a GitHub secret.")


def _slot_time(hhmm: str) -> str | None:
    """Today's HH:MM slot (ACG_TZ) as ISO UTC if it's still ahead; None means "post now".
    A late run (slot already passed, or a run after midnight for yesterday's slot) posts immediately
    instead of waiting ~20 hours for the next day's slot."""
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    h, m = map(int, hhmm.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    ahead = at - now
    if timedelta(minutes=15) <= ahead <= timedelta(hours=12):
        return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _publish_at(args: argparse.Namespace) -> str | None:
    if getattr(args, "publish_slot", None):
        return _slot_time(args.publish_slot)
    return _next_publish_time(args.publish_next) if args.publish_next else args.publish_at


AD_LINK_SECONDS = 4.5  # ads end with the website card on screen for at least this long

# Current step and non-fatal problems, reported to Telegram by main().
STATE: dict = {"stage": "setup", "warnings": []}


def _warn(msg: str) -> None:
    print(f"    WARNING: {msg}")
    STATE["warnings"].append(msg)


def make(args: argparse.Namespace) -> None:
    if not config.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is not set - add it to .env (free key: https://aistudio.google.com/apikey)")
    if args.niche == "auto":  # mornings: fun facts or feel-good science; evenings: stories, kind animals, traditions
        from .writer import TOPIC_MIX
        if args.style not in TOPIC_MIX:
            sys.exit(f"--niche auto only works with --style {' or '.join(TOPIC_MIX)}.")
        args.niche = random.choice(list(TOPIC_MIX[args.style]))
    print(f"    topic area: {args.niche}")

    from .footage import fetch_clip, provider
    from . import history
    from .guide import write_guide
    from .config import HEIGHT
    from .media import (card_top, concat_audio, final_render, logo_badge, render_card, render_segment,
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

    from . import voice as voice_mod, writer as writer_mod
    fast_voice = voice_mod.inworld_available()  # Clive/Dennis speak ~30% faster than the fallbacks
    writer_mod.VOICE_PACE = 1.3 if fast_voice else 1.0
    print(f"    Inworld credits available: {'yes' if fast_voice else 'no'}")
    STATE["stage"] = "script"
    print("2/6 Writing script, titles, captions and hashtags...")
    brief = ""
    if args.style == "ad":
        if not args.brief or not args.website:
            sys.exit("--style ad needs --brief (product brief file) and --website.")
        brief = open(args.brief, encoding="utf-8").read()
    # Ending, picked at random: a question + comments prompt, or a lesson/payoff + follow-for-more outro.
    ending = args.ending if args.ending != "random" else random.choice(["question", "statement"])
    if args.style != "ad":
        print(f"    ending style: {ending}")
    past = history.recent_topics(args.style)
    not_again: list[str] = []
    for draft in range(3):
        pkg = write_package(args.niche, args.topic, research, args.seconds, args.style,
                            avoid=past, avoid_hooks=history.recent_hooks(),
                            brief=brief, website=args.website or "", ending=ending, not_again=not_again,
                            language=args.language)
        if args.topic or args.style == "ad":
            break
        # The writer sometimes ignores the "already covered" list and retells a story under a new title.
        try:
            repeat = writer_mod.find_repeat(pkg, args.style, past)
        except Exception as e:  # checker unavailable: keep the draft
            print(f"    repeat check skipped ({type(e).__name__})")
            break
        if not repeat:
            break
        print(f'    "{pkg.topic}" repeats "{repeat}" - rewriting with a different topic')
        not_again.append(repeat)
        if draft == 2:
            _warn(f'The script may repeat an earlier video ("{repeat}"); 3 drafts in a row did.')
    if writer_mod.LAST_WRITER != "Gemini":
        _warn(f"Gemini was unavailable, so the script was written by the backup: {writer_mod.LAST_WRITER}.")
    if args.language == "tl":  # a native-speaker pass so nothing sounds like Google Translate
        writer = writer_mod.LAST_WRITER
        try:
            changed = writer_mod.polish_filipino(pkg, brief)
            print(f"    Filipino polish: {changed} line(s) made more natural")
        except Exception as e:
            _warn(f"The Filipino wording check was skipped ({type(e).__name__}); the first draft was used.")
        writer_mod.LAST_WRITER = writer
    if args.style != "ad":  # the matching call to action is added below; drop any the model wrote itself
        from .writer import strip_cta
        pkg.scenes[-1].narration = strip_cta(pkg.scenes[-1].narration)
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
    # How a video ends:
    # - ends on a question -> that's the ending (sometimes + "let me know in the comments"), no follow outro
    # - ends on a statement (e.g. a story's lesson) -> add the follow-for-more outro
    last = pkg.scenes[-1]
    ends_with_question = last.narration.rstrip().endswith("?") or "comment" in last.narration.lower()
    outro_text = outro_spoken = None
    if args.style == "ad":  # ads always end with the website call to action
        outro_text = args.cta_text or (f"Subukan nang libre sa {args.website.upper()}" if args.language == "tl"
                                       else f"Try it free at {args.website.upper()}")
        outro_spoken = args.cta_voice or outro_text
    elif ends_with_question:
        if "comment" not in last.narration.lower() and random.random() < config.COMMENT_CTA_CHANCE:
            last.narration = f"{last.narration.rstrip()} {random.choice(config.COMMENT_CTAS)}"
            print(f"    comment prompt: {last.narration!r}")
    elif config.OUTROS and not args.no_outro and (args.outro or random.random() < config.OUTRO_CHANCE):
        # Avoid the endings used in the last few videos so it doesn't feel repetitive.
        recent = set(history.recent_outros(min(6, len(config.OUTROS) - 1)))
        outro_text = outro_spoken = random.choice([o for o in config.OUTROS if o not in recent] or config.OUTROS)
    if outro_text:
        print(f"    ending: {outro_text!r}")
    narrations = [s.narration for s in pkg.scenes] + ([outro_spoken] if outro_spoken else [])
    voices = synthesize_scenes(narrations, args.voice, workdir, rate, language=args.language)
    engine = voices[0]["engine"] if voices else ""
    print(f"    voice: {engine}")
    inworld_error = voices[0].get("inworld_error") if voices else None
    # Inworld having no credits is the normal state on the free plan, so only other Inworld errors are flagged.
    if inworld_error and "402" not in inworld_error:
        _warn(f"The Inworld voice (Clive/Dennis) failed, so this video uses Kokoro instead. Details: {inworld_error}")
    if engine == "piper":
        _warn("Kokoro failed, so this video uses the backup Piper voice (more robotic). "
              f"Details: {voices[0].get('kokoro_error') or voices[0].get('edge_error')}")
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
        STATE["stage"] = "lengthen"
        try:
            at, extra = extend_package(pkg, args.style, args.min_seconds - content + 2, language=args.language)
            if not extra:
                continue
            extra_voices = synthesize_scenes([s.narration for s in extra], args.voice, workdir, rate,
                                             prefix=f"extra{round_}", engine=voices[0]["engine"],
                                             language=args.language)
        except Exception as e:  # a shorter video is better than no video
            _warn(f"Couldn't add extra scenes ({type(e).__name__}: {str(e)[:120]}) - the video is a bit shorter "
                  f"than {args.min_seconds}s.")
            break
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
    if visuals == "auto":  # AI scene images when Cloudflare is set up, otherwise stock footage
        visuals = "ai" if images.available() else "stock"
        if visuals == "stock":
            _warn("Used stock footage instead of AI images: CF_ACCOUNT_ID and CF_API_TOKEN are not set "
                  "(add them to the GitHub repository secrets).")
    if visuals == "ai" and not images.available():
        sys.exit("--visuals ai needs CF_ACCOUNT_ID and CF_API_TOKEN in .env (see README).")
    source = provider()
    char_ref = None
    app_screens, placed = [], 0
    if visuals == "ai" and args.style == "ad" and args.website and any(s.shows_app for s in pkg.scenes):
        from .screens import all_screens, place_on_phone
        app_screens = all_screens(args.website, workdir)
        print(f"    {len(app_screens)} app screen(s) ready for the phone scenes")
    if visuals == "ai":
        print("4/6 Generating AI scene images and rendering scenes...")
        try:  # a head-and-shoulders reference keeps the face and clothes without pinning the pose
            char_ref = images.generate(
                f"Head and shoulders portrait of {pkg.character}, neutral expression, plain soft background",
                workdir / "character.jpg", seed=args.seed)
        except Exception as e:  # e.g. daily free allowance used up: every scene falls back to stock below
            print(f"    character portrait failed ({str(e)[:100]})")
    else:
        print("4/6 Fetching stock footage and rendering scenes...")
        if not source:
            _warn("No footage key (PIXABAY_API_KEY) - the video uses plain backgrounds.")
    used: set[int] = set()
    segments, words, t, last_clip = [], [], 0.0, None
    image_fails, footage_errors, unmatched, reused = 0, [], 0, False
    for i, (scene, v) in enumerate(zip(pkg.scenes, voices)):
        clip = None
        if visuals == "ai":
            try:
                has_character = char_ref is not None and "the character" in scene.image_prompt.lower()
                prompt = scene.image_prompt
                if has_character:
                    prompt += (f". Show this action clearly with a new pose and setting. Use image 0 ONLY for the "
                               f"character's face, hair and clothes: {pkg.character}. Do not copy its pose, framing "
                               "or background")
                clip, review = images.generate_checked(prompt, scene.narration, workdir / f"scene_{i:02d}.jpg",
                                                       refs=[char_ref] if has_character else [],
                                                       seed=args.seed + i + 1, plan=scene.image_prompt)
                print(f"    scene {i + 1}: {review}")
                if scene.shows_app and app_screens:  # put the real website on the phone in the picture
                    try:
                        skipped = place_on_phone(clip, app_screens[placed % len(app_screens)])
                    except Exception as e:
                        skipped = f"{type(e).__name__}: {str(e)[:80]}"
                    placed += not skipped
                    print(f"    scene {i + 1}: app screen " + (f"not added ({skipped})" if skipped else "added to the phone"))
            except Exception as e:  # e.g. daily free allowance used up: fall back to stock footage
                image_fails += 1
                print(f"    scene {i + 1}: image failed ({str(e)[:100]})")
        # One blocked image: keep the previous picture so a real clip doesn't appear mid-cartoon.
        if clip is None and visuals == "ai" and last_clip is not None and last_clip.suffix == ".jpg" and not reused:
            reused = True
            print(f"    scene {i + 1}: keeping the previous picture")
        elif clip is None and source:
            try:
                clip, how = fetch_clip(scene.visual_queries, v["duration"], used, workdir / f"clip_{i:02d}.mp4",
                                       narration=scene.narration)
                print(f"    scene {i + 1}: {how}")
            except Exception as e:  # footage site down: keep going with the previous clip
                footage_errors.append(str(e)[:120])
            unmatched += clip is None
        status = "ok" if clip else "no match, reusing previous" if last_clip else "no match, plain background"
        print(f"    scene {i + 1}: {scene.image_prompt if visuals == 'ai' else scene.visual_queries} -> {status}")
        if clip is not None and clip != last_clip:
            reused = False
        clip = last_clip = clip or last_clip
        seg = workdir / f"seg_{i:02d}.mp4"
        render_segment(clip, v["duration"], seg, zoom_out=i % 2 == 1)
        segments.append(seg)
        words += [{**w, "start": w["start"] + t, "end": w["end"] + t, "scene": i} for w in v["words"]]
        t += v["duration"]
    STATE["stage"] = "render"
    if source and (visuals == "stock" or any(workdir.glob("clip_*.mp4"))):  # Pixabay/Pexels ask that the footage source be credited
        pkg.youtube.description += f"\n\nStock footage: {source}"
    (workdir / "package.json").write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    if image_fails:
        _warn(f"{image_fails} AI image(s) failed (safety filter or free daily allowance) - the previous picture "
              "or stock footage was used instead.")
    if footage_errors:
        _warn(f"Footage site errors on {len(footage_errors)} scene(s): {footage_errors[0]}")
    if unmatched >= max(2, len(pkg.scenes) // 2):
        _warn(f"No matching footage for {unmatched} of {len(pkg.scenes)} scenes - clips were reused.")

    outro_at = None
    if outro and args.style == "ad" and outro[0]["duration"] < AD_LINK_SECONDS:
        # Keep the website on screen long enough to read and type: pad the call to action with quiet time.
        from .media import pad_audio
        outro[0]["audio"] = pad_audio(outro[0]["audio"], AD_LINK_SECONDS)
        outro[0]["duration"] = AD_LINK_SECONDS
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
    branded = args.style != "ad"  # product ads stay separate from the channel brand
    pop = None
    if outro_at is not None:
        card = render_card(outro_text, workdir / "card_outro.png", args.caption_style,
                           center_y=HEIGHT // 2 + 120, font_size=80, max_width=990)
        if logo.exists() and branded:  # channel logo pops in (CapCut-style) above the follow-for-more box
            badge = logo_badge(logo, workdir / "card_logo.png")
            from PIL import Image
            badge_h = Image.open(badge).height
            pop = (badge, outro_at, t, card_top(card) - 40 - badge_h // 2)
        cards.append((card, outro_at, t, True))
    if icon.exists() and branded and not args.no_watermark:  # small channel watermark until the ending card
        cards.append((render_watermark(icon, workdir / "card_watermark.png"), 0.0,
                      outro_at if outro_at is not None else t, False))
    video = workdir / "video.mp4"
    final_render(segments, narration, captions, video, cards=cards, pop=pop)

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
        privacy = args.privacy
        if args.publish_slot and publish_at is None:  # run was late and the slot has passed: post now
            privacy = "public"
            print(f"    the {args.publish_slot} slot has already passed - posting publicly right away")
        url = upload(video, pkg.youtube, privacy=privacy, publish_at=publish_at, thumbnail=thumb)
        if youtube.LAST_THUMBNAIL_ERROR:
            _warn(youtube.LAST_THUMBNAIL_ERROR)
        print(f"    {url}" + (f" (goes public {publish_at})" if publish_at else ""))
    else:
        print("6/6 Skipping YouTube upload (use --upload).")

    guide = workdir / "POSTING_GUIDE.md"
    write_guide(pkg, guide, url)
    history.add({"style": args.style, "niche": args.niche, "topic": pkg.topic, "hook": pkg.scenes[0].narration,
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
    m.add_argument("--niche", required=True, help='e.g. "space facts", "stoic quotes", "money tips", or "auto" '
                   '(random from the style\'s topic mix)')
    m.add_argument("--style", default="facts", choices=["facts", "story", "ad"],
                   help="fun facts (fast, punchy), inspiring story (slower, narrative), or product ad (needs --brief)")
    m.add_argument("--brief", help="Product brief file for --style ad, e.g. ads/logexpense.md")
    m.add_argument("--website", help="Website for --style ad, e.g. logexpense.site")
    m.add_argument("--language", default="en", choices=["en", "tl"],
                   help="en: English (default); tl: natural Filipino/Taglish script with Gemini's Filipino voice")
    m.add_argument("--cta-text", help='Ad ending shown on screen (default "Try it free at <WEBSITE>")')
    m.add_argument("--cta-voice", help="Ad ending as spoken (e.g. spell the site out for the voice)")
    m.add_argument("--topic", help="Specific topic; omit to let it pick from current trends")
    m.add_argument("--seconds", type=int, default=45, help="Target length (default 45)")
    m.add_argument("--min-seconds", type=int, default=30,
                   help="Minimum length of the main content, not counting the outro (default 30)")
    m.add_argument("--visuals", default="auto", choices=["auto", "ai", "stock"],
                   help="AI 3D scene images or stock footage (auto: AI when Cloudflare is set up)")
    m.add_argument("--seed", type=int, default=7, help="Image seed; change it for a different-looking character")
    m.add_argument("--caption-style", default="classic", choices=["classic", "bold"],
                   help="classic: 3-word captions (default); bold: one big word + title card")
    m.add_argument("--voice", default=config.VOICE, help="edge-tts voice (run: edge-tts --list-voices)")
    m.add_argument("--no-research", action="store_true", help="Skip the live trend web search")
    m.add_argument("--upload", action="store_true", help="Upload to YouTube when done")
    m.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    m.add_argument("--publish-at", help="Schedule YouTube publish, ISO UTC e.g. 2026-10-05T17:00:00Z")
    m.add_argument("--publish-next", metavar="HH:MM", help="Schedule for the next HH:MM local time (ACG_TZ, default Asia/Manila)")
    m.add_argument("--publish-slot", metavar="HH:MM",
                   help="Schedule for today's HH:MM if it's still ahead, otherwise post publicly right away")
    m.add_argument("--no-title", action="store_true", help="Don't show the title card at the start")
    m.add_argument("--ending", default="random", choices=["random", "question", "statement"],
                   help="question = ends asking viewers + comments prompt; statement = lesson/payoff + follow outro")
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
    sc = sub.add_parser("screens", help="Refresh the saved phone screenshots of the ad's website (ads/screens)")
    sc.add_argument("--website", default="logexpense.site")
    c = sub.add_parser("check", help="Exit 0 if a video of this style was uploaded recently (used by retry runs)")
    c.add_argument("--style", required=True, choices=["facts", "story", "ad"])
    c.add_argument("--hours", type=float, default=6)
    args = p.parse_args()
    try:
        {"make": make, "upload": upload_existing, "telegram-setup": telegram_setup, "check": check_recent,
         "screens": refresh_screens}[args.cmd](args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        _report_failure(args, exc)
        raise


def _report_failure(args: argparse.Namespace, exc: Exception) -> None:
    """Tell the phone what broke. Leaves a marker so the workflow doesn't send a second, vaguer alert."""
    from . import notify
    if args.cmd in ("telegram-setup", "screens") or not notify.enabled():
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
