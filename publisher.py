"""
publisher.py — Cross-platform publishing for JinYi Telegram Bot
Platforms: Telegram channel/group, Facebook Page, Instagram (via Graph API)
WordPress blog publishing is handled separately as a future step.
"""

import os
import logging
import re
import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID")
WEBSITE_URL = os.getenv("WEBSITE_URL", "").rstrip("/")
BLOG_API_SECRET = os.getenv("BLOG_API_SECRET", "")


# ─────────────────────────────────────────────
#  Telegram
# ─────────────────────────────────────────────

def publish_to_telegram_channel(channel_id: str, text: str, image_path: str | None = None) -> bool:
    """
    Publish a post to a Telegram channel.
    channel_id: e.g. "@jinyi_channel" or numeric chat id
    """
    base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    try:
        if image_path:
            with open(image_path, "rb") as img:
                resp = requests.post(
                    f"{base_url}/sendPhoto",
                    data={"chat_id": channel_id, "caption": text, "parse_mode": "HTML"},
                    files={"photo": img},
                    timeout=30,
                )
        else:
            resp = requests.post(
                f"{base_url}/sendMessage",
                json={"chat_id": channel_id, "text": text, "parse_mode": "HTML"},
                timeout=30,
            )
        resp.raise_for_status()
        logger.info(f"Telegram publish OK to {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Telegram publish FAILED: {e}")
        return False


# ─────────────────────────────────────────────
#  Facebook
# ─────────────────────────────────────────────

def publish_to_facebook(text: str, image_path: str | None = None) -> bool:
    """Publish a post to the Facebook Page."""
    if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
        logger.warning("Facebook credentials not set — skipping FB publish")
        return False

    try:
        if image_path:
            url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
            with open(image_path, "rb") as img:
                resp = requests.post(
                    url,
                    data={"message": text, "access_token": FB_PAGE_ACCESS_TOKEN},
                    files={"source": img},
                    timeout=30,
                )
        else:
            url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed"
            resp = requests.post(
                url,
                json={"message": text, "access_token": FB_PAGE_ACCESS_TOKEN},
                timeout=30,
            )
        resp.raise_for_status()
        logger.info("Facebook publish OK")
        return True
    except Exception as e:
        logger.error(f"Facebook publish FAILED: {e}")
        return False


# ─────────────────────────────────────────────
#  Instagram (Graph API — requires image)
# ─────────────────────────────────────────────

def publish_to_instagram(text: str, image_url: str) -> bool:
    """
    Publish to Instagram via Graph API.
    image_url must be a publicly accessible URL (upload to CDN first).
    """
    if not IG_ACCOUNT_ID or not FB_PAGE_ACCESS_TOKEN:
        logger.warning("Instagram credentials not set — skipping IG publish")
        return False

    try:
        # Step 1: Create media container
        create_url = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}/media"
        create_resp = requests.post(
            create_url,
            json={
                "image_url": image_url,
                "caption": text,
                "access_token": FB_PAGE_ACCESS_TOKEN,
            },
            timeout=30,
        )
        create_resp.raise_for_status()
        container_id = create_resp.json()["id"]

        # Step 2: Publish container
        publish_url = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}/media_publish"
        pub_resp = requests.post(
            publish_url,
            json={"creation_id": container_id, "access_token": FB_PAGE_ACCESS_TOKEN},
            timeout=30,
        )
        pub_resp.raise_for_status()
        logger.info("Instagram publish OK")
        return True
    except Exception as e:
        logger.error(f"Instagram publish FAILED: {e}")
        return False


# ─────────────────────────────────────────────
#  Website / Blog (Supabase via Next.js API)
# ─────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert a title/brief into a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug[:80].strip("-")
    return slug or "post"


def _split_bilingual(text: str) -> tuple[str, str]:
    """
    Split a bilingual post into (en, zh) parts.
    Posts are structured as: [EN content] \\n\\n——— \\n\\n[ZH content]
    """
    parts = re.split(r"\n\s*———\s*\n", text, maxsplit=1)
    en = parts[0].strip() if parts else text.strip()
    zh = parts[1].strip() if len(parts) > 1 else ""
    return en, zh


def publish_to_website(
    title: str,
    text: str,
    track: str = "investor",
    video_url: str | None = None,
    image_url: str | None = None,
) -> bool:
    """Publish a post to the website blog via the Next.js API route."""
    if not WEBSITE_URL or not BLOG_API_SECRET:
        logger.warning("WEBSITE_URL or BLOG_API_SECRET not set — skipping website publish")
        return False

    content_en, content_zh = _split_bilingual(text)

    # Extract hashtags from EN section
    hashtag_match = re.findall(r"#\w+", content_en)
    hashtags = " ".join(hashtag_match) if hashtag_match else None

    slug = _slugify(title)

    payload = {
        "secret": BLOG_API_SECRET,
        "slug": slug,
        "title": title,
        "content_en": content_en,
        "content_zh": content_zh or None,
        "track": track,
        "hashtags": hashtags,
        "video_url": video_url,
        "image_url": image_url,
    }

    try:
        resp = requests.post(
            f"{WEBSITE_URL}/api/posts",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Website publish OK: {data.get('slug')}")
        return True
    except Exception as e:
        logger.error(f"Website publish FAILED: {e}")
        return False


# ─────────────────────────────────────────────
#  Convenience: publish to all platforms
# ─────────────────────────────────────────────

def publish_all(
    text: str,
    blog_text: str | None = None,
    title: str = "JinYi Update",
    track: str = "investor",
    telegram_channel: str | None = None,
    image_path: str | None = None,
    instagram_image_url: str | None = None,
    video_url: str | None = None,
    targets: list[str] | None = None,
) -> dict:
    """
    Publish to configured platforms.
    targets: optional list to restrict which platforms to post to.
             e.g. ["facebook", "telegram"] or ["website"]
             If None, posts to all platforms.
    Returns a dict of results: { "telegram": bool, "facebook": bool, "website": bool }
    """
    results = {}
    run_all = targets is None

    if (run_all or "telegram" in targets) and telegram_channel:
        results["telegram"] = publish_to_telegram_channel(telegram_channel, text, image_path)

    if run_all or "facebook" in targets:
        results["facebook"] = publish_to_facebook(text, image_path)

    if run_all or "website" in targets:
        results["website"] = publish_to_website(
            title=title,
            text=blog_text or text,   # prefer long-form article for blog
            track=track,
            video_url=video_url,
            image_url=None,
        )

    if instagram_image_url and (run_all or "instagram" in targets):
        results["instagram"] = publish_to_instagram(text, instagram_image_url)

    return results
