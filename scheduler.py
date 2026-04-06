"""
scheduler.py — APScheduler Tier 1 jobs for JinYi Telegram Bot
Jobs:
  - Did You Know: Tuesday + Thursday 10:00 AM MYT
  - Weekly Digest: Every Friday 9:00 AM MYT
  - Holiday Greetings: 8:00 AM eve of each holiday (pre-generated at startup)
"""

import json
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from content import generate_weekly_digest, generate_holiday_greeting
from researcher import research_trending_content
from publisher import publish_to_facebook

logger = logging.getLogger(__name__)

MYT = pytz.timezone("Asia/Kuala_Lumpur")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))
DYK_BANK_PATH = Path(__file__).parent / "dyk_bank.json"
HOLIDAYS_PATH = Path(__file__).parent / "holiday_greetings.json"
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "")  # e.g. "@jinyi_official"

LOW_BANK_THRESHOLD = 10


# ─────────────────────────────────────────────
#  DYK Bank helpers
# ─────────────────────────────────────────────

def load_dyk_bank() -> list[dict]:
    with open(DYK_BANK_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_dyk_bank(bank: list[dict]) -> None:
    with open(DYK_BANK_PATH, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


def get_unused_dyk(bank: list[dict]) -> dict | None:
    unused = [p for p in bank if not p.get("used")]
    return random.choice(unused) if unused else None


def mark_dyk_used(bank: list[dict], post_id: int) -> list[dict]:
    for p in bank:
        if p["id"] == post_id:
            p["used"] = True
    return bank


def count_unused_dyk(bank: list[dict]) -> int:
    return sum(1 for p in bank if not p.get("used"))


# ─────────────────────────────────────────────
#  Holiday greetings helpers
# ─────────────────────────────────────────────

HOLIDAYS_2026 = [
    {"date": "2026-01-01", "name": "New Year's Day",       "name_zh": "元旦"},
    {"date": "2026-01-29", "name": "Chinese New Year Eve",  "name_zh": "除夕"},
    {"date": "2026-01-30", "name": "Chinese New Year",      "name_zh": "农历新年"},
    {"date": "2026-01-31", "name": "Chinese New Year Day 2","name_zh": "农历新年初二"},
    {"date": "2026-03-20", "name": "Hari Raya Aidilfitri",  "name_zh": "开斋节"},
    {"date": "2026-05-01", "name": "Labour Day",            "name_zh": "劳动节"},
    {"date": "2026-05-25", "name": "Hari Raya Aidiladha",   "name_zh": "哈芝节"},
    {"date": "2026-08-31", "name": "National Day",          "name_zh": "国庆日"},
    {"date": "2026-09-16", "name": "Malaysia Day",          "name_zh": "马来西亚日"},
    {"date": "2026-12-25", "name": "Christmas",             "name_zh": "圣诞节"},
]


def load_or_generate_holidays(bot: Bot = None) -> list[dict]:
    """Load cached holiday greetings or generate them via Claude."""
    if HOLIDAYS_PATH.exists():
        with open(HOLIDAYS_PATH, encoding="utf-8") as f:
            return json.load(f)

    logger.info("Generating holiday greetings via Claude (one-time batch)...")
    greetings = []
    for h in HOLIDAYS_2026:
        try:
            text = generate_holiday_greeting(h["name"], h["name_zh"])
            greetings.append({"date": h["date"], "name": h["name"], "text": text, "sent": False})
            logger.info(f"  ✓ Generated: {h['name']}")
        except Exception as e:
            logger.error(f"  ✗ Failed {h['name']}: {e}")

    with open(HOLIDAYS_PATH, "w", encoding="utf-8") as f:
        json.dump(greetings, f, ensure_ascii=False, indent=2)

    return greetings


# ─────────────────────────────────────────────
#  Job: Did You Know (Tue + Thu 10am)
# ─────────────────────────────────────────────

async def job_dyk(bot: Bot) -> None:
    logger.info("Running DYK job...")
    bank = load_dyk_bank()
    unused_count = count_unused_dyk(bank)

    post = get_unused_dyk(bank)
    if not post:
        # All used — reset and start again
        for p in bank:
            p["used"] = False
        save_dyk_bank(bank)
        post = get_unused_dyk(bank)
        await bot.send_message(OWNER_CHAT_ID, "♻️ DYK bank fully cycled — resetting all posts to unused.")

    # Pick language based on day (Tue = EN, Thu = ZH) — or send both
    text = f"{post['en']}\n\n———\n\n{post['zh']}"

    # Send to channel if configured
    if TELEGRAM_CHANNEL:
        await bot.send_message(TELEGRAM_CHANNEL, text)
    else:
        # Fallback: send to owner as a preview
        await bot.send_message(OWNER_CHAT_ID, f"📤 DYK posted (no channel set):\n\n{text}")

    # Publish to Facebook
    publish_to_facebook(text)

    # Mark used
    bank = mark_dyk_used(bank, post["id"])
    save_dyk_bank(bank)

    # Low bank alert
    remaining = count_unused_dyk(bank)
    if remaining < LOW_BANK_THRESHOLD:
        await bot.send_message(
            OWNER_CHAT_ID,
            f"⚠️ DYK bank low — only {remaining} unused posts remaining. "
            "Please add more posts to dyk_bank.json.",
        )

    logger.info(f"DYK job done. {remaining} posts remaining.")


# ─────────────────────────────────────────────
#  Job: Weekly Digest (Friday 9am)
# ─────────────────────────────────────────────

async def job_weekly_digest(bot: Bot) -> None:
    logger.info("Running Weekly Digest job...")
    try:
        text = generate_weekly_digest()

        if TELEGRAM_CHANNEL:
            await bot.send_message(TELEGRAM_CHANNEL, text)
        else:
            await bot.send_message(OWNER_CHAT_ID, f"📤 Weekly Digest (no channel set):\n\n{text}")

        publish_to_facebook(text)
        logger.info("Weekly Digest job done.")
    except Exception as e:
        logger.error(f"Weekly Digest job FAILED: {e}")
        await bot.send_message(OWNER_CHAT_ID, f"❌ Weekly Digest failed: {e}")


# ─────────────────────────────────────────────
#  Job: Holiday greetings (8am eve of holiday)
# ─────────────────────────────────────────────

async def job_check_holidays(bot: Bot) -> None:
    """Check if tomorrow is a holiday and post the greeting today at 8am."""
    greetings = load_or_generate_holidays()
    tomorrow = (datetime.now(MYT) + timedelta(days=1)).strftime("%Y-%m-%d")

    for g in greetings:
        if g["date"] == tomorrow and not g.get("sent"):
            text = g["text"]

            if TELEGRAM_CHANNEL:
                await bot.send_message(TELEGRAM_CHANNEL, text)
            else:
                await bot.send_message(OWNER_CHAT_ID, f"📤 Holiday greeting (no channel set):\n\n{text}")

            publish_to_facebook(text)

            g["sent"] = True
            with open(HOLIDAYS_PATH, "w", encoding="utf-8") as f:
                json.dump(greetings, f, ensure_ascii=False, indent=2)

            logger.info(f"Holiday greeting sent for {g['name']}")


# ─────────────────────────────────────────────
#  Job: Weekly Content Research (Monday 9am)
# ─────────────────────────────────────────────

async def job_content_research(bot: Bot) -> None:
    logger.info("Running Weekly Content Research job...")
    try:
        report = research_trending_content(num_ideas=5)
        await bot.send_message(
            OWNER_CHAT_ID,
            report,
            parse_mode="Markdown",
        )
        logger.info("Content research delivered to owner.")
    except Exception as e:
        logger.error(f"Content research job FAILED: {e}")
        await bot.send_message(OWNER_CHAT_ID, f"❌ Content research failed: {e}")


# ─────────────────────────────────────────────
#  Scheduler setup
# ─────────────────────────────────────────────

def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MYT)

    # Did You Know — Tuesday (day_of_week=1) + Thursday (day_of_week=3) at 10:00am
    scheduler.add_job(
        job_dyk,
        trigger="cron",
        day_of_week="1,3",
        hour=10,
        minute=0,
        args=[bot],
        id="dyk_job",
        name="Did You Know",
        replace_existing=True,
    )

    # Weekly Digest — Friday at 9:00am
    scheduler.add_job(
        job_weekly_digest,
        trigger="cron",
        day_of_week="4",
        hour=9,
        minute=0,
        args=[bot],
        id="digest_job",
        name="Weekly Digest",
        replace_existing=True,
    )

    # Holiday check — daily at 8:00am (posts eve-of-holiday greeting)
    scheduler.add_job(
        job_check_holidays,
        trigger="cron",
        hour=8,
        minute=0,
        args=[bot],
        id="holiday_job",
        name="Holiday Greetings",
        replace_existing=True,
    )

    # Content Research — every Monday 9:00am (小红书 + Douyin trending ideas)
    scheduler.add_job(
        job_content_research,
        trigger="cron",
        day_of_week="0",  # Monday
        hour=9,
        minute=0,
        args=[bot],
        id="research_job",
        name="Weekly Content Research",
        replace_existing=True,
    )

    return scheduler
