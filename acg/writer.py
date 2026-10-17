"""Gemini (free tier) calls: live trend research, then the script + per-platform post copy."""
import random
import re
import time
from datetime import date

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from .config import GEMINI_API_KEY, INWORLD_API_KEY, MODEL

client = genai.Client(api_key=GEMINI_API_KEY)
YOUTUBE_ONLY_TAGS = re.compile(r"#(?:youtube)?shorts?(?:feed|video)?\b", re.IGNORECASE)

# Free-tier models get busy (503) or rate limited (429); fall back through these.
MODELS = list(dict.fromkeys([MODEL, "gemini-3.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]))


def _generate(contents: str, config: types.GenerateContentConfig | None = None):
    last = None
    for attempt in range(2):
        for model in MODELS:
            try:
                return client.models.generate_content(model=model, contents=contents, config=config)
            except errors.APIError as e:
                if e.code not in (429, 500, 503, 504):
                    raise
                last = e
                print(f"    {model} unavailable ({e.code}), trying next model...")
        time.sleep(20)
    raise last


class Scene(BaseModel):
    narration: str = Field(description="What the voiceover says in this scene (1-2 short sentences)")
    visual_queries: list[str] = Field(description=(
        "2-3 stock-footage searches from specific to generic, each 1-2 common words naming something "
        "visible (noun first), e.g. ['octopus', 'coral reef', 'ocean']"))
    image_prompt: str = Field(description=(
        "One-sentence image prompt for this scene: who/what is shown, action, setting, camera framing. "
        "If the main character appears, refer to them as 'the character' (their look is defined separately)."))


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
- End with a short payoff or a question that invites comments.""",
    "story": """- 6-9 scenes, about {words} words of narration total, told as one short story.
- Scene 1 is the hook and must pull the viewer in within 2 seconds (hook type for this video is given below).
- Structure: setup -> struggle -> turning point -> lesson. Keep the lesson to one sentence at the end.
- Warm, simple, emotional language; no cliches like "little did they know".
- If it's about a real person or event, every detail must be true and well documented.
  If it's a parable or fictional, the narration must make that clear within the first two scenes, in natural,
  varied wording (e.g. "Legend says...", "As the parable goes...", "In a village somewhere, the tale says..."),
  and topic must start with "Parable:". Never present an invented story as true.
- The final scene is the lesson itself, stated as a strong, memorable line. Do NOT end with a question
  (a follow-for-more call to action is added after it automatically).""",
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
PRIVACY_CHANCE = 0.4  # share of ads that include the brief's privacy reassurance


def write_package(niche: str, topic: str | None, research: str, target_seconds: int, style: str = "facts",
                  avoid: list[str] = (), avoid_hooks: list[str] = (), brief: str = "",
                  website: str = "") -> VideoPackage:
    hook = random.choice(HOOKS[style])
    recent = "\n".join(f"  - {h}" for h in avoid_hooks)
    # Inworld's Clive/Dennis speak noticeably faster than the Microsoft voice, so ask for more words.
    words = int(target_seconds * WORDS_PER_SECOND[style] * (1.3 if INWORLD_API_KEY else 1.0))
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
Topic: {topic or ("pick a fresh angle from the brief" if style == "ad" else "pick the best topic from the research below")}
{"Already covered - pick a clearly different " + ("angle (different audience or problem or feature)" if style == "ad" else "topic (different subject, not just a reworded title)") + ": " + "; ".join(avoid) if avoid and not topic else ""}
{product}
Trend research (collected today):
<research>
{research or "No research available - rely on evergreen best practices and say so in trend_notes."}
</research>

Script rules:
{STYLE_RULES[style].format(words=words)}
- Hook type for this video: {hook}.
- Never open with "Did you know", "There's an old story", "Have you ever", "Imagine", or "Think again".
{"- Recent openings - don't reuse their wording or sentence pattern:" + chr(10) + recent if recent else ""}
- Plain spoken English, short sentences, no emojis, no stage directions, no "in this video".
- image_prompt: a vivid, concrete, single moment that illustrates the narration (3D cartoon look is added
  automatically - don't mention style). Vary framing across scenes: close-up, medium, wide.
- visual_queries: simple, literal words a stock site (Pixabay/Pexels) would tag - objects, animals, places,
  people doing common actions. No abstract ideas ("hope", "mistake") and no names.

Post copy rules:
- Use hashtags from the research where they genuinely fit; mix broad + niche tags.
- Respect current platform hashtag limits found in the research (Instagram allows at most 5 per post).
- Never use YouTube-only tags (#shorts, #youtubeshorts) on TikTok or Instagram.
- TikTok: punchy caption under 150 chars before hashtags, 3-5 hashtags.
- Instagram: 1-3 line caption with a call to action (save/share/comment), then hashtags.
- YouTube: title must end with #Shorts; description ends with 3-5 hashtags.
{ad_copy}"""
    resp = _generate(
        prompt, types.GenerateContentConfig(response_mime_type="application/json", response_schema=VideoPackage)
    )
    pkg = resp.parsed if isinstance(resp.parsed, VideoPackage) else None
    if pkg is None:
        pkg = VideoPackage.model_validate_json(resp.text or "{}")
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
    words = int(missing_seconds * WORDS_PER_SECOND[style] * (1.3 if INWORLD_API_KEY else 1.0)) + 5
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
    resp = _generate(prompt, types.GenerateContentConfig(response_mime_type="application/json",
                                                         response_schema=ExtraScenes))
    extra = resp.parsed if isinstance(resp.parsed, ExtraScenes) else ExtraScenes.model_validate_json(resp.text or "{}")
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
