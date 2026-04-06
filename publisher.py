"""
publisher.py — Cross-platform publishing for JinYi Telegram Bot
Platforms: Telegram channel/group, Facebook Page, Instagram (via Graph API)
WordPress blog publishing is handled separately as a future step.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID")


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
#  Convenience: publish to all platforms
# ─────────────────────────────────────────────

def publish_all(
    text: str,
    telegram_channel: str | None = None,
    image_path: str | None = None,
    instagram_image_url: str | None = None,
) -> dict:
    """
    Publish to all configured platforms.
    Returns a dict of results: { "telegram": bool, "facebook": bool, "instagram": bool }
    """
    results = {}

    if telegram_channel:
        results["telegram"] = publish_to_telegram_channel(telegram_channel, text, image_path)

    results["facebook"] = publish_to_facebook(text, image_path)

    if instagram_image_url:
        results["instagram"] = publish_to_instagram(text, instagram_image_url)
    else:
        results["instagram"] = False  # IG requires an image

    return results
