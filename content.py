"""
content.py — Multi-model content generation for JinYi Telegram Bot

Model routing:
  - Claude (Anthropic)  → EN content, image prompts, bilingual digests
  - DeepSeek            → ZH-primary content (小红书, Douyin, WeChat), ZH revision
  - Used together       → Bilingual posts: Claude writes EN, DeepSeek writes ZH
"""

import anthropic
import logging
import os
from openai import OpenAI

logger = logging.getLogger(__name__)

# ── Clients ──────────────────────────────────
claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

deepseek = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# ── System prompts ────────────────────────────

CLAUDE_SYSTEM = """You are the English content writer for JinYi Group, a premium swiftlet farming
company in Sabah and Sarawak, Malaysian Borneo.

Brand voice:
- Professional, trustworthy, premium
- Warm but not overly casual
- Educational — teach the audience, don't just sell
- No excessive exclamation marks or hype language

When writing bilingual posts:
- Write the English section only
- 80–120 words
- Start with a relevant emoji
- End with hashtags including #JinYiGroup
"""

DEEPSEEK_SYSTEM = """你是锦益集团（JinYi Group）的中文内容创作者。锦益集团是马来西亚婆罗洲沙巴和砂拉越的顶级燕窝养殖企业。

品牌调性：
- 专业、可信、高端
- 亲切但不过于随意
- 教育性强——教育受众，而非单纯推销
- 避免过多感叹号或浮夸措辞
- 语言自然流畅，符合中国社交媒体习惯

写作规则：
- 只写中文部分
- 字数：150–250字
- 开头使用相关emoji
- 结尾附上话题标签，包含 #锦益集团
- 针对平台优化：小红书用温暖个人化语气，抖音用故事感强的钩子句，微信用深度和价值感
"""

DEEPSEEK_XHS_SYSTEM = """你是小红书爆款内容创作者，专注燕窝和健康养生领域。

写作风格：
- 第一人称，真实体验感
- 开头必须是强力钩子（引发好奇或共鸣）
- 多用换行，每段1-2句，视觉清爽
- 适量使用emoji点缀
- 结尾引导互动（提问或邀请评论）
- 标题党风格的标题（但不失真）
- 字数：300–500字

你代表锦益集团，但写作时要像真实用户分享，而非品牌广告。
"""

DEEPSEEK_DOUYIN_SYSTEM = """你是抖音爆款文案创作者，专注燕窝和燕屋养殖投资内容。

视频脚本格式：
- 开头3秒钩子（让人停下来看的第一句话）
- 视频时长：15–60秒
- 结构：钩子 → 核心内容 → 行动号召
- 语言口语化，适合真人出镜朗读
- 每个场景附上拍摄建议
- 结尾必须有明确的行动号召

你代表锦益集团，风格真实、有教育价值、不过度销售。
"""


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _deepseek(system: str, user: str, max_tokens: int = 1024) -> str:
    response = deepseek.chat.completions.create(
        model="deepseek-chat",
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content


def _claude(system: str, messages: list[dict], max_tokens: int = 1024) -> str:
    response = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text


# ─────────────────────────────────────────────
#  Bilingual posts (Claude EN + DeepSeek ZH)
# ─────────────────────────────────────────────

def generate_bilingual_post(brief: str) -> str:
    """
    Generate a full bilingual post.
    Claude writes English, DeepSeek writes Chinese. Combined into one post.
    """
    # English — Claude
    en_text = _claude(
        CLAUDE_SYSTEM,
        [{"role": "user", "content": f"Write an English social media post about: {brief}"}],
    )

    # Chinese — DeepSeek
    zh_text = _deepseek(
        DEEPSEEK_SYSTEM,
        f"写一篇关于以下话题的中文社交媒体帖子：{brief}",
    )

    return f"{en_text}\n\n———\n\n{zh_text}"


def generate_tier2_draft(brief: str, history: list[dict] | None = None) -> str:
    """Generate a Tier 2 draft. Uses bilingual model split."""
    return generate_bilingual_post(brief)


def revise_draft(original_draft: str, feedback: str, history: list[dict]) -> str:
    """Revise a draft. Uses Claude for full revision with context."""
    messages = history.copy()
    messages.append({
        "role": "user",
        "content": (
            f"Revise the previous draft based on this feedback: {feedback}\n\n"
            "Keep bilingual format (EN + ZH separated by ———). Maintain brand voice."
        ),
    })
    return _claude(CLAUDE_SYSTEM, messages)


def generate_weekly_digest() -> str:
    """Weekly industry digest — Claude for EN, DeepSeek for ZH."""
    prompt = (
        "Write a 'Weekly Industry Digest' about bird's nest / swiftlet farming industry trends. "
        "Informative, useful for investors and enthusiasts. 150–200 words English."
    )
    en = _claude(CLAUDE_SYSTEM, [{"role": "user", "content": prompt}])
    zh = _deepseek(
        DEEPSEEK_SYSTEM,
        "写一篇本周燕窝和燕屋养殖行业动态的周报帖子。信息丰富，适合投资者和爱好者。200–300字。",
    )
    return f"{en}\n\n———\n\n{zh}"


def draft_from_voice_transcript(transcript: str) -> str:
    """Tier 3: voice note → bilingual post."""
    return generate_bilingual_post(f"owner voice note: {transcript}")


def draft_from_photo_caption(caption: str) -> str:
    """Tier 3: photo + caption → bilingual post."""
    return generate_bilingual_post(f"photo caption: {caption}")


def generate_holiday_greeting(holiday_name: str, holiday_name_zh: str) -> str:
    """Pre-generate holiday greeting. Claude EN + DeepSeek ZH."""
    en = _claude(
        CLAUDE_SYSTEM,
        [{"role": "user", "content": f"Write a warm holiday greeting for {holiday_name} from JinYi Group. Sincere, premium, 60–80 words."}],
    )
    zh = _deepseek(
        DEEPSEEK_SYSTEM,
        f"为{holiday_name_zh}写一篇锦益集团的节日祝福帖子。真诚、高端、100–150字。",
    )
    return f"{en}\n\n———\n\n{zh}"


def generate_image_prompt(post_text: str) -> str:
    """Generate an image generation prompt for Genspark/NanoBanana."""
    return _claude(
        "You are an art director. Write concise image generation prompts.",
        [{
            "role": "user",
            "content": (
                "Write an image generation prompt for this post. "
                "Premium, photorealistic, dark/moody luxury aesthetic for a Malaysian bird's nest brand. No text in image.\n\n"
                f"Post:\n{post_text}\n\nReturn ONLY the prompt, no explanation."
            ),
        }],
        max_tokens=150,
    )


# ─────────────────────────────────────────────
#  Platform-specific: 小红书
# ─────────────────────────────────────────────

def generate_xhs_post(topic: str, research_angle: str = "") -> str:
    """
    Generate a 小红书-optimised post in DeepSeek.
    topic: what to write about
    research_angle: optional angle from /research output
    """
    angle_note = f"\n参考角度：{research_angle}" if research_angle else ""
    return _deepseek(
        DEEPSEEK_XHS_SYSTEM,
        f"话题：{topic}{angle_note}\n\n写一篇小红书爆款帖子，附上标题和正文。",
        max_tokens=1024,
    )


# ─────────────────────────────────────────────
#  Platform-specific: Douyin video script
# ─────────────────────────────────────────────

def generate_douyin_script(topic: str, duration: str = "30秒", research_angle: str = "") -> str:
    """
    Generate a Douyin video script.
    topic: video topic
    duration: target video length
    research_angle: optional trending angle from /research
    """
    angle_note = f"\n参考热门角度：{research_angle}" if research_angle else ""
    return _deepseek(
        DEEPSEEK_DOUYIN_SYSTEM,
        (
            f"话题：{topic}\n"
            f"目标时长：{duration}\n"
            f"{angle_note}\n\n"
            "请提供：\n"
            "1. 视频标题（抖音风格）\n"
            "2. 完整脚本（含旁白+画面提示）\n"
            "3. 推荐BGM风格\n"
            "4. 封面文案建议"
        ),
        max_tokens=1200,
    )


# ─────────────────────────────────────────────
#  Platform-specific: WeChat
# ─────────────────────────────────────────────

def generate_wechat_post(topic: str, format_type: str = "moments") -> str:
    """
    Generate WeChat content.
    format_type: "moments" (short) or "article" (long-form)
    """
    if format_type == "article":
        prompt = (
            f"为微信公众号写一篇关于「{topic}」的深度文章。\n"
            "格式：标题 + 导语 + 3-5个小节 + 结尾行动号召\n"
            "字数：800–1200字\n"
            "风格：专业、有深度、有价值感，适合微信生态"
        )
    else:
        prompt = (
            f"为微信朋友圈写一条关于「{topic}」的帖子。\n"
            "字数：100–200字\n"
            "风格：个人化、真实、有温度，适合老板或创始人发朋友圈"
        )

    return _deepseek(DEEPSEEK_SYSTEM, prompt, max_tokens=1500)
