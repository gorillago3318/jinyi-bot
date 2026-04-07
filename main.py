"""
main.py — JinYi Telegram Content Bot
Commands registered as Telegram menu (tap "/" to see all).
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, Bot, BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

from content import (
    generate_tier2_draft,
    revise_draft,
    draft_from_photo_caption,
    generate_image_prompt,
    generate_xhs_post,
    generate_douyin_script,
    generate_wechat_post,
    generate_blog_article,
    generate_copypaste_blocks,
    generate_linkedin_post,
)
from publisher import publish_all
from scheduler import build_scheduler, load_dyk_bank, count_unused_dyk
from researcher import research_trending_content, research_with_kimi_search
from imager import generate_image, generate_post_images
# from kling import submit_text_to_video, poll_video_result, download_video  # disabled — no video platform

# ── Logging ──────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "")

# ── Draft state ──────────────────────────────
draft_state: dict[int, dict] = {}

# ── Telegram command menu ────────────────────
BOT_COMMANDS = [
    BotCommand("draft",    "Bilingual post · /draft [investor|consumer] [topic]"),
    BotCommand("linkedin", "LinkedIn thought leadership post · /linkedin [topic]"),
    BotCommand("xhs",      "Xiaohongshu post · /xhs [investor|consumer] [topic]"),
    BotCommand("douyin",   "Douyin script · /douyin [investor|consumer] [topic]"),
    BotCommand("wechat",   "WeChat post · /wechat [investor|consumer] [moments|article] [topic]"),
    BotCommand("research", "Research trending Xiaohongshu & Douyin topics"),
    BotCommand("approve",  "Publish current draft to all channels"),
    BotCommand("image",    "Attach image to current draft"),
    BotCommand("bank",     "Show Did You Know post bank count"),
    BotCommand("status",   "Show scheduled jobs"),
    BotCommand("cancel",   "Discard current draft"),
    BotCommand("start",    "Show all commands"),
]

# Default investor topics for random selection when no topic given
TIER2_INVESTOR_TOPICS = [
    "why swiftlet farming offers a different risk profile compared to REITs",
    "JinYi's 20+ years of tracked yield data across Sabah and Sarawak",
    "what asset ownership looks like in a managed swiftlet farm",
    "the regulated supply chain that protects JinYi investors",
    "how bird's nest commodity pricing has trended over the past decade",
    "why location matters: Borneo vs other swiftlet farming regions",
    "understanding harvest cycles and yield expectations",
    "how JinYi's 36+ locations reduce concentration risk",
    "the difference between owning a swiftlet asset vs a traditional property investment",
    "why sophisticated investors are looking at alternative agricultural assets",
]

# Default consumer topics
TIER2_CONSUMER_TOPICS = [
    "how to properly prepare bird's nest at home",
    "the difference between cave nest and house nest",
    "how to identify authentic bird's nest vs fake",
    "why Sabah bird's nest commands a higher price",
    "bird's nest storage tips to preserve quality",
    "simple bird's nest recipe for daily consumption",
    "what the grading system means for bird's nest quality",
    "bird's nest for new mothers: what you need to know",
]


# Video generation disabled — no platform available yet.
# Re-enable when a working video API is available.


async def _generate_images_background(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    img_prompt: str,
    topic: str,
) -> None:
    """
    Generate post images via Imagen 3 in background.
    Sends all format variants to owner as a media group.
    Saves square image path to draft_state for blog upload.
    """
    try:
        loop = asyncio.get_event_loop()
        paths = await loop.run_in_executor(None, generate_post_images, img_prompt)

        if not paths:
            await context.bot.send_message(chat_id, "⚠️ Image generation returned no results.")
            return

        # Save square image to draft_state for /approve blog upload
        if chat_id in draft_state and "square" in paths:
            draft_state[chat_id]["image_path"] = paths["square"]

        # Send images as labelled messages
        labels = {
            "square":   "🟫 Square — Blog / general",
            "portrait": "📕 3:4 — XHS copy-paste",
            "facebook": "📘 4:5 — Facebook feed",
            "linkedin": "💼 16:9 — LinkedIn",
        }
        await context.bot.send_message(
            chat_id,
            "🖼 *Images ready!* Copy to your platforms:\n\n"
            "• Square → Blog (auto-attached on /approve)\n"
            "• 3:4 → XHS\n"
            "• 4:5 → Facebook\n"
            "• 16:9 → LinkedIn",
            parse_mode="Markdown",
        )
        for fmt, path in paths.items():
            if Path(path).exists():
                with open(path, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=labels.get(fmt, fmt),
                    )
                # Clean up non-square images (square kept for /approve)
                if fmt != "square":
                    Path(path).unlink(missing_ok=True)

    except Exception as e:
        logger.warning(f"Image generation failed (non-fatal): {e}")
        await context.bot.send_message(
            chat_id,
            f"⚠️ Image generation failed: {e}\n_Use the image prompt above in Canva / Firefly manually._",
            parse_mode="Markdown",
        )


async def _generate_blog_background(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, topic: str, track: str
) -> None:
    """
    Generate a long-form blog article in background.
    - If draft still pending: store in draft_state for /approve to use.
    - If draft already approved (race condition): post directly to website now.
    """
    try:
        loop = asyncio.get_event_loop()
        article = await loop.run_in_executor(None, generate_blog_article, topic, track)

        if chat_id in draft_state:
            # Draft still waiting — store for /approve
            draft_state[chat_id]["blog_article"] = article
            await context.bot.send_message(
                chat_id,
                "📝 *Blog article ready!*\n\n"
                "_Preview:_\n" + article[:400] + "…\n\n"
                "✅ *Ready to publish — tap /approve now.*",
                parse_mode="Markdown",
            )
        else:
            # Draft already approved — post directly to website now
            from publisher import publish_to_website
            ok = publish_to_website(title=topic, text=article, track=track)
            status = "✅ saved to website blog" if ok else "❌ website save failed"
            await context.bot.send_message(
                chat_id,
                f"📝 *Blog article posted* ({status})\n\n"
                "_Preview:_\n" + article[:400] + "…",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.warning(f"Blog article generation failed (non-fatal): {e}")


def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_CHAT_ID:
            await update.message.reply_text("Authorised users only.")
            return
        return await func(update, context)
    return wrapper


# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────

def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for the main menu."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✍️ Draft (Investor)", callback_data="menu:draft:investor"),
            InlineKeyboardButton("✍️ Draft (Consumer)", callback_data="menu:draft:consumer"),
        ],
        [
            InlineKeyboardButton("📕 XHS (Investor)", callback_data="menu:xhs:investor"),
            InlineKeyboardButton("📕 XHS (Consumer)", callback_data="menu:xhs:consumer"),
        ],
        [
            InlineKeyboardButton("🎬 Douyin (Investor)", callback_data="menu:douyin:investor"),
            InlineKeyboardButton("🎬 Douyin (Consumer)", callback_data="menu:douyin:consumer"),
        ],
        [
            InlineKeyboardButton("💬 WeChat Moments", callback_data="menu:wechat:investor:moments"),
            InlineKeyboardButton("📰 WeChat Article", callback_data="menu:wechat:investor:article"),
        ],
        [
            InlineKeyboardButton("🔍 Research Trends", callback_data="menu:research"),
            InlineKeyboardButton("🎥 Quick Video", callback_data="menu:video"),
        ],
        [
            InlineKeyboardButton("✅ Approve Draft", callback_data="menu:approve"),
            InlineKeyboardButton("❌ Cancel Draft", callback_data="menu:cancel"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="menu:status"),
            InlineKeyboardButton("📚 Bank", callback_data="menu:bank"),
        ],
    ])


@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *JinYi Content Bot*\n\n"
        "Two tracks: *Investor* (HNW, asset management tone) · *Consumer* (health & lifestyle)\n\n"
        "Tap a button to get started, or type `/draft [topic]` directly.",
        parse_mode="Markdown",
        reply_markup=_main_menu_keyboard(),
    )


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses from /start menu."""
    query = update.callback_query
    await query.answer()

    if query.from_user.id != OWNER_CHAT_ID:
        return

    data = query.data  # e.g. "menu:draft:investor"
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "draft":
        track = parts[2] if len(parts) > 2 else "investor"
        track_label = "Investor" if track == "investor" else "Consumer"
        await query.edit_message_text(
            f"✍️ *{track_label} Draft*\n\n"
            f"Send me your topic and I'll write the post.\n"
            f"Or just send anything and I'll pick a topic.\n\n"
            f"Type: `/draft {track} [your topic]`",
            parse_mode="Markdown",
        )
        context.user_data["pending_track"] = track
        context.user_data["pending_command"] = "draft"

    elif action == "xhs":
        track = parts[2] if len(parts) > 2 else "investor"
        track_label = "Investor" if track == "investor" else "Consumer"
        await query.edit_message_text(
            f"📕 *Xiaohongshu — {track_label}*\n\n"
            f"Type: `/xhs {track} [your topic]`\n\n"
            f"Or reply with just a topic and I'll create the post.",
            parse_mode="Markdown",
        )
        context.user_data["pending_track"] = track
        context.user_data["pending_command"] = "xhs"

    elif action == "douyin":
        track = parts[2] if len(parts) > 2 else "investor"
        track_label = "Investor" if track == "investor" else "Consumer"
        await query.edit_message_text(
            f"🎬 *Douyin — {track_label}*\n\n"
            f"Type: `/douyin {track} [your topic]`\n\n"
            f"I'll write the script and generate a Kling video.",
            parse_mode="Markdown",
        )
        context.user_data["pending_track"] = track
        context.user_data["pending_command"] = "douyin"

    elif action == "wechat":
        track = parts[2] if len(parts) > 2 else "investor"
        fmt = parts[3] if len(parts) > 3 else "moments"
        track_label = "Investor" if track == "investor" else "Consumer"
        fmt_label = "Article" if fmt == "article" else "Moments"
        await query.edit_message_text(
            f"💬 *WeChat {fmt_label} — {track_label}*\n\n"
            f"Type: `/wechat {track} {fmt} [your topic]`",
            parse_mode="Markdown",
        )
        context.user_data["pending_track"] = track
        context.user_data["pending_command"] = f"wechat:{fmt}"

    elif action == "research":
        await query.edit_message_text("🔍 Running weekly research... (~30 seconds)")
        try:
            report = research_trending_content(num_ideas=5)
            await context.bot.send_message(query.message.chat_id, report)
        except Exception as e:
            await context.bot.send_message(query.message.chat_id, f"Research failed: {e}")

    elif action == "video":
        await query.edit_message_text(
            "🎥 *Quick Kling Video*\n\n"
            "Type: `/video [visual description]`\n\n"
            "Example: `/video swiftlet birds flying into nest house at golden hour borneo rainforest`",
            parse_mode="Markdown",
        )

    elif action == "approve":
        # Trigger approve inline
        chat_id = query.message.chat_id
        state = draft_state.get(chat_id)
        if not state or not state.get("draft"):
            await query.edit_message_text("No draft to approve. Create one first.")
            return
        await query.edit_message_text("Publishing...")
        results = publish_all(
            text=state["draft"],
            blog_text=state.get("blog_article") or state["draft"],
            title=state.get("title", "JinYi Update"),
            track=state.get("track", "investor"),
            telegram_channel=TELEGRAM_CHANNEL or None,
            image_path=state.get("image_path"),
            video_url=state.get("video_url"),
        )
        lines = [("✅" if ok else "❌") + f" {p.capitalize()}" for p, ok in results.items()]
        await context.bot.send_message(chat_id, "Published:\n" + "\n".join(lines))
        if state.get("image_path"):
            Path(state["image_path"]).unlink(missing_ok=True)
        draft_state.pop(chat_id, None)

    elif action == "cancel":
        chat_id = query.message.chat_id
        if chat_id in draft_state:
            del draft_state[chat_id]
            await query.edit_message_text("Draft discarded.")
        else:
            await query.edit_message_text("No active draft.")

    elif action == "status":
        scheduler = context.bot_data.get("scheduler")
        if not scheduler:
            await query.edit_message_text("Scheduler not running.")
            return
        jobs = scheduler.get_jobs()
        lines = ["📅 *Scheduled Jobs:*\n"]
        for job in jobs:
            next_run = job.next_run_time
            t = next_run.strftime("%a %d %b, %I:%M %p MYT") if next_run else "N/A"
            lines.append(f"• *{job.name}* — {t}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")

    elif action == "bank":
        bank = load_dyk_bank()
        unused = count_unused_dyk(bank)
        total = len(bank)
        await query.edit_message_text(
            f"📚 *Did You Know Bank:* {unused}/{total} posts remaining\n\n"
            f"Sent Tue + Thu at 10am. At 2/week, ~{unused // 2} weeks of content left.",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────
#  /draft
# ─────────────────────────────────────────────

@owner_only
async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import random
    chat_id = update.effective_chat.id
    args = list(context.args or [])

    # Parse optional track flag as first word
    track = "investor"
    if args and args[0].lower() in ("investor", "consumer", "inv", "con", "i", "c"):
        track = args.pop(0).lower()

    brief = " ".join(args) if args else random.choice(
        TIER2_INVESTOR_TOPICS if track in ("investor", "inv", "i") else TIER2_CONSUMER_TOPICS
    )
    track_label = "Investor" if track in ("investor", "inv", "i") else "Consumer"

    await update.message.reply_text(
        f"Writing *{track_label}* post: _{brief}_...", parse_mode="Markdown"
    )

    try:
        draft = generate_tier2_draft(brief, track=track)
        img_prompt = generate_image_prompt(draft)
        draft_state[chat_id] = {
            "draft": draft,
            "title": brief,
            "track": track,
            "image_path": None,
            "video_url": None,
            "blog_article": None,  # filled by background task
            "history": [
                {"role": "user", "content": f"Write a {track_label} post about: {brief}"},
                {"role": "assistant", "content": draft},
            ],
        }
        await update.message.reply_text(
            f"{draft}\n\n———\n"
            "Reply with feedback to revise · /approve to publish · /cancel to discard\n\n"
            "_📝 Blog article + 🖼 Images generating in background — wait for both before /approve_",
            parse_mode="Markdown",
        )
        asyncio.create_task(_generate_blog_background(context, chat_id, brief, track))
        asyncio.create_task(_generate_images_background(context, chat_id, img_prompt, brief))
    except Exception as e:
        err = str(e)
        if "402" in err or "Insufficient Balance" in err:
            await update.message.reply_text(
                "⚠️ *DeepSeek out of credit.*\n\n"
                "Top up at: platform.deepseek.com → Billing → Top Up\n"
                "Minimum $5. Then try again.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Draft failed: {e}")


# ─────────────────────────────────────────────
#  /xhs
# ─────────────────────────────────────────────

@owner_only
async def cmd_xhs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import random
    chat_id = update.effective_chat.id
    args = list(context.args or [])

    track = "investor"
    if args and args[0].lower() in ("investor", "consumer", "inv", "con", "i", "c"):
        track = args.pop(0).lower()

    topic = " ".join(args) if args else random.choice(
        TIER2_INVESTOR_TOPICS if track in ("investor", "inv", "i") else TIER2_CONSUMER_TOPICS
    )
    track_label = "Investor" if track in ("investor", "inv", "i") else "Consumer"

    await update.message.reply_text(
        f"Writing *{track_label}* Xiaohongshu post: _{topic}_...", parse_mode="Markdown"
    )

    try:
        post = generate_xhs_post(topic, track=track)
        img_prompt = generate_image_prompt(post)
        draft_state[chat_id] = {
            "draft": post,
            "title": topic,
            "track": track,
            "image_path": None,
            "video_url": None,
            "history": [
                {"role": "user", "content": f"Xiaohongshu {track_label} topic: {topic}"},
                {"role": "assistant", "content": post},
            ],
        }
        await update.message.reply_text(
            f"{post}\n\n———\n"
            "Reply with feedback · /approve · /cancel\n\n"
            f"🖼 *Image prompt:*\n`{img_prompt}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        err = str(e)
        if "402" in err or "Insufficient Balance" in err:
            await update.message.reply_text(
                "⚠️ *DeepSeek out of credit.*\n\nTop up at: platform.deepseek.com → Billing → Top Up",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Failed: {e}")


# ─────────────────────────────────────────────
#  /douyin
# ─────────────────────────────────────────────

@owner_only
async def cmd_douyin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import random
    chat_id = update.effective_chat.id
    args = list(context.args or [])

    # Parse track flag
    track = "investor"
    if args and args[0].lower() in ("investor", "consumer", "inv", "con", "i", "c"):
        track = args.pop(0).lower()

    # Optional duration as next arg: /douyin investor 10 topic...
    duration_sec = 5
    if args and args[0].isdigit():
        duration_sec = min(max(int(args.pop(0)), 5), 10)

    track_label = "Investor" if track in ("investor", "inv", "i") else "Consumer"
    topic = " ".join(args) if args else random.choice(
        TIER2_INVESTOR_TOPICS if track in ("investor", "inv", "i") else TIER2_CONSUMER_TOPICS
    )
    duration_label = f"{duration_sec}s"

    await update.message.reply_text(
        f"🎬 *Douyin pipeline starting*\n\n"
        f"Track: *{track_label}*\n"
        f"Topic: _{topic}_\n"
        f"Steps: DeepSeek script → Kling {duration_label} video\n\n"
        "_This takes about 2–3 minutes..._",
        parse_mode="Markdown",
    )

    # Step 1 — Script
    try:
        script = generate_douyin_script(topic, f"{duration_sec} seconds", track=track)
    except Exception as e:
        err = str(e)
        if "402" in err or "Insufficient Balance" in err:
            await update.message.reply_text(
                "⚠️ *DeepSeek out of credit.*\n\nTop up at: platform.deepseek.com → Billing → Top Up",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Script generation failed: {e}")
        return

    await update.message.reply_text(
        f"✅ *Script ready:*\n\n{script}\n\n_Submitting to Kling for video..._",
        parse_mode="Markdown",
    )

    # Step 2 — Kling video
    visual_prompt = (
        f"Premium bird's nest swiftlet farming in Sabah Borneo Malaysia. "
        f"{topic}. Cinematic vertical 9:16, warm golden tones, "
        f"lush tropical rainforest, professional documentary style, no text."
    )

    try:
        task_id = submit_text_to_video(
            prompt=visual_prompt,
            duration=duration_sec,
            aspect_ratio="9:16",
            model="kling-v1-6",
            mode="std",
        )
        await update.message.reply_text(
            f"Kling task submitted — ID: `{task_id}`\n_Waiting for render..._",
            parse_mode="Markdown",
        )

        loop = asyncio.get_event_loop()
        video_url = await loop.run_in_executor(None, poll_video_result, task_id)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await loop.run_in_executor(None, download_video, video_url, tmp_path)

        with open(tmp_path, "rb") as vf:
            await context.bot.send_video(
                chat_id=chat_id,
                video=vf,
                caption=f"🎬 {topic}\n\nPost to Douyin manually with the script above.",
            )
        Path(tmp_path).unlink(missing_ok=True)
        await update.message.reply_text("Done. Reply with feedback to revise the script · /cancel to discard.")

    except Exception as e:
        logger.error(f"Kling failed: {e}")
        await update.message.reply_text(f"Video generation failed: {e}\n\nScript saved — you can record manually.")

    draft_state[chat_id] = {
        "draft": script,
        "title": topic,
        "track": track,
        "image_path": None,
        "video_url": None,
        "history": [
            {"role": "user", "content": f"Douyin {track_label} script: {topic}"},
            {"role": "assistant", "content": script},
        ],
    }


# ─────────────────────────────────────────────
#  /video
# ─────────────────────────────────────────────

@owner_only
async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "Usage: `/video [visual prompt]`\n\n"
            "Example: `/video swiftlet birds flying into nest house at golden hour borneo rainforest`",
            parse_mode="Markdown",
        )
        return

    prompt = " ".join(context.args)
    await update.message.reply_text(
        f"🎬 Generating video...\n`{prompt}`\n\n_~2–3 minutes_",
        parse_mode="Markdown",
    )

    try:
        task_id = submit_text_to_video(prompt=prompt, duration=5, aspect_ratio="9:16")
        loop = asyncio.get_event_loop()
        video_url = await loop.run_in_executor(None, poll_video_result, task_id)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await loop.run_in_executor(None, download_video, video_url, tmp_path)

        with open(tmp_path, "rb") as vf:
            await context.bot.send_video(chat_id=chat_id, video=vf, caption=f"🎬 {prompt}")
        Path(tmp_path).unlink(missing_ok=True)

    except Exception as e:
        await update.message.reply_text(f"Video generation failed: {e}")


# ─────────────────────────────────────────────
#  /wechat
# ─────────────────────────────────────────────

@owner_only
async def cmd_wechat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import random
    chat_id = update.effective_chat.id
    args = list(context.args or [])

    # Parse track flag
    track = "investor"
    if args and args[0].lower() in ("investor", "consumer", "inv", "con", "i", "c"):
        track = args.pop(0).lower()

    # Parse format flag
    fmt = "moments"
    if args and args[0].lower() in ("article", "moments"):
        fmt = args.pop(0).lower()

    track_label = "Investor" if track in ("investor", "inv", "i") else "Consumer"
    topic = " ".join(args) if args else random.choice(
        TIER2_INVESTOR_TOPICS if track in ("investor", "inv", "i") else TIER2_CONSUMER_TOPICS
    )
    fmt_label = "Article" if fmt == "article" else "Moments post"

    await update.message.reply_text(
        f"Writing WeChat *{track_label}* {fmt_label}: _{topic}_...", parse_mode="Markdown"
    )

    try:
        post = generate_wechat_post(topic, fmt, track=track)
        draft_state[chat_id] = {
            "draft": post,
            "title": topic,
            "track": track,
            "image_path": None,
            "video_url": None,
            "history": [
                {"role": "user", "content": f"WeChat {track_label} {fmt_label}: {topic}"},
                {"role": "assistant", "content": post},
            ],
        }
        await update.message.reply_text(
            f"{post}\n\n———\nReply with feedback · /cancel to discard.",
            parse_mode="Markdown",
        )
    except Exception as e:
        err = str(e)
        if "402" in err or "Insufficient Balance" in err:
            await update.message.reply_text(
                "⚠️ *DeepSeek out of credit.*\n\nTop up at: platform.deepseek.com → Billing → Top Up",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Failed: {e}")


# ─────────────────────────────────────────────
#  /linkedin
# ─────────────────────────────────────────────

@owner_only
async def cmd_linkedin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import random
    chat_id = update.effective_chat.id
    args = list(context.args or [])

    track = "investor"
    if args and args[0].lower() in ("investor", "consumer", "inv", "con", "i", "c"):
        track = args.pop(0).lower()

    topic = " ".join(args) if args else random.choice(TIER2_INVESTOR_TOPICS)

    await update.message.reply_text(
        f"Writing LinkedIn post: _{topic}_...", parse_mode="Markdown"
    )

    try:
        post = generate_linkedin_post(topic, track=track)
        img_prompt = generate_image_prompt(post)
        draft_state[chat_id] = {
            "draft": post,
            "title": topic,
            "track": track,
            "image_path": None,
            "video_url": None,
            "blog_article": None,
            "history": [
                {"role": "user", "content": f"LinkedIn post: {topic}"},
                {"role": "assistant", "content": post},
            ],
        }
        await update.message.reply_text(
            f"{post}\n\n———\n"
            "Copy and post to LinkedIn manually.\n"
            "Reply with feedback to revise · /cancel to discard\n\n"
            "_🖼 Generating LinkedIn image in background..._",
            parse_mode="Markdown",
        )
        asyncio.create_task(_generate_images_background(context, chat_id, img_prompt, topic))
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")


# ─────────────────────────────────────────────
#  /research
# ─────────────────────────────────────────────

@owner_only
async def cmd_research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Researching Xiaohongshu & Douyin trends... (~30 seconds)")
    try:
        if context.args:
            query = " ".join(context.args)
            result = research_with_kimi_search(query)
            await update.message.reply_text(f"🔍 Research: {query}\n\n{result}")
        else:
            report = research_trending_content(num_ideas=5)
            await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"Research failed: {e}")


# ─────────────────────────────────────────────
#  /approve
# ─────────────────────────────────────────────

@owner_only
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state = draft_state.get(chat_id)

    if not state or not state.get("draft"):
        await update.message.reply_text("No draft to approve. Use /draft to create one.")
        return

    await update.message.reply_text("Publishing...")

    title = state.get("title", "JinYi Update")
    track = state.get("track", "investor")

    # Use long-form blog article for website if available, otherwise use social post
    blog_content = state.get("blog_article") or state["draft"]

    results = publish_all(
        text=state["draft"],          # short social post → Facebook + Telegram
        blog_text=blog_content,       # long article → website blog
        title=title,
        track=track,
        telegram_channel=TELEGRAM_CHANNEL or None,
        image_path=state.get("image_path"),
        video_url=state.get("video_url"),
    )

    lines = [("✅" if ok else "❌") + f" {p.capitalize()}" for p, ok in results.items()]
    await update.message.reply_text("Published:\n" + "\n".join(lines))

    img_path = state.get("image_path")
    if img_path:
        Path(img_path).unlink(missing_ok=True)

    del draft_state[chat_id]

    # Send XHS + Douyin copy-paste blocks
    await update.message.reply_text(
        "Generating XHS + Douyin copy-paste blocks...", parse_mode="Markdown"
    )
    try:
        loop = asyncio.get_event_loop()
        blocks = await loop.run_in_executor(None, generate_copypaste_blocks, title, track)
        # Send in chunks if too long for one message
        if len(blocks) > 4000:
            mid = blocks.find("━━━━━━━━━━━━━━━━━━━━\n🎬")
            await update.message.reply_text(blocks[:mid], parse_mode="Markdown")
            await update.message.reply_text(blocks[mid:], parse_mode="Markdown")
        else:
            await update.message.reply_text(blocks, parse_mode="Markdown")
    except Exception as e:
        err = str(e)
        if "402" in err or "Insufficient Balance" in err:
            await update.message.reply_text(
                "⚠️ *DeepSeek out of credit* — copy-paste blocks skipped.\n"
                "Top up at: platform.deepseek.com",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Copy-paste blocks failed: {e}")


# ─────────────────────────────────────────────
#  /image
# ─────────────────────────────────────────────

@owner_only
async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in draft_state:
        await update.message.reply_text("No active draft. Create one first with /draft.")
        return

    if update.message.photo:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        await file.download_to_drive(tmp.name)
        draft_state[chat_id]["image_path"] = tmp.name
        await update.message.reply_text("Image attached. Use /approve to publish.")
    else:
        await update.message.reply_text("Send a photo with the /image command.")


# ─────────────────────────────────────────────
#  /cancel
# ─────────────────────────────────────────────

@owner_only
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in draft_state:
        del draft_state[chat_id]
        await update.message.reply_text("Draft discarded.")
    else:
        await update.message.reply_text("No active draft.")


# ─────────────────────────────────────────────
#  /status
# ─────────────────────────────────────────────

@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scheduler = context.bot_data.get("scheduler")
    if not scheduler:
        await update.message.reply_text("Scheduler not running.")
        return

    jobs = scheduler.get_jobs()
    lines = ["📅 *Scheduled Jobs:*\n"]
    for job in jobs:
        next_run = job.next_run_time
        t = next_run.strftime("%a %d %b, %I:%M %p MYT") if next_run else "N/A"
        lines.append(f"• *{job.name}* — {t}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  /bank
# ─────────────────────────────────────────────

@owner_only
async def cmd_bank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bank = load_dyk_bank()
    unused = count_unused_dyk(bank)
    total = len(bank)
    await update.message.reply_text(
        f"📚 *Did You Know Bank:* {unused}/{total} posts remaining\n\n"
        f"Sent Tue + Thu at 10am. At 2/week, ~{unused // 2} weeks of content left.",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  Text handler — revision loop / Tier 3 brief
# ─────────────────────────────────────────────

@owner_only
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    state = draft_state.get(chat_id)

    if state and state.get("draft"):
        await update.message.reply_text("Revising...")
        try:
            track = state.get("track", "investor")
            revised = revise_draft(state["draft"], text, state["history"], track=track)
            state["history"].append({"role": "user", "content": text})
            state["history"].append({"role": "assistant", "content": revised})
            if len(state["history"]) > 10:
                state["history"] = state["history"][-10:]
            state["draft"] = revised
            img_prompt = generate_image_prompt(revised)
            await update.message.reply_text(
                f"{revised}\n\n———\n"
                "Reply with more feedback · /approve · /cancel\n\n"
                f"🖼 *Image prompt:*\n`{img_prompt}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"Revision failed: {e}")
    else:
        await update.message.reply_text("Drafting from your brief...")
        try:
            draft = generate_tier2_draft(text)
            img_prompt = generate_image_prompt(draft)
            draft_state[chat_id] = {
                "draft": draft,
                "image_path": None,
                "history": [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": draft},
                ],
            }
            await update.message.reply_text(
                f"{draft}\n\n———\n"
                "Reply with feedback · /approve · /cancel\n\n"
                f"🖼 *Image prompt:*\n`{img_prompt}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"Draft failed: {e}")


# ─────────────────────────────────────────────
#  Voice handler — Tier 3
# ─────────────────────────────────────────────

@owner_only
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    Path(tmp_path).unlink(missing_ok=True)
    await update.message.reply_text(
        "Voice note received.\n\n"
        "Please reply with a short text summary of the key points "
        "and I'll draft the post from that."
    )


# ─────────────────────────────────────────────
#  Photo handler — Tier 3
# ─────────────────────────────────────────────

@owner_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""

    if not caption:
        await update.message.reply_text(
            "Photo received. Please resend it with a caption describing what it shows."
        )
        return

    await update.message.reply_text("Photo + caption received. Drafting post...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    await file.download_to_drive(tmp.name)

    try:
        draft = draft_from_photo_caption(caption)
        draft_state[chat_id] = {
            "draft": draft,
            "image_path": tmp.name,
            "history": [
                {"role": "user", "content": f"Photo caption: {caption}"},
                {"role": "assistant", "content": draft},
            ],
        }
        await update.message.reply_text(
            f"{draft}\n\n———\n"
            "Image attached. Reply with feedback · /approve · /cancel",
            parse_mode="Markdown",
        )
    except Exception as e:
        Path(tmp.name).unlink(missing_ok=True)
        await update.message.reply_text(f"Draft failed: {e}")


# ─────────────────────────────────────────────
#  Startup
# ─────────────────────────────────────────────

async def post_init(application: Application) -> None:
    bot: Bot = application.bot

    # Register command menu so "/" button works in Telegram
    await bot.set_my_commands(BOT_COMMANDS)
    # Also set for the owner specifically (shows in private chat menu)
    try:
        await bot.set_my_commands(
            BOT_COMMANDS,
            scope=BotCommandScopeChat(chat_id=OWNER_CHAT_ID),
        )
    except Exception:
        pass

    # Start scheduler
    scheduler = build_scheduler(bot)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started.")

    try:
        await bot.send_message(
            OWNER_CHAT_ID,
            "✅ *JinYi Content Bot online.*\n\nTap / to see all commands.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Could not send startup message: {e}")


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")
    if not OWNER_CHAT_ID:
        raise ValueError("OWNER_CHAT_ID not set")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("draft",    cmd_draft))
    app.add_handler(CommandHandler("xhs",      cmd_xhs))
    app.add_handler(CommandHandler("douyin",   cmd_douyin))
    app.add_handler(CommandHandler("video",    cmd_video))
    app.add_handler(CommandHandler("wechat",    cmd_wechat))
    app.add_handler(CommandHandler("linkedin",  cmd_linkedin))
    app.add_handler(CommandHandler("research",  cmd_research))
    app.add_handler(CommandHandler("approve",  cmd_approve))
    app.add_handler(CommandHandler("image",    cmd_image, filters=filters.PHOTO))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("bank",     cmd_bank))

    # Inline keyboard button handler
    app.add_handler(CallbackQueryHandler(handle_menu_callback, pattern="^menu:"))

    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting JinYi Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
