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
from telegram import Update, Bot, BotCommand, BotCommandScopeChat
from telegram.ext import (
    Application,
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
)
from publisher import publish_all
from scheduler import build_scheduler, load_dyk_bank, count_unused_dyk
from researcher import research_trending_content, research_with_kimi_search
from kling import submit_text_to_video, poll_video_result, download_video

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
    BotCommand("draft",    "Write a bilingual post (EN + ZH)"),
    BotCommand("xhs",      "Write a Xiaohongshu post"),
    BotCommand("douyin",   "Write Douyin script + generate video"),
    BotCommand("video",    "Generate a Kling video from a prompt"),
    BotCommand("wechat",   "Write a WeChat post"),
    BotCommand("research", "Research trending Xiaohongshu & Douyin topics"),
    BotCommand("approve",  "Publish current draft"),
    BotCommand("image",    "Attach image to current draft"),
    BotCommand("bank",     "Show Did You Know post bank count"),
    BotCommand("status",   "Show scheduled jobs"),
    BotCommand("cancel",   "Discard current draft"),
    BotCommand("start",    "Show all commands"),
]

TIER2_TOPICS = [
    "the health benefits of bird's nest for new mothers",
    "why Borneo swiftlet nests command a premium price",
    "what to look for when buying authentic bird's nest",
    "JinYi's 20+ years of expertise in Sabah and Sarawak",
    "the difference between white nest, red nest, and cave nest",
    "sustainable harvesting practices in swiftlet farming",
    "how to identify premium grade vs lower grade bird's nest",
    "investing in a swiftlet house: what you need to know",
    "the science behind bird's nest and skin health",
    "how climate affects nest production in Borneo",
]


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

@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *JinYi Content Bot*\n\n"
        "*Content creation:*\n"
        "/draft — Bilingual post (EN + ZH)\n"
        "/xhs — Xiaohongshu post\n"
        "/douyin — Douyin script + Kling video\n"
        "/video — Quick Kling video from prompt\n"
        "/wechat — WeChat post\n\n"
        "*Research:*\n"
        "/research — Trending topic ideas\n\n"
        "*Draft management:*\n"
        "/approve — Publish current draft\n"
        "/image — Attach image to draft\n"
        "/cancel — Discard draft\n\n"
        "*Automation:*\n"
        "/status — Scheduled jobs\n"
        "/bank — Did You Know post count\n\n"
        "Or just send a text, photo, or voice note and I'll draft a post.",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  /draft
# ─────────────────────────────────────────────

@owner_only
async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import random
    chat_id = update.effective_chat.id
    brief = " ".join(context.args) if context.args else random.choice(TIER2_TOPICS)

    await update.message.reply_text(f"Writing post about: _{brief}_...", parse_mode="Markdown")

    try:
        draft = generate_tier2_draft(brief)
        img_prompt = generate_image_prompt(draft)
        draft_state[chat_id] = {
            "draft": draft,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"Write a post about: {brief}"},
                {"role": "assistant", "content": draft},
            ],
        }
        await update.message.reply_text(
            f"{draft}\n\n———\n"
            "Reply with feedback to revise · /approve to publish · /cancel to discard\n\n"
            f"🖼 *Image prompt:*\n`{img_prompt}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Draft failed: {e}")


# ─────────────────────────────────────────────
#  /xhs
# ─────────────────────────────────────────────

@owner_only
async def cmd_xhs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    topic = " ".join(context.args) if context.args else "bird's nest health benefits — real experience"

    await update.message.reply_text(f"Writing Xiaohongshu post: _{topic}_...", parse_mode="Markdown")

    try:
        post = generate_xhs_post(topic)
        img_prompt = generate_image_prompt(post)
        draft_state[chat_id] = {
            "draft": post,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"Xiaohongshu topic: {topic}"},
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
        await update.message.reply_text(f"Failed: {e}")


# ─────────────────────────────────────────────
#  /douyin
# ─────────────────────────────────────────────

@owner_only
async def cmd_douyin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = list(context.args or [])

    # Optional duration as first arg: /douyin 10 topic...
    duration_sec = 5
    if args and args[0].isdigit():
        duration_sec = min(max(int(args.pop(0)), 5), 10)

    topic = " ".join(args) if args else "is swiftlet farming investment worth it"
    duration_label = f"{duration_sec}s"

    await update.message.reply_text(
        f"🎬 *Douyin pipeline starting*\n\n"
        f"Topic: _{topic}_\n"
        f"Steps: DeepSeek script → Kling {duration_label} video\n\n"
        "_This takes about 2–3 minutes..._",
        parse_mode="Markdown",
    )

    # Step 1 — Script
    try:
        script = generate_douyin_script(topic, f"{duration_sec} seconds")
    except Exception as e:
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
        "image_path": None,
        "history": [
            {"role": "user", "content": f"Douyin script: {topic}"},
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
    chat_id = update.effective_chat.id
    args = list(context.args or [])

    fmt = "moments"
    if args and args[0] in ("article", "moments"):
        fmt = args.pop(0)

    topic = " ".join(args) if args else "the unique advantage of Sabah swiftlet farming"
    label = "article" if fmt == "article" else "Moments post"

    await update.message.reply_text(f"Writing WeChat {label}: _{topic}_...", parse_mode="Markdown")

    try:
        post = generate_wechat_post(topic, fmt)
        draft_state[chat_id] = {
            "draft": post,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"WeChat {label}: {topic}"},
                {"role": "assistant", "content": post},
            ],
        }
        await update.message.reply_text(
            f"{post}\n\n———\nReply with feedback · /cancel to discard.",
            parse_mode="Markdown",
        )
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
            await update.message.reply_text(
                f"🔍 *Research: {query}*\n\n{result}",
                parse_mode="Markdown",
            )
        else:
            report = research_trending_content(num_ideas=5)
            await update.message.reply_text(report, parse_mode="Markdown")
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

    results = publish_all(
        text=state["draft"],
        telegram_channel=TELEGRAM_CHANNEL or None,
        image_path=state.get("image_path"),
    )

    lines = [("✅" if ok else "❌") + f" {p.capitalize()}" for p, ok in results.items()]
    await update.message.reply_text("Published:\n" + "\n".join(lines))

    img_path = state.get("image_path")
    if img_path:
        Path(img_path).unlink(missing_ok=True)

    del draft_state[chat_id]


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
            revised = revise_draft(state["draft"], text, state["history"])
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
    app.add_handler(CommandHandler("wechat",   cmd_wechat))
    app.add_handler(CommandHandler("research", cmd_research))
    app.add_handler(CommandHandler("approve",  cmd_approve))
    app.add_handler(CommandHandler("image",    cmd_image, filters=filters.PHOTO))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("bank",     cmd_bank))

    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting JinYi Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
