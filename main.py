"""
main.py — JinYi Telegram Content Bot
Phase 1 Steps 7–10: Tier 1 automation + Tier 2 approval flow + Tier 3 personal content

Commands:
  /approve  — publish current draft to all platforms
  /image    — attach an image to current draft
  /draft    — request a new Tier 2 draft
  /status   — show scheduled post queue
  /bank     — show DYK bank count
  /cancel   — cancel current draft

Tier 3 inputs (no command needed):
  - Voice note   → Claude transcribes → draft
  - Photo + caption → Claude writes post
  - Text message → Claude drafts post
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram import Update, Bot
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
    draft_from_voice_transcript,
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

# ── In-memory draft state per chat ───────────
# Stores: { chat_id: { "draft": str, "image_path": str|None, "history": list } }
draft_state: dict[int, dict] = {}

TIER2_BRIEF_TOPICS = [
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
    """Decorator — restrict handler to owner chat ID only."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_CHAT_ID:
            await update.message.reply_text("⛔ Authorised users only.")
            return
        return await func(update, context)
    return wrapper


# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────

@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *JinYi Content Bot online.*\n\n"
        "Commands:\n"
        "/draft — Bilingual post (Claude EN + DeepSeek ZH)\n"
        "/xhs [topic] — 小红书 post (DeepSeek)\n"
        "/douyin [topic] — Douyin script + Kling video\n"
        "/video [prompt] — Quick Kling video clip\n"
        "/wechat [topic] — WeChat post (DeepSeek)\n"
        "/research — 小红书 & Douyin trending ideas (Kimi)\n"
        "/approve — Publish current draft\n"
        "/image — Attach image to draft\n"
        "/status — Scheduled queue\n"
        "/bank — DYK bank count\n"
        "/cancel — Discard current draft\n\n"
        "Or just send me:\n"
        "• A *voice note* → I'll draft a post from it\n"
        "• A *photo with caption* → I'll write the post\n"
        "• A *text message* → I'll turn it into a draft",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  /draft — Tier 2: proactive draft request
# ─────────────────────────────────────────────

@owner_only
async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args

    # Use provided brief or pick a random topic
    if args:
        brief = " ".join(args)
    else:
        import random
        brief = random.choice(TIER2_BRIEF_TOPICS)

    await update.message.reply_text(f"✍️ Drafting post about: _{brief}_...", parse_mode="Markdown")

    try:
        draft = generate_tier2_draft(brief)
        draft_state[chat_id] = {
            "draft": draft,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"Write a post about: {brief}"},
                {"role": "assistant", "content": draft},
            ],
        }

        img_prompt = generate_image_prompt(draft)

        await update.message.reply_text(
            f"{draft}\n\n"
            "———\n"
            "Reply with feedback to revise, /approve to publish, or /cancel to discard.\n\n"
            f"🖼️ *Image prompt for Genspark:*\n`{img_prompt}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Draft generation failed: {e}")
        await update.message.reply_text(f"❌ Draft failed: {e}")


# ─────────────────────────────────────────────
#  /approve — publish current draft
# ─────────────────────────────────────────────

@owner_only
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state = draft_state.get(chat_id)

    if not state or not state.get("draft"):
        await update.message.reply_text("❌ No draft to approve. Use /draft to create one.")
        return

    await update.message.reply_text("📤 Publishing...")

    results = publish_all(
        text=state["draft"],
        telegram_channel=TELEGRAM_CHANNEL or None,
        image_path=state.get("image_path"),
    )

    summary_lines = []
    for platform, ok in results.items():
        icon = "✅" if ok else "❌"
        summary_lines.append(f"{icon} {platform.capitalize()}")

    await update.message.reply_text(
        "Published:\n" + "\n".join(summary_lines)
    )

    # Clean up image temp file if it exists
    img_path = state.get("image_path")
    if img_path and Path(img_path).exists():
        try:
            Path(img_path).unlink()
        except Exception:
            pass

    del draft_state[chat_id]


# ─────────────────────────────────────────────
#  /image — attach image to current draft
# ─────────────────────────────────────────────

@owner_only
async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in draft_state:
        await update.message.reply_text("❌ No active draft. Create one first with /draft.")
        return

    if update.message.photo:
        photo = update.message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        await file.download_to_drive(tmp.name)
        draft_state[chat_id]["image_path"] = tmp.name
        await update.message.reply_text("✅ Image attached. Use /approve to publish.")
    else:
        await update.message.reply_text("Please send an image with the /image caption.")


# ─────────────────────────────────────────────
#  /cancel
# ─────────────────────────────────────────────

@owner_only
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in draft_state:
        del draft_state[chat_id]
        await update.message.reply_text("🗑️ Draft discarded.")
    else:
        await update.message.reply_text("No active draft.")


# ─────────────────────────────────────────────
#  /status — show scheduled queue
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
        next_str = next_run.strftime("%a %d %b %Y, %I:%M %p MYT") if next_run else "N/A"
        lines.append(f"• *{job.name}* — next: {next_str}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  /xhs — 小红书 post (DeepSeek)
# ─────────────────────────────────────────────

@owner_only
async def cmd_xhs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    topic = " ".join(context.args) if context.args else "燕窝的功效与真实体验"
    await update.message.reply_text(f"📕 生成小红书帖子：_{topic}_...", parse_mode="Markdown")
    try:
        post = generate_xhs_post(topic)
        draft_state[chat_id] = {
            "draft": post,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"小红书帖子话题：{topic}"},
                {"role": "assistant", "content": post},
            ],
        }
        img_prompt = generate_image_prompt(post)
        await update.message.reply_text(
            f"{post}\n\n———\n"
            "回复反馈修改，/approve 发布，/cancel 放弃。\n\n"
            f"🖼️ *图片生成提示词:*\n`{img_prompt}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 生成失败: {e}")


# ─────────────────────────────────────────────
#  /douyin — Douyin script + Kling video generation
# ─────────────────────────────────────────────

@owner_only
async def cmd_douyin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import tempfile
    chat_id = update.effective_chat.id
    args = context.args or []

    # Parse duration flag: /douyin 5 topic... or /douyin topic...
    duration_sec = 5  # default 5s clip
    if args and args[0].isdigit():
        duration_sec = int(args.pop(0))
        duration_sec = min(max(duration_sec, 5), 10)  # Kling supports 5 or 10

    topic = " ".join(args) if args else "燕窝养殖投资值不值得"
    duration_label = f"{duration_sec}秒"

    await update.message.reply_text(
        f"🎬 正在生成抖音内容：_{topic}_\n\n"
        f"步骤：\n1️⃣ DeepSeek 写脚本\n2️⃣ Kling 生成视频 ({duration_label})\n\n_请稍候约2–3分钟..._",
        parse_mode="Markdown",
    )

    # Step 1: Generate script with DeepSeek
    try:
        script = generate_douyin_script(topic, duration_label)
    except Exception as e:
        await update.message.reply_text(f"❌ 脚本生成失败: {e}")
        return

    # Send script first so owner can read while video generates
    await update.message.reply_text(
        f"✅ *脚本已生成:*\n\n{script}\n\n_正在提交 Kling 生成视频..._",
        parse_mode="Markdown",
    )

    # Step 2: Build a concise visual prompt from the topic for Kling
    # Kling works best with descriptive visual prompts, not full scripts
    visual_prompt = (
        f"Premium bird's nest swiftlet farming in Sabah Borneo Malaysia. "
        f"Topic: {topic}. "
        f"Cinematic vertical video 9:16, warm golden tones, lush tropical forest, "
        f"professional documentary style, no text overlay."
    )

    # Step 3: Submit to Kling and poll
    try:
        task_id = submit_text_to_video(
            prompt=visual_prompt,
            duration=duration_sec,
            aspect_ratio="9:16",
            model="kling-v1-6",
            mode="std",
        )
        await update.message.reply_text(f"📤 Kling 任务已提交 (ID: `{task_id}`)\n_等待视频生成..._", parse_mode="Markdown")

        # Poll in background — run blocking poll in thread executor
        import asyncio
        loop = asyncio.get_event_loop()
        video_url = await loop.run_in_executor(None, poll_video_result, task_id)

        # Download video
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await loop.run_in_executor(None, download_video, video_url, tmp_path)

        # Send video to Telegram
        with open(tmp_path, "rb") as vf:
            await context.bot.send_video(
                chat_id=chat_id,
                video=vf,
                caption=f"🎬 *{topic}*\n\n脚本已附上，手动发布至抖音。",
                parse_mode="Markdown",
            )

        # Clean up
        Path(tmp_path).unlink(missing_ok=True)

        # Save script as draft for revision
        draft_state[chat_id] = {
            "draft": script,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"抖音脚本话题：{topic}"},
                {"role": "assistant", "content": script},
            ],
        }
        await update.message.reply_text("✅ 视频已发送。回复反馈可修改脚本，/cancel 放弃。")

    except Exception as e:
        logger.error(f"Kling video generation failed: {e}")
        await update.message.reply_text(
            f"⚠️ 视频生成失败: {e}\n\n脚本已保存，您可以手动录制。",
        )
        # Still save the script as draft
        draft_state[chat_id] = {
            "draft": script,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"抖音脚本话题：{topic}"},
                {"role": "assistant", "content": script},
            ],
        }


# ─────────────────────────────────────────────
#  /video — Quick Kling video from a prompt
# ─────────────────────────────────────────────

@owner_only
async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import tempfile, asyncio
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "Usage: `/video [prompt]`\nExample: `/video swiftlet birds flying into nest house at sunset borneo`",
            parse_mode="Markdown",
        )
        return

    prompt = " ".join(context.args)
    await update.message.reply_text(f"🎬 Generating video...\n`{prompt}`\n\n_~2–3 minutes_", parse_mode="Markdown")

    try:
        task_id = submit_text_to_video(prompt=prompt, duration=5, aspect_ratio="9:16")
        loop = asyncio.get_event_loop()
        video_url = await loop.run_in_executor(None, poll_video_result, task_id)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await loop.run_in_executor(None, download_video, video_url, tmp_path)

        with open(tmp_path, "rb") as vf:
            await context.bot.send_video(chat_id=chat_id, video=vf, caption=f"🎬 `{prompt}`", parse_mode="Markdown")

        Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Video generation failed: {e}")


# ─────────────────────────────────────────────
#  /wechat — WeChat post (DeepSeek)
# ─────────────────────────────────────────────

@owner_only
async def cmd_wechat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []
    # format: /wechat [article|moments] topic...
    fmt = "moments"
    if args and args[0] in ("article", "moments"):
        fmt = args.pop(0)
    topic = " ".join(args) if args else "沙巴燕屋养殖的独特优势"
    label = "公众号文章" if fmt == "article" else "朋友圈"
    await update.message.reply_text(f"💬 生成微信{label}：_{topic}_...", parse_mode="Markdown")
    try:
        post = generate_wechat_post(topic, fmt)
        draft_state[chat_id] = {
            "draft": post,
            "image_path": None,
            "history": [
                {"role": "user", "content": f"微信{label}话题：{topic}"},
                {"role": "assistant", "content": post},
            ],
        }
        await update.message.reply_text(
            f"{post}\n\n———\n"
            "回复反馈修改，/cancel 放弃。",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 生成失败: {e}")


# ─────────────────────────────────────────────
#  /research — on-demand 小红书 / Douyin research
# ─────────────────────────────────────────────

@owner_only
async def cmd_research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    await update.message.reply_text(
        "🔍 Researching 小红书 & Douyin trends... (takes ~30 seconds)"
    )
    try:
        if args:
            # Targeted search on a specific topic
            query = " ".join(args)
            result = research_with_kimi_search(query)
            await update.message.reply_text(
                f"🔍 *Research: {query}*\n\n{result}",
                parse_mode="Markdown",
            )
        else:
            # Full weekly report — 5 ideas
            report = research_trending_content(num_ideas=5)
            await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Research failed: {e}")


# ─────────────────────────────────────────────
#  /bank — show DYK bank count
# ─────────────────────────────────────────────

@owner_only
async def cmd_bank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bank = load_dyk_bank()
    unused = count_unused_dyk(bank)
    total = len(bank)
    await update.message.reply_text(
        f"📚 *DYK Bank:* {unused}/{total} unused posts remaining.\n\n"
        "Posts are sent Tue + Thu at 10am. "
        f"At 2 posts/week, current bank covers ~{unused // 2} weeks.",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  Text message handler — Tier 2 revision / Tier 3 brief
# ─────────────────────────────────────────────

@owner_only
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    state = draft_state.get(chat_id)

    if state and state.get("draft"):
        # In revision loop — treat message as feedback
        await update.message.reply_text("✏️ Revising...")
        try:
            revised = revise_draft(state["draft"], text, state["history"])
            state["history"].append({"role": "user", "content": text})
            state["history"].append({"role": "assistant", "content": revised})
            # Keep history to last 10 messages
            if len(state["history"]) > 10:
                state["history"] = state["history"][-10:]
            state["draft"] = revised

            img_prompt = generate_image_prompt(revised)

            await update.message.reply_text(
                f"{revised}\n\n"
                "———\n"
                "Reply with more feedback, /approve to publish, or /cancel to discard.\n\n"
                f"🖼️ *Updated image prompt:*\n`{img_prompt}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Revision failed: {e}")
    else:
        # No active draft — treat as Tier 3 text brief
        await update.message.reply_text("✍️ Drafting from your brief...")
        try:
            draft = generate_tier2_draft(text)
            draft_state[chat_id] = {
                "draft": draft,
                "image_path": None,
                "history": [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": draft},
                ],
            }
            img_prompt = generate_image_prompt(draft)
            await update.message.reply_text(
                f"{draft}\n\n"
                "———\n"
                "Reply with feedback to revise, /approve to publish, or /cancel to discard.\n\n"
                f"🖼️ *Image prompt:*\n`{img_prompt}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Draft failed: {e}")


# ─────────────────────────────────────────────
#  Voice note handler — Tier 3
# ─────────────────────────────────────────────

@owner_only
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text("🎙️ Voice note received. Transcribing and drafting...")

    # Download voice file
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    try:
        # Use Anthropic to draft from voice note description
        # (Direct audio transcription would require Whisper/another service)
        # For now, ask owner to include a caption with key points
        await update.message.reply_text(
            "Voice note downloaded ✅\n\n"
            "Please reply with a text summary of the key points from your voice note "
            "and I'll draft the post from that. "
            "(Full audio transcription coming in a future update.)"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────
#  Photo handler — Tier 3
# ─────────────────────────────────────────────

@owner_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    caption = update.message.caption or ""

    if not caption:
        await update.message.reply_text(
            "📸 Photo received! Please resend it with a caption describing what it shows, "
            "and I'll write the full post."
        )
        return

    await update.message.reply_text("📸 Photo + caption received. Drafting post...")

    # Save image for potential use in the draft
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
            f"{draft}\n\n"
            "———\n"
            "Image attached ✅ Reply with feedback to revise, /approve to publish, or /cancel.",
            parse_mode="Markdown",
        )
    except Exception as e:
        Path(tmp.name).unlink(missing_ok=True)
        await update.message.reply_text(f"❌ Draft failed: {e}")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

async def post_init(application: Application) -> None:
    """Run after the bot starts — start scheduler and generate holidays if needed."""
    bot: Bot = application.bot
    scheduler = build_scheduler(bot)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started.")

    # Notify owner
    try:
        await bot.send_message(
            OWNER_CHAT_ID,
            "✅ *JinYi Content Bot is online.*\n\n"
            "Scheduler running. Use /status to see next scheduled posts.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Could not send startup message: {e}")


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")
    if not OWNER_CHAT_ID:
        raise ValueError("OWNER_CHAT_ID not set in .env")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("draft",    cmd_draft))
    app.add_handler(CommandHandler("approve",  cmd_approve))
    app.add_handler(CommandHandler("image",    cmd_image, filters=filters.PHOTO))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("bank",     cmd_bank))
    app.add_handler(CommandHandler("research", cmd_research))
    app.add_handler(CommandHandler("xhs",      cmd_xhs))
    app.add_handler(CommandHandler("douyin",   cmd_douyin))
    app.add_handler(CommandHandler("wechat",   cmd_wechat))
    app.add_handler(CommandHandler("video",    cmd_video))

    # Media handlers (Tier 3)
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting JinYi Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
