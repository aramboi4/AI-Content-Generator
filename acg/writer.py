"""Gemini (free tier) calls: live trend research, then the script + per-platform post copy."""
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
    visual_query: str = Field(description="2-4 word stock-footage search, concrete and visual, e.g. 'octopus swimming reef'")


class YouTubePost(BaseModel):
    title: str = Field(description="Max 90 chars, curiosity-driven, ends with #Shorts")
    description: str = Field(description="2-3 lines + hashtags on the last line")
    tags: list[str] = Field(description="10-15 search tags, no '#'")


class SocialPost(BaseModel):
    on_screen_title: str = Field(description="Short text-overlay/cover title (max 6 words)")
    caption: str = Field(description="Full post caption including hashtags at the end")
    hashtags: list[str] = Field(description="The hashtags used, each starting with '#'")


class VideoPackage(BaseModel):
    topic: str
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
- Scene 1 is the hook: a surprising claim or question that stops the scroll within 2 seconds.
- One fact per scene, building to the most surprising one last.
- Facts must be accurate and widely verifiable; skip anything you are unsure of.
- End with a short payoff or a question that invites comments.""",
    "story": """- 6-9 scenes, about {words} words of narration total, told as one short story.
- Scene 1 is the hook: drop the viewer into a moment of tension or a striking line.
- Structure: setup -> struggle -> turning point -> lesson. Keep the lesson to one sentence at the end.
- Warm, simple, emotional language; no cliches like "little did they know".
- If it's about a real person or event, every detail must be true and well documented.
  If it's a parable or fictional, the narration must make that clear (e.g. "There's an old story...")
  and topic must start with "Parable:". Never present an invented story as true.
- End with the lesson, then a short question that invites comments.""",
}
WORDS_PER_SECOND = {"facts": 2.6, "story": 2.3}


def write_package(niche: str, topic: str | None, research: str, target_seconds: int, style: str = "facts") -> VideoPackage:
    words = int(target_seconds * WORDS_PER_SECOND[style])
    prompt = f"""Write a faceless short-form video (vertical, ~{target_seconds}s) for the niche: {niche}.
Format: {"fun facts" if style == "facts" else "short inspiring story"}
Topic: {topic or "pick the best topic from the research below"}

Trend research (collected today):
<research>
{research or "No research available - rely on evergreen best practices and say so in trend_notes."}
</research>

Script rules:
{STYLE_RULES[style].format(words=words)}
- Plain spoken English, short sentences, no emojis, no stage directions, no "in this video".
- visual_query must describe footage that likely exists on a stock site (Pixabay/Pexels).

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
