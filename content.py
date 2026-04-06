"""
content.py — Claude API integration for JinYi Telegram Bot
Handles: weekly digest, draft generation, voice-note transcription,
         revision loop, and image prompt generation.
"""

import anthropic
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are the content writer for JinYi Group, a premium swiftlet farming
company based in Sabah and Sarawak, Malaysian Borneo. You write bilingual (English +
Simplified Chinese) social media posts for Telegram, Facebook, and Instagram.

Brand voice:
- Professional, trustworthy, premium
- Warm but not overly casual
- Educational tone — teach the audience about bird's nest and swiftlet farming
- Never use excessive exclamation marks or hype language
- Always bilingual: English paragraph first, then a divider (———), then Chinese

Format rules:
- Start with a relevant emoji
- Hashtags at the end of each language block
- English: 80–120 words max
- Chinese: equivalent length
- Always end with #JinYiGroup / #锦益集团
"""


def generate_weekly_digest() -> str:
    """Generate a weekly industry digest post (Tier 1 — Friday)."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Write a 'Weekly Industry Digest' post summarising key trends or news "
                    "in the bird's nest / swiftlet farming industry this week. "
                    "Make it informative and useful for investors and enthusiasts. "
                    "300–400 words total (EN + ZH combined). "
                    "Note: base it on general industry knowledge — you cannot browse the web, "
                    "so write about evergreen industry insights framed as a weekly reflection."
                ),
            }
        ],
    )
    return response.content[0].text


def generate_tier2_draft(brief: str, history: list[dict] | None = None) -> str:
    """
    Generate a Tier 2 proactive draft post.
    brief: topic or idea string from scheduler or /draft command
    history: list of prior messages for revision context (last 10)
    """
    messages = history or []
    messages.append(
        {
            "role": "user",
            "content": (
                f"Write a social media post for JinYi Group about: {brief}\n\n"
                "Format: bilingual EN + ZH, with relevant emoji and hashtags. "
                "Length: 80–120 words English, equivalent Chinese."
            ),
        }
    )
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


def revise_draft(original_draft: str, feedback: str, history: list[dict]) -> str:
    """
    Revise a draft based on owner feedback.
    history: the conversation so far (for context)
    """
    messages = history.copy()
    messages.append(
        {
            "role": "user",
            "content": (
                f"Please revise the previous draft based on this feedback: {feedback}\n\n"
                "Keep the bilingual format (EN + ZH) and maintain brand voice."
            ),
        }
    )
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


def draft_from_voice_transcript(transcript: str) -> str:
    """Turn an owner voice note transcript into a polished bilingual post (Tier 3)."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"The owner recorded this voice note: \"{transcript}\"\n\n"
                    "Turn it into a polished bilingual social media post for JinYi Group. "
                    "Preserve the owner's intent and personal tone while lifting it to brand standards."
                ),
            }
        ],
    )
    return response.content[0].text


def draft_from_photo_caption(caption: str) -> str:
    """Turn an owner photo caption into a bilingual post (Tier 3)."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"The owner shared a photo with this caption: \"{caption}\"\n\n"
                    "Write a full bilingual post to accompany the photo. "
                    "Make it engaging and suitable for Telegram, Facebook, and Instagram."
                ),
            }
        ],
    )
    return response.content[0].text


def generate_image_prompt(post_text: str) -> str:
    """Generate a Genspark/image-generation prompt for a given post."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": (
                    "Given this social media post, write a concise image generation prompt "
                    "suitable for Genspark or NanoBanana. The image should be premium, "
                    "photorealistic, with a dark/moody aesthetic matching a luxury Malaysian "
                    "bird's nest brand. No text in the image.\n\n"
                    f"Post:\n{post_text}\n\n"
                    "Return ONLY the image prompt, no explanation."
                ),
            }
        ],
    )
    return response.content[0].text


def generate_holiday_greeting(holiday_name: str, holiday_name_zh: str) -> str:
    """Pre-generate a holiday greeting post (batched at setup time)."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a warm holiday greeting post for {holiday_name} ({holiday_name_zh}) "
                    "from JinYi Group. Keep it sincere, premium, and culturally appropriate. "
                    "Bilingual EN + ZH format with relevant emoji and hashtags."
                ),
            }
        ],
    )
    return response.content[0].text
