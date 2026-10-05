"""Prompt template rendering + rewriting."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations import llm
from app.models import PromptTemplate

VARIABLES = ["{title}", "{caption}", "{tags}", "{source}", "{niche}"]
ALIASES = {"original_title": "title", "original_caption": "caption", "original_tags": "tags"}
VAR_RE = re.compile(r"\{(\w+)\}")

DEFAULT_TEMPLATE = {
    "name": "Default rewrite",
    "description": "Rewrite any short-form video for TikTok discovery",
    "title_prompt": "Write a short, punchy TikTok title (max 80 characters) for a video originally titled:\n{title}\n\nOriginal caption for context:\n{caption}",
    "caption_prompt": "Rewrite this caption into a concise, engaging TikTok caption. Lead with a strong hook, keep it authentic, avoid clickbait, and do not include hashtags. Maximum 160 characters.\n\nOriginal caption:\n{caption}",
    "hashtags_prompt": "Suggest 4-6 relevant TikTok hashtags for this video. Return them space-separated, each starting with #.\n\nCaption: {caption}\nOriginal tags: {tags}",
}


def render(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        name = ALIASES.get(match.group(1), match.group(1))
        return values.get(name, match.group(0))

    return VAR_RE.sub(repl, template)


def parse_hashtags(text: str) -> list[str]:
    tags = re.findall(r"#?([\wऀ-ॿ؀-ۿ]+)", text or "")
    return list(dict.fromkeys(t.lower() for t in tags if t))[:10]


def resolve_template(db: Session, template_id: int | None) -> PromptTemplate | None:
    if template_id:
        template = db.get(PromptTemplate, template_id)
        if template and template.is_enabled:
            return template
    return db.scalar(select(PromptTemplate).where(PromptTemplate.is_default.is_(True), PromptTemplate.is_enabled.is_(True)))


def rewrite(
    *, title_prompt: str, caption_prompt: str, hashtags_prompt: str, title: str, caption: str, tags: list[str],
    source: str = "", niche: str = "",
) -> dict:
    """Run each non-empty template field through the LLM. Empty fields keep the original value."""
    values = {"title": title, "caption": caption, "tags": " ".join(f"#{t}" for t in tags), "source": source, "niche": niche}
    result = {"title": title, "caption": caption, "tags": list(tags)}
    if title_prompt.strip():
        result["title"] = llm.complete(render(title_prompt, values)).strip().strip('"')[:150]
    if caption_prompt.strip():
        result["caption"] = llm.complete(render(caption_prompt, values)).strip().strip('"')
    if hashtags_prompt.strip():
        result["tags"] = parse_hashtags(llm.complete(render(hashtags_prompt, values)))
    return result
