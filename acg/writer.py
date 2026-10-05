"""Gemini (free tier) calls: live trend research, then the script + per-platform post copy."""
import random
import time
from datetime import date

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from .config import GEMINI_API_KEY, MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

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
        present = {w.lower().rstrip(".,!?") for w in self.caption.split() if w.startswith("#")}
        tags = [t if t.startswith("#") else f"#{t}" for t in self.hashtags]
        missing = [t for t in tags if t.lower() not in present]
        return f"{self.caption.rstrip()}\n\n{' '.join(missing)}" if missing else self.caption


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
- End with the lesson, then a short question that invites comments.""",
}
WORDS_PER_SECOND = {"facts": 2.6, "story": 2.3}


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
}


def write_package(niche: str, topic: str | None, research: str, target_seconds: int, style: str = "facts",
                  avoid: list[str] = (), avoid_hooks: list[str] = ()) -> VideoPackage:
    hook = random.choice(HOOKS[style])
    recent = "\n".join(f"  - {h}" for h in avoid_hooks)
    words = int(target_seconds * WORDS_PER_SECOND[style])
    prompt = f"""Write a faceless short-form video (vertical, ~{target_seconds}s) for the niche: {niche}.
Format: {"fun facts" if style == "facts" else "short inspiring story"}
Topic: {topic or "pick the best topic from the research below"}
{"Already covered - pick a clearly different topic (different subject, not just a reworded title): " + "; ".join(avoid) if avoid and not topic else ""}

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
- TikTok: punchy caption under 150 chars before hashtags, 3-5 hashtags.
- Instagram: 1-3 line caption with a call to action (save/share/comment), then hashtags.
- YouTube: title must end with #Shorts; description ends with 3-5 hashtags.
"""
    resp = _generate(
        prompt, types.GenerateContentConfig(response_mime_type="application/json", response_schema=VideoPackage)
    )
    pkg = resp.parsed if isinstance(resp.parsed, VideoPackage) else None
    if pkg is None:
        pkg = VideoPackage.model_validate_json(resp.text or "{}")
    return pkg
