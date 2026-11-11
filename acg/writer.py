"""Gemini (free tier) calls: live trend research, then the script + per-platform post copy."""
import json
import os
import random
import re
import time
from datetime import date

import httpx
import requests
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from .config import GEMINI_API_KEY, GROQ_API_KEY, INWORLD_API_KEY, MODEL

# A time limit, so a request that never answers moves on to the next model or backup instead of hanging the run.
client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=120_000))  # milliseconds
YOUTUBE_ONLY_TAGS = re.compile(r"#(?:youtube)?shorts?(?:feed|video)?\b", re.IGNORECASE)

# Free-tier models get busy (503) or rate limited (429); fall back through these.
MODELS = list(dict.fromkeys([MODEL, "gemini-3.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]))


def _generate(contents, config: types.GenerateContentConfig | None = None, rounds: int = 3):
    """Calls Gemini, retrying across free models on busy/rate-limit errors and dropped connections."""
    last = None
    for attempt in range(rounds):
        for model in MODELS:
            try:
                return client.models.generate_content(model=model, contents=contents, config=config)
            except errors.APIError as e:
                if e.code not in (429, 500, 502, 503, 504):
                    raise
                last = e
                print(f"    {model} unavailable ({e.code}), trying next model...")
            except (httpx.TransportError, ConnectionError) as e:  # e.g. "Server disconnected without a response"
                last = e
                print(f"    {model} connection dropped ({type(e).__name__}), trying again...")
        if attempt + 1 < rounds:
            time.sleep(20 * (attempt + 1))
    raise last


# Backup writers when every Gemini model fails: free, OpenAI-compatible APIs, tried in this order.
BACKUPS = [
    ("Groq", "https://api.groq.com/openai/v1/chat/completions", GROQ_API_KEY,
     ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]),
    # GitHub Models works inside GitHub Actions with the workflow's own token (permissions: models: read).
    ("GitHub Models", "https://models.github.ai/inference/chat/completions", os.getenv("GITHUB_TOKEN", ""),
     ["openai/gpt-4o-mini"]),
]
LAST_WRITER = "Gemini"  # which service wrote the last script (reported in Telegram when it's a backup)


def _backup_json(url: str, key: str, model: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    system = ("Reply with ONLY a JSON object (no markdown, no commentary) that matches this JSON schema. "
              "Include EVERY required field at every level.\n" + json.dumps(schema.model_json_schema()))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    for attempt in range(4):
        r = requests.post(url, timeout=180, headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "temperature": 0.8, "response_format": {"type": "json_object"},
                                "messages": messages})
        if r.status_code == 429 and attempt < 3:  # per-minute free limit: wait as told, then retry
            wait = min(float(r.headers.get("retry-after", 20) or 20), 60)
            print(f"    {model} rate-limited, waiting {wait:.0f}s...")
            time.sleep(wait)
            continue
        if r.status_code == 400 and "validate json" in r.text.lower() and attempt < 3:  # model emitted broken JSON
            messages = messages[:2] + [{"role": "user", "content": "Your last reply was not valid JSON. Reply with "
                                                                    "one complete, valid JSON object only."}]
            continue
        if not r.ok:
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        text = re.sub(r"^```(?:json)?|```$", "", r.json()["choices"][0]["message"]["content"].strip()).strip()
        try:
            return schema.model_validate_json(text)
        except Exception as e:  # missing/invalid fields: show the model exactly what to fix
            if attempt == 3:
                raise
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"That JSON is incomplete or invalid:\n{str(e)[:1500]}\n"
                                                     "Return the COMPLETE corrected JSON object with every required "
                                                     "field filled in."}]


def _structured(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Asks Gemini for JSON matching `schema`; if every Gemini model fails, falls back to Groq, then
    GitHub Models, so a Gemini outage doesn't stop the daily video."""
    global LAST_WRITER
    try:
        resp = _generate(prompt, types.GenerateContentConfig(response_mime_type="application/json",
                                                             response_schema=schema))
        result = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text or "{}")
        LAST_WRITER = "Gemini"
        return result
    except Exception as gemini_error:
        errors_seen = [f"Gemini: {type(gemini_error).__name__}: {str(gemini_error)[:120]}"]
    for name, url, key, models in BACKUPS:
        if not key:
            continue
        for model in models:
            try:
                print(f"    Gemini failed - writing with {name} ({model})...")
                result = _backup_json(url, key, model, prompt, schema)
                LAST_WRITER = f"{name} ({model})"
                return result
            except Exception as e:
                errors_seen.append(f"{name} {model}: {type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError("All script writers failed: " + " | ".join(errors_seen))


class Scene(BaseModel):
    narration: str = Field(description="What the voiceover says in this scene (1-2 short sentences)")
    visual_queries: list[str] = Field(description=(
        "2-3 stock-footage searches from specific to generic, each 1-2 common words naming something "
        "visible (noun first), e.g. ['octopus', 'coral reef', 'ocean']"))
    image_prompt: str = Field(description=(
        "One-sentence image prompt showing exactly what this scene's narration says: who/what is shown, action, "
        "setting, camera framing. If the main character appears, write 'the character' (their look is defined "
        "separately)."))


class YouTubePost(BaseModel):
    title: str = Field(description="Max 90 chars, curiosity-driven, ends with #Shorts")
    description: str = Field(description="2-3 lines + hashtags on the last line")
    tags: list[str] = Field(description="10-15 search tags, no '#'")


class SocialPost(BaseModel):
    on_screen_title: str = Field(description="Short text-overlay/cover title (max 6 words)")
    caption: str = Field(description="Full post caption, ending with the hashtags (they must appear in this text)")
    hashtags: list[str] = Field(description="The hashtags used, each starting with '#'")

    def full_caption(self) -> str:
        """Caption ready to paste: appends any hashtags the model left out of the caption text."""
        caption = YOUTUBE_ONLY_TAGS.sub("", self.caption)  # #shorts etc. look out of place on TikTok/IG
        caption = re.sub(r"[ \t]{2,}", " ", caption).strip()
        present = {w.lower().rstrip(".,!?") for w in caption.split() if w.startswith("#")}
        tags = [t if t.startswith("#") else f"#{t}" for t in self.hashtags]
        missing = [t for t in tags if t.lower() not in present and not YOUTUBE_ONLY_TAGS.fullmatch(t)]
        return f"{caption}\n\n{' '.join(missing)}" if missing else caption


class VideoPackage(BaseModel):
    topic: str
    character: str = Field(description=(
        "Visual description of the main recurring character (age, hair, face, outfit colors), 1-2 sentences. "
        "For fact videos with no character, describe a friendly narrator character (e.g. a curious kid explorer)."))
    scenes: list[Scene]
    youtube: YouTubePost
    tiktok: SocialPost
    instagram: SocialPost
    best_posting_times: str = Field(description="Recommended posting windows per platform, with timezone")
    trend_notes: str = Field(description="Trending sounds/formats/hashtags worth using and why; flag anything unverified")


def research_trends(niche: str, topic: str | None) -> str:
    """Ask Gemini to search Google for what's trending now. Returns "" if search grounding isn't available."""
    focus = f'the topic "{topic}"' if topic else "a strong video topic"
    prompt = (
        f"Today is {date.today().isoformat()}. I make faceless short-form videos in the niche: {niche}.\n"
        f"Search the web for what is trending RIGHT NOW to help me pick {focus} and write post copy.\n\n"
        "Report concisely:\n"
        "1. Trending/high-performing hashtags for this niche on TikTok, Instagram Reels and YouTube Shorts "
        "(separate lists; note which are broad vs niche).\n"
        "2. Current trending sounds or formats relevant to this niche, if any.\n"
        "3. Current platform rules that affect captions (hashtag limits, caption length, AI-content labels).\n"
        "4. If no topic was given: 5 topic ideas currently getting attention in this niche.\n"
        "Only report what your searches support; say when something is unverified."
    )
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )  # no fallback loop: search quota is all-or-nothing per account
        return (resp.text or "").strip()
    except Exception as e:  # free-tier quota or grounding not enabled: carry on without it
        print(f"    Web search research unavailable ({type(e).__name__}: {str(e)[:120]}) - continuing without it.")
        return ""


STYLE_RULES = {
    "facts": """- 5-8 scenes, about {words} words of narration total.
- Scene 1 is the hook and must stop the scroll within 2 seconds (hook type for this video is given below).
- One fact per scene, building to the most surprising one last.
- Facts must be accurate and widely verifiable; skip anything you are unsure of.
- {ending}""",
    "story": """- 6-9 scenes, about {words} words of narration total, told as one short story.
- Scene 1 is the hook and must pull the viewer in within 2 seconds (hook type for this video is given below).
- Structure: setup -> struggle -> turning point -> lesson. Keep the lesson to one sentence at the end.
- Warm, simple, emotional language; no cliches like "little did they know".
- If it's about a real person or event, every detail must be true and well documented. Never invent dramatic
  moments, weather, dangers or dialogue for effect; the true events are the story.
  If it's a parable or fictional, the narration must make that clear within the first two scenes, in natural,
  varied wording (e.g. "Legend says...", "As the parable goes...", "In a village somewhere, the tale says..."),
  and topic must start with "Parable:". Never present an invented story as true.
- {ending}""",
    "ad": """- 5-7 scenes, about {words} words of narration total: a short ad for the product in the brief below.
- Structure: hook (a relatable money problem) -> the frustration -> the product as the simple fix,
  showing 1-2 specific features from the brief -> a payoff line. The spoken call to action (website) is added
  automatically after your last scene, so don't say the website or "link in bio" yourself.
- Pick ONE angle for this ad (a specific audience + problem + feature) and put it in `topic`, e.g.
  "Ad: roommates arguing over who paid the electric bill -> shared workspace".
- Only claim what the brief lists as available. Never invent statistics, reviews, user counts, or prices.
  Mention it's free to start. Never mention features the brief lists as not available yet.
- Talk to the viewer ("you"), conversational, like a friend recommending it - not a TV announcer.""",
}
# How the script must end; the matching call to action is added afterwards in code.
ENDING_RULES = {
    "facts": {
        "question": "The final scene is a short, specific question to the viewer about the facts (it must end with "
                    "'?'). Don't mention comments - that's added automatically.",
        "statement": "The final scene is a short, punchy payoff line (a statement, NOT a question). A follow-for-more "
                     "call to action is added after it automatically.",
    },
    "story": {
        "question": "End with the lesson in one sentence, then a final short question that asks viewers how it "
                    "applies to their life (it must end with '?'). Don't mention comments - that's added automatically.",
        "statement": "The final scene is the lesson itself, stated as a strong, memorable line - NOT a question. "
                     "A follow-for-more call to action is added after it automatically.",
    },
}
WORDS_PER_SECOND = {"facts": 2.6, "story": 2.3, "ad": 2.5}


HOOKS = {
    "facts": [
        "a bold claim that sounds impossible but is true",
        "a direct question to the viewer about something they think they know",
        "a 'stop doing X' or 'you've been doing X wrong' line",
        "a striking number or comparison",
        "a challenge: 'bet you didn't know this one'",
        "start mid-fact, with no intro - the most surprising detail first",
        "a 'what would happen if...' scenario",
        "a myth the viewer believes, then 'that's wrong'",
    ],
    "story": [
        "drop the viewer into the most tense moment, then rewind",
        "open with a line of dialogue",
        "open with the ending or the twist, then explain how it happened",
        "a vivid sensory detail of one small moment",
        "a question the main character faced",
        "a surprising fact about a real person before their story",
        "a short, striking statement about life that the story will prove",
        "a time-and-place opener: a specific year, place, and person",
    ],
    "ad": [
        "a relatable 'POV:' moment (e.g. 'POV: it's rent day and nobody remembers who paid last month')",
        "a direct question about a money problem the viewer has",
        "a short, overheard-style line of dialogue in an argument about money",
        "a 'stop doing X' line about tracking money in group chats or notebooks",
        "a surprising, everyday money moment the viewer recognizes",
        "a 'here's how we finally stopped fighting about money' opener",
    ],
}


FORMATS = {"facts": "fun facts", "story": "short inspiring story", "ad": "short product ad"}
# `--niche auto` picks one of these at random for each video (niche -> extra writing rules).
TOPIC_MIX = {
    "facts": {
        "fun facts": "",
        "feel-good science": (
            "Feel-good science: real, well-established research on how kindness, gratitude, nature, friendship, "
            "laughter, music, sleep or helping others lifts people's mood and wellbeing. Say 'studies suggest' or "
            "'researchers found' instead of overclaiming. Keep to mood, stress, focus and social connection: no "
            "claims about pain, immunity, disease, lifespan or other physical health, and no medical advice, "
            "diagnoses, cures or supplements."),
    },
    "story": {
        "short inspiring stories": "",
        "kind animals": (
            "Kind animals: a true, well-documented story or behavior of animals showing kindness, loyalty, care or "
            "cooperation, toward each other or toward people (e.g. elephants comforting a grieving herd member). "
            "The animal is the main character. Every detail must be documented; never invent events. "
            "Prefer animals helping each other or adults: skip stories about injured or endangered children. "
            "It's not a parable, so the topic must not start with 'Parable:'."),
        "kindness traditions around the world": (
            "Kindness traditions around the world: one real tradition of kindness from a specific culture, told as a "
            "short story of how it works and why it matters (e.g. Filipino bayanihan, neighbors carrying a house "
            "together; Italy's caffe sospeso, a coffee paid ahead for a stranger). About one time in three, pick a "
            "tradition from the Philippines. Clothes, places and customs must be accurate; no stereotypes. "
            "It's not a parable, so the topic must not start with 'Parable:'."),
    },
}
PRIVACY_CHANCE = 0.4  # share of ads that include the brief's privacy reassurance
# Words per second relative to the Microsoft voice; set to ~1.3 by the CLI when the faster Inworld voice
# (Clive/Dennis) will be used, so videos come out near the target length for the actual voice.
VOICE_PACE = 1.0


_CTA_SENTENCE = re.compile(r"[^.!?]*\b(follow|subscribe|like and share|hit the bell|in the comments)\b[^.!?]*[.!?]\s*$",
                           re.IGNORECASE)


def fix_narration(scenes: list, character: str) -> None:
    """Safety net: "the character" is image-prompt wording and must never be spoken."""
    female = re.search(r"\b(woman|girl|female|she|her|lady|grandmother|mother)\b", character, re.IGNORECASE)
    pronoun = "she" if female else "he"
    for scene in scenes:
        scene.narration = re.sub(r"\bThe character\b", pronoun.capitalize(), scene.narration)
        scene.narration = re.sub(r"\bthe character\b", pronoun, scene.narration, flags=re.IGNORECASE)


def strip_cta(text: str) -> str:
    """Removes a trailing follow/subscribe/comments sentence the model added on its own."""
    stripped = _CTA_SENTENCE.sub("", text).strip()
    return stripped or text


class RepeatCheck(BaseModel):
    repeat_of: str = Field(description="The past topic it repeats, copied exactly from the list; empty if it's new")


def find_repeat(pkg: VideoPackage, style: str, past: list[str]) -> str:
    """Returns the past topic this video retells (same story, person, event or parable, or the same facts subject),
    even under a reworded title; "" if it's new. Raises if no writer is available."""
    if not past:
        return ""
    same = ("the same story, person, event or parable (a retelling with different details or a new title still "
            "counts, e.g. two videos about the doctor paid with a glass of milk)" if style == "story" else
            "mostly the same subject (e.g. two videos about deep ocean trenches)")
    story = " ".join(s.narration for s in pkg.scenes[:3])
    prompt = (f'New video topic: "{pkg.topic}"\nOpening: "{story}"\n\nPast videos:\n'
              + "\n".join(f"- {t}" for t in past)
              + f"\n\nDoes the new video tell {same} as one of the past videos? Judge by what it's about, not the "
                "wording. If yes, give that past topic exactly as written; if no, leave repeat_of empty.")
    global LAST_WRITER
    writer = LAST_WRITER  # keep reporting who wrote the script, not who did this check
    try:
        found = _structured(prompt, RepeatCheck).repeat_of.strip()
    finally:
        LAST_WRITER = writer
    return found if found in past else next((t for t in past if found and found.lower() in t.lower()), "")


def write_package(niche: str, topic: str | None, research: str, target_seconds: int, style: str = "facts",
                  avoid: list[str] = (), avoid_hooks: list[str] = (), brief: str = "",
                  website: str = "", ending: str = "statement", not_again: list[str] = ()) -> VideoPackage:
    """ending: "question" (last line asks viewers something) or "statement" (last line is the lesson/payoff)."""
    hook = random.choice(HOOKS[style])
    recent = "\n".join(f"  - {h}" for h in avoid_hooks)
    # Inworld's Clive/Dennis speak noticeably faster than the Microsoft voice, so ask for more words.
    words = int(target_seconds * WORDS_PER_SECOND[style] * VOICE_PACE)
    product = f"""
Product brief (the only source of truth for claims):
<brief>
{brief}
</brief>
""" if brief else ""
    privacy = ("- Include the privacy message from the brief as one short scene near the end, before the payoff.\n"
               if style == "ad" and random.random() < PRIVACY_CHANCE else "")
    ad_copy = f"""{privacy}- Follow the brief's Target audience section (situations, currency, hashtags).
- This is an ad for the product's own channel: in every caption and description, say it's free to start.
- YouTube description: first line must include {website}.
- TikTok/Instagram captions can't have clickable links: end the caption text with "Link in bio" and
  mention the site name ({website}) once.
""" if style == "ad" else ""
    prompt = f"""Write a faceless short-form video (vertical, ~{target_seconds}s) for the niche: {niche}.
Format: {FORMATS[style]}
{TOPIC_MIX.get(style, {}).get(niche, "")}
Topic: {topic or ("pick a fresh angle from the brief" if style == "ad" else "pick the best topic from the research below")}
{"Already covered - pick a clearly different " + ("angle (different audience or problem or feature)" if style == "ad" else "topic (different subject, not just a reworded title)") + ": " + "; ".join(avoid) if avoid and not topic else ""}
{"IMPORTANT: your previous draft retold a video we already posted. Do NOT write about any of these or anything close to them (same story, person or subject, even with a new title): " + "; ".join(not_again) if not_again else ""}
{product}
Trend research (collected today):
<research>
{research or "No research available - rely on evergreen best practices and say so in trend_notes."}
</research>

Script rules:
{STYLE_RULES[style].format(words=words, ending=ENDING_RULES.get(style, {}).get(ending, ''))}
- Hook type for this video: {hook}.
- Never open with "Did you know", "There's an old story", "Have you ever", "Imagine", or "Think again".
{"- Recent openings - don't reuse their wording or sentence pattern:" + chr(10) + recent if recent else ""}
- Plain spoken English, short sentences, no emojis, no stage directions, no "in this video".
- In `narration`, refer to people naturally by name or as he/she. The words "the character" are ONLY for
  image_prompt and must never appear in narration, titles or captions.
- Never add calls to action yourself (follow, subscribe, like, share, comment) - they are added automatically.
- image_prompt: the exact moment this scene's narration describes, so a viewer could guess the line from the
  picture: the same subject, action, emotion, quantity and setting (many rabbits chasing a man, not one rabbit;
  a valley flooded with glowing lava, not a lake). Name every visible object and person. Vary framing across
  scenes: close-up, medium, wide. The art style is added automatically - don't mention style. Never ask
  for signs, labels, writing or anything with lettering, because image models garble text. Name the country or
  region in the prompt whenever the story has one, so buildings and clothes fit. Whenever the main character appears, write exactly "the character" (never a name or a
  description; their look is supplied separately). Describe anyone else in full each time. For fun facts,
  show the fact's real subject; only use the character when the line is about a person.
  Show the line's main EVENT and its emotional meaning, not just its setting or background. When a line has
  several ideas, draw the human moment that matters: for "famine forced him to drop out of school", show the sad
  boy looking back at his school from outside while classmates in uniform go in, with dry fields around, not
  just dry land. Use concrete visual clues (school, uniform, books, classmates) to make the event obvious.
  Keep every picture believable: realistic scale and physics (a small spark stays small, never lightning, unless
  the narration really says so), calm natural poses with hands clearly holding things, and accurate period,
  place and objects (a scrap-built windmill in a Malawian village, not a Dutch one). Avoid dangerous stunts.
- visual_queries: simple, literal words a stock site (Pixabay/Pexels) would tag - objects, animals, places,
  people doing common actions. No abstract ideas ("hope", "mistake") and no names.
  The FIRST query must name the scene's key visual exactly as described in the narration, keeping the
  substance and quantity (e.g. "lava flow" for lava - never "lake"; "rabbits running" for many rabbits;
  "volcano eruption", "crowd cheering"). Later queries can be broader but must still fit the line.

Post copy rules:
- Use hashtags from the research where they genuinely fit; mix broad + niche tags.
- Respect current platform hashtag limits found in the research (Instagram allows at most 5 per post).
- Never use YouTube-only tags (#shorts, #youtubeshorts) on TikTok or Instagram.
- TikTok: punchy caption under 150 chars before hashtags, 3-5 hashtags.
- Instagram: 1-3 line caption with a call to action (save/share/comment), then hashtags.
- YouTube: title must end with #Shorts; description ends with 3-5 hashtags.
{ad_copy}"""
    pkg = _structured(prompt, VideoPackage)
    fix_narration(pkg.scenes, pkg.character)
    return pkg


class ExtraScenes(BaseModel):
    scenes: list[Scene]


EXTEND_RULES = {
    "facts": "Add {n} more fact scene(s) on the same topic, each a new, accurate, surprising fact that isn't "
             "already in the script. They are inserted just before the final scene.",
    "story": "Add {n} more scene(s) that deepen the middle of the story (more of the struggle, a vivid detail, "
             "or a setback before the turning point). They are inserted just before the last two scenes, so "
             "the turning point and the lesson stay at the end. Keep the same characters, tone and facts.",
    "ad": "Add {n} more scene(s) that show one more real feature from the brief solving the same problem. "
          "They are inserted just before the final scene.",
}


def extend_package(pkg: VideoPackage, style: str, missing_seconds: float) -> tuple[int, list[Scene]]:
    """Writes extra scenes when the video came out too short. Returns (insert index, new scenes)."""
    n = max(1, min(3, round(missing_seconds / 6)))
    words = int(missing_seconds * WORDS_PER_SECOND[style] * VOICE_PACE) + 5
    script = "\n".join(f"{i + 1}. {s.narration}" for i, s in enumerate(pkg.scenes))
    prompt = f"""This short video script is about {missing_seconds:.0f} seconds too short.
Topic: {pkg.topic}
Current script (one line per scene):
{script}

{EXTEND_RULES[style].format(n=n)}
Return ONLY the {n} new scene(s) - do not repeat or include any existing scene.
Write about {words} words of narration in total across the new scenes, in the same voice and style:
plain spoken English, short sentences, no emojis, no stage directions. Each new scene needs narration,
visual_queries (simple literal stock-footage words) and image_prompt, like the existing scenes."""
    extra = _structured(prompt, ExtraScenes)
    fix_narration(extra.scenes, pkg.character)
    # The model sometimes echoes the whole script back: keep only genuinely new scenes, at most n.
    def norm(t: str) -> str:
        return re.sub(r"\W+", " ", t).strip().lower()
    existing = {norm(s.narration) for s in pkg.scenes}
    new, seen = [], set()
    for s in extra.scenes:
        k = norm(s.narration)
        if k and k not in existing and k not in seen:
            seen.add(k)
            new.append(s)
    at = max(1, len(pkg.scenes) - (2 if style == "story" else 1))
    return at, new[:n]


class ClipPick(BaseModel):
    best: int = Field(description="Number of the image that best shows the narration (1-based), or 0 if none fit")
    score: int = Field(description="How literally that image matches the narration, 0-10")
    reason: str = Field(description="One short sentence")


def pick_clip(narration: str, images: list[bytes]) -> tuple[int | None, int]:
    """Shows Gemini the candidates' preview images and returns (0-based index of the best, score),
    or (None, score) when nothing plausibly matches."""
    parts = [types.Part.from_text(text=(
        f'A short video narrator says: "{narration}"\n\n'
        f"Below are {len(images)} preview images of stock video clips, numbered 1 to {len(images)} in order. "
        "Pick the one that most literally shows what is being said: the same subject, the same action, "
        "the same quantity (one rabbit vs many rabbits) and the same substance (lava vs water, fire vs light). "
        "Prefer a literal match over a pretty but unrelated shot. If none of them could reasonably accompany "
        "this line, answer best = 0."))]
    for i, img in enumerate(images, 1):
        parts += [types.Part.from_text(text=f"Image {i}:"), types.Part.from_bytes(data=img, mime_type="image/jpeg")]
    # One quick pass over the models, no waiting: if Gemini is busy, the caller falls back to tag matching.
    resp = _generate(parts, types.GenerateContentConfig(response_mime_type="application/json",
                                                        response_schema=ClipPick), rounds=1)
    pick = resp.parsed if isinstance(resp.parsed, ClipPick) else ClipPick.model_validate_json(resp.text or "{}")
    if pick.best < 1 or pick.best > len(images) or pick.score <= 1:
        return None, pick.score
    return pick.best - 1, pick.score


class ImageCheck(BaseModel):
    matches_line: int = Field(description="0-10: does the picture show what the narrator says?")
    believable: int = Field(description="0-10: physically plausible, realistic scale, no exaggerated effects?")
    anatomy: int = Field(description="0-10: are bodies, arms, hands and faces drawn correctly?")
    problem: str = Field(description="The single most important thing to fix, as a drawing instruction; empty if none")


def check_image(narration: str, image: bytes, plan: str = "") -> ImageCheck:
    """Reviews a generated scene image against its narration line (one quick pass; raises if Gemini is busy)."""
    parts = [types.Part.from_text(text=(
        f'This image illustrates a short video where the narrator says: "{narration}"\n'
        f'The planned picture was: "{plan}"\n'
        "Anything the plan asks for must be clearly visible; a key element that's missing (such as the school in a "
        "line about leaving school) scores 5 or less. In `problem`, keep to the plan: say what to add or correct, "
        "never suggest a different idea. Any visible lettering or sign scores believable 4 or less (tell it to "
        "remove the text). Buildings, clothes and objects that don't fit the story's country or period score "
        "believable 6 or less.\n"
        "Review it strictly. The art style itself is fine. Score how well it shows that line (subject, action, "
        "quantity, place, period); a picture that shows only the setting and misses the line's main event scores 4 "
        "or less; whether it's believable (realistic scale, physics and objects; no exaggerated "
        "effects like huge lightning from a small device); and its anatomy (extra, missing or twisted arms, hands "
        "or fingers, limbs bending wrongly, distorted faces).")),
        types.Part.from_bytes(data=image, mime_type="image/jpeg")]
    resp = _generate(parts, types.GenerateContentConfig(response_mime_type="application/json",
                                                        response_schema=ImageCheck), rounds=1)
    return resp.parsed if isinstance(resp.parsed, ImageCheck) else ImageCheck.model_validate_json(resp.text or "{}")
