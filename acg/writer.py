"""Claude calls: live trend research, then the script + per-platform post copy."""
from datetime import date

import anthropic
from pydantic import BaseModel, Field

from .config import MODEL

# Server-side fallback: if the main model declines, the API retries on a
# suitable model inside the same call instead of failing the run.
BETAS = ["server-side-fallback-2026-07-01"]
FALLBACKS = "default"

client = anthropic.Anthropic()


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


def _final_text(resp) -> str:
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()


def research_trends(niche: str, topic: str | None) -> str:
    """Use Claude's web search to collect what is trending right now for this niche."""
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
    messages = [{"role": "user", "content": prompt}]
    for _ in range(4):  # server tools can pause long turns; resume up to a few times
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=BETAS,
            fallbacks=FALLBACKS,
            output_config={"effort": "medium"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}],
            messages=messages,
        )
        if resp.stop_reason != "pause_turn":
            break
        messages = [*messages, {"role": "assistant", "content": resp.content}]
    if resp.stop_reason == "refusal":
        raise RuntimeError("Trend research was declined by the model.")
    return _final_text(resp)


def write_package(niche: str, topic: str | None, research: str, target_seconds: int) -> VideoPackage:
    words = int(target_seconds * 2.6)  # ~2.6 spoken words per second
    prompt = f"""Write a faceless short-form video (vertical, ~{target_seconds}s) for the niche: {niche}.
Topic: {topic or "pick the best topic from the research below"}

Trend research (live, from today):
<research>
{research or "No research available - rely on evergreen best practices and say so in trend_notes."}
</research>

Script rules:
- 5-8 scenes, about {words} words of narration total.
- Scene 1 is the hook: a surprising claim or question that stops the scroll within 2 seconds.
- Plain spoken English, short sentences, no emojis, no stage directions, no "in this video".
- Facts must be accurate; avoid claims you are unsure of.
- End with a short payoff or a question that invites comments.
- visual_query must describe footage that likely exists on a stock site (Pexels).

Post copy rules:
- Use trending hashtags from the research where they genuinely fit; mix broad + niche tags.
- Respect current platform hashtag limits found in the research (Instagram allows at most 5 per post).
- TikTok: punchy caption under 150 chars before hashtags, 3-5 hashtags.
- Instagram: 1-3 line caption with a call to action (save/share/comment), then hashtags.
- YouTube: title must end with #Shorts; description ends with 3-5 hashtags.
"""
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=BETAS,
        fallbacks=FALLBACKS,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": prompt}],
        output_format=VideoPackage,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"Script generation failed (stop_reason={resp.stop_reason}).")
    return resp.parsed_output
