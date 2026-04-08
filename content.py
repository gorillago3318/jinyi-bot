"""
content.py — Multi-model content generation for JinYi Telegram Bot

Two content tracks:
  investor  → HNW audience, asset management tone, data-driven, no lifestyle language
  consumer  → Health-conscious buyers, warm expert tone, recipes/quality/preparation

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

# ── INVESTOR TRACK ──
CLAUDE_SYSTEM_INVESTOR = """You are the content strategist for JinYi Group — a regulated swiftlet farming asset manager
with 20+ years of operations across 36+ locations in Sabah and Sarawak, Malaysian Borneo.

Your audience: High-net-worth individuals (RM 500k–2M investable assets), business owners,
family offices. They are comparing JinYi against fixed deposits, REITs, and property.

Brand voice:
- Authoritative, precise, measured
- Speak like a fund manager or senior partner — not a salesperson
- Data and specifics over adjectives
- Acknowledge risk honestly — it builds trust
- Never use hype, exclamation marks, or lifestyle language

Content rules:
- Lead with the business/investment angle, not bird's nest
- Bird's nest is the commodity output, not the story
- The story is: asset ownership, managed yield, regulated supply chain, proven track record
- 100–150 words English
- Start with a sharp observation or data point, not an emoji
- End with hashtags: #SwiftletInvestment #JinYiGroup #AlternativeAssets
"""

DEEPSEEK_INVESTOR_SYSTEM = """你是锦益集团（JinYi Group）的投资者关系内容创作者。
锦益集团是马来西亚婆罗洲沙巴和砂拉越拥有20年以上运营经验的专业燕窝农场资产管理公司，管理逾36个活跃点位。

目标受众：高净值个人投资者（可投资资产50万至200万令吉以上）、企业主、家族办公室。
他们正在比较锦益与定存、房产、REITs等投资标的。

写作调性：
- 专业、精准、有权威感——像基金经理或资深合伙人，而非销售员
- 用数据和具体事实说话，避免形容词堆砌
- 诚实披露风险——这反而建立信任
- 绝不使用浮夸语言或感叹号
- 燕窝是商品产出，不是核心叙事；核心是资产所有权、受监管的供应链、经过验证的回报

写作规则：
- 只写中文部分，150–250字
- 以数据或犀利观察开头，不用emoji开头
- 结尾附话题标签：#燕屋投资 #锦益集团 #另类资产
- 最后附英文摘要（3-4句），标注「English Summary:」供品牌主审阅
"""

# ── CONSUMER / LIFESTYLE TRACK ──
CLAUDE_SYSTEM_CONSUMER = """You are the content writer for JinYi Group, a premium swiftlet farming company
in Sabah and Sarawak, Malaysian Borneo.

Your audience: Health-conscious consumers, bird's nest buyers, food enthusiasts,
homemakers. They care about quality, authenticity, and how to use bird's nest.

Brand voice:
- Warm, credible, educational
- Expert but approachable — like a trusted specialist, not an influencer
- Specific and honest — real information, not vague health claims
- No excessive exclamation marks

Content rules:
- 80–120 words English
- Start with a relevant emoji
- Topics: recipes, preparation tips, quality grading, cave vs house nest,
  how to identify authentic nests, storage, serving suggestions
- End with hashtags: #BirdsNest #JinYiGroup #SwiftletFarming
"""

DEEPSEEK_CONSUMER_SYSTEM = """你是锦益集团（JinYi Group）的消费者内容创作者。
锦益集团是马来西亚婆罗洲沙巴和砂拉越的顶级燕窝养殖企业。

目标受众：注重健康的消费者、燕窝购买者、美食爱好者。
他们关心品质、真伪鉴别和燕窝的正确使用方式。

写作调性：
- 温暖、专业、有教育价值
- 像专业顾问，不像网红博主
- 提供真实具体的信息，不做模糊的健康声称
- 不使用过多感叹号

写作规则：
- 只写中文部分，150–250字
- 话题：食谱、泡发技巧、品级鉴别、洞燕vs屋燕、真伪辨别、储存方式
- 开头使用相关emoji
- 结尾附话题标签：#燕窝 #锦益集团 #燕窝功效
- 最后附英文摘要（3-4句），标注「English Summary:」供品牌主审阅
"""

# ── XHS TRACK ──
DEEPSEEK_XHS_INVESTOR_SYSTEM = """你是小红书财经/投资类内容创作者，专注另类资产和燕屋养殖投资。

目标受众：有闲钱想找好投资的高净值人群，正在对比各类资产配置方案。

写作风格：
- 以数据或反常识观点开头（钩子）
- 理性分析为主，有温度但不煽情
- 每段2-3句，逻辑清晰
- 适度使用emoji，不堆砌
- 结尾引导留言：提出一个有深度的问题
- 字数：300–400字

重要：内容用中文创作，最后附「English Summary:」（3-4句英文）。
"""

DEEPSEEK_XHS_CONSUMER_SYSTEM = """你是小红书生活方式内容创作者，专注燕窝健康养生和美食。

目标受众：注重健康、有品质生活追求的消费者。

写作风格：
- 实用干货为主，真实可信
- 开头直接给价值（不绕弯子）
- 多用换行，视觉清爽
- 适量emoji
- 结尾引导互动
- 字数：250–400字
- 内容：食谱、泡发、品级、洞燕vs屋燕、辨别真假

重要：内容用中文创作，最后附「English Summary:」（3-4句英文）。
"""

# ── DOUYIN TRACK ──
DEEPSEEK_DOUYIN_INVESTOR_SYSTEM = """你是抖音财经/投资类内容创作者，专注燕屋养殖投资。

视频脚本格式：
- 开头3秒：用数据或反常识钩子（不是情感煽动）
- 时长：30–60秒
- 结构：钩子 → 核心论点 → 数据支撑 → 行动号召
- 语言专业但口语化，适合真人出镜
- 每个段落附拍摄建议
- 结尾：明确引导私信或留言

重要：脚本用中文，最后附「English Summary:」（3-4句英文）。
"""

DEEPSEEK_DOUYIN_CONSUMER_SYSTEM = """你是抖音生活方式/美食内容创作者，专注燕窝养生。

视频脚本格式：
- 开头3秒：实用钩子（"教你一招" / "99%的人不知道"类型）
- 时长：15–30秒
- 结构：钩子 → 核心干货 → 品牌植入（自然）→ 行动号召
- 语言轻松口语，适合真人出镜或图文
- 每个段落附拍摄建议

重要：脚本用中文，最后附「English Summary:」（3-4句英文）。
"""


# ─────────────────────────────────────────────
#  Track helpers
# ─────────────────────────────────────────────

def _resolve_track(track: str) -> str:
    """Normalise track name. Accepts 'i'/'inv' → 'investor', 'c'/'con' → 'consumer'."""
    t = track.lower().strip()
    if t in ("investor", "inv", "i", "invest"):
        return "investor"
    if t in ("consumer", "con", "c", "lifestyle", "life"):
        return "consumer"
    return "investor"  # default


def _claude_system(track: str) -> str:
    return CLAUDE_SYSTEM_INVESTOR if _resolve_track(track) == "investor" else CLAUDE_SYSTEM_CONSUMER


def _deepseek_system(track: str) -> str:
    return DEEPSEEK_INVESTOR_SYSTEM if _resolve_track(track) == "investor" else DEEPSEEK_CONSUMER_SYSTEM


def _xhs_system(track: str) -> str:
    return DEEPSEEK_XHS_INVESTOR_SYSTEM if _resolve_track(track) == "investor" else DEEPSEEK_XHS_CONSUMER_SYSTEM


def _douyin_system(track: str) -> str:
    return DEEPSEEK_DOUYIN_INVESTOR_SYSTEM if _resolve_track(track) == "investor" else DEEPSEEK_DOUYIN_CONSUMER_SYSTEM


# ─────────────────────────────────────────────
#  Low-level model callers
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
    if not response.choices or not response.choices[0].message.content:
        raise ValueError("DeepSeek returned an empty response")
    return response.choices[0].message.content


def _claude(system: str, messages: list[dict], max_tokens: int = 1024) -> str:
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    if not response.content or not hasattr(response.content[0], "text"):
        raise ValueError("Claude returned an empty response")
    return response.content[0].text


# ─────────────────────────────────────────────
#  Blog article (long-form, website only)
# ─────────────────────────────────────────────

CLAUDE_BLOG_INVESTOR = """You are a senior investment writer for JinYi Group — a regulated swiftlet farming
asset manager with 20+ years of operations across 36+ locations in Sabah and Sarawak, Malaysian Borneo.

Write long-form blog articles for the company website. Audience: high-net-worth individuals
comparing swiftlet farming against fixed deposits, REITs, and property.

Rules:
- 600–800 words
- Professional, data-driven, no hype
- Structure: sharp opening observation → context/market data → JinYi's position →
  how it works → risks (honest) → who it's for → closing thought
- Use subheadings (##) to break up sections
- Write in first-person plural ("We operate...", "Our investors...")
- End with a soft call to action: "Speak with our team"
- No hashtags in the article body
"""

CLAUDE_BLOG_CONSUMER = """You are a content writer for JinYi Group, a premium swiftlet farming company
in Sabah and Sarawak, Malaysian Borneo.

Write long-form educational blog articles for health-conscious consumers and bird's nest buyers.

Rules:
- 600–800 words
- Warm, credible, educational — like a trusted specialist
- Structure: engaging opening → background/context → the key information →
  practical tips or guidance → JinYi's approach → closing recommendation
- Use subheadings (##) to break up sections
- Specific and honest — real information, not vague health claims
- End with an invitation to learn more or try their products
- No hashtags in the article body
"""


def generate_blog_article(topic: str, track: str = "investor") -> str:
    """
    Generate a long-form blog article (600–800 words) for the website.
    Uses Claude only — no bilingual split (website shows EN with ZH section below).
    """
    system = CLAUDE_BLOG_INVESTOR if _resolve_track(track) == "investor" else CLAUDE_BLOG_CONSUMER
    return _claude(
        system,
        [{"role": "user", "content": f"Write a blog article about: {topic}"}],
        max_tokens=2000,
    )


def generate_linkedin_post(topic: str, track: str = "investor") -> str:
    """
    Generate a LinkedIn post — professional thought leadership tone.
    English only. 150–200 words. No hashtag spam (max 3).
    """
    system = """You are writing LinkedIn posts for Mak Wai Kit, CEO of JinYi Group —
a regulated swiftlet farming asset manager in Sabah and Sarawak, Malaysian Borneo.
20+ years operations, 36+ locations, RM2.99M raised via equity crowdfunding.

LinkedIn tone rules:
- First-person ("I've observed...", "We recently...")
- Thought leadership — share a genuine insight, not a sales pitch
- Data point or counter-intuitive observation to open
- 150–200 words maximum
- Short paragraphs, one idea per paragraph
- End with a genuine question to spark discussion
- Max 3 hashtags, professional ones only (#AlternativeAssets #SwiftletFarming #Investing)
- Never sound like an ad
- Authoritative but human — the voice of an experienced founder/operator
"""
    return _claude(
        system,
        [{"role": "user", "content": f"Write a LinkedIn post about: {topic}"}],
        max_tokens=600,
    )


def generate_copypaste_blocks(topic: str, track: str = "investor") -> str:
    """
    Generate ready-to-copy XHS post + Douyin script for manual posting.
    Returns a formatted string with both blocks.
    """
    xhs = generate_xhs_post(topic, track=track)
    douyin = generate_douyin_script(topic, "30秒", track=track)

    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📕 *小红书 Copy-Paste*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{xhs}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎬 *抖音 Script*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{douyin}"
    )


# ─────────────────────────────────────────────
#  Bilingual posts (Claude EN + DeepSeek ZH)
# ─────────────────────────────────────────────

def generate_bilingual_post(brief: str, track: str = "investor") -> str:
    """
    Generate a full bilingual post.
    Claude writes English, DeepSeek writes Chinese. Combined into one post.

    track: "investor" (default) or "consumer"
    """
    claude_sys = _claude_system(track)
    deepseek_sys = _deepseek_system(track)

    # English — Claude
    en_text = _claude(
        claude_sys,
        [{"role": "user", "content": f"Write an English social media post about: {brief}"}],
    )

    # Chinese — DeepSeek
    zh_text = _deepseek(
        deepseek_sys,
        f"写一篇关于以下话题的中文社交媒体帖子：{brief}",
    )

    return f"{en_text}\n\n———\n\n{zh_text}"


def generate_tier2_draft(brief: str, track: str = "investor", history: list[dict] | None = None) -> str:
    """Generate a Tier 2 draft. Uses bilingual model split."""
    return generate_bilingual_post(brief, track=track)


def revise_draft(original_draft: str, feedback: str, history: list[dict], track: str = "investor") -> str:
    """Revise a draft. Uses Claude for full revision with context."""
    messages = history.copy()
    messages.append({
        "role": "user",
        "content": (
            f"Revise the previous draft based on this feedback: {feedback}\n\n"
            "Keep bilingual format (EN + ZH separated by ———). Maintain brand voice."
        ),
    })
    return _claude(_claude_system(track), messages)


def generate_weekly_digest() -> str:
    """Weekly industry digest — investor track by default (Claude EN + DeepSeek ZH)."""
    prompt = (
        "Write a 'Weekly Industry Digest' for swiftlet farming investors. "
        "Cover: industry trends, commodity pricing context, regulatory updates, or operational insights. "
        "Informative, data-driven, useful for HNW investors. 150–200 words English."
    )
    en = _claude(CLAUDE_SYSTEM_INVESTOR, [{"role": "user", "content": prompt}])
    zh = _deepseek(
        DEEPSEEK_INVESTOR_SYSTEM,
        "写一篇本周燕屋养殖行业投资动态的周报帖子。面向高净值投资者，信息准确、数据支撑。200–300字。",
    )
    return f"{en}\n\n———\n\n{zh}"


def draft_from_voice_transcript(transcript: str, track: str = "investor") -> str:
    """Tier 3: voice note → bilingual post."""
    return generate_bilingual_post(f"owner voice note: {transcript}", track=track)


def draft_from_photo_caption(caption: str, track: str = "investor") -> str:
    """Tier 3: photo + caption → bilingual post."""
    return generate_bilingual_post(f"photo caption: {caption}", track=track)


def generate_holiday_greeting(holiday_name: str, holiday_name_zh: str) -> str:
    """Pre-generate holiday greeting. Claude EN + DeepSeek ZH."""
    en = _claude(
        CLAUDE_SYSTEM_INVESTOR,
        [{"role": "user", "content": f"Write a warm holiday greeting for {holiday_name} from JinYi Group. Sincere, premium, 60–80 words. Keep brand voice — no hype or exclamation marks."}],
    )
    zh = _deepseek(
        DEEPSEEK_INVESTOR_SYSTEM,
        f"为{holiday_name_zh}写一篇锦益集团的节日祝福帖子。真诚、高端、100–150字。",
    )
    return f"{en}\n\n———\n\n{zh}"


SWIFTLET_VISUAL_KNOWLEDGE = """
You are an expert art director for JinYi Borneo Harvest, a premium Malaysian swiftlet farming and edible bird's nest brand based in Sabah, Borneo.

You have deep knowledge of how swiftlet farming looks. Use this knowledge when writing image prompts:

SWIFTLET FARM BUILDINGS:
- Low-rise 2 to 4 storey plain rectangular concrete or brick buildings — NOT apartments, NOT offices, NOT towers
- Facade has rows of small circular or rectangular bird ENTRY HOLES (10–15 cm wide), not glass windows
- Buildings are standalone, surrounded by tropical jungle, palm trees, or rural Sabah landscape
- Exterior is plain unpainted or whitewashed concrete, often with a simple rooftop parapet
- Swiftlets (tiny dark birds resembling swallows) fly in large swarms around the building at dusk and dawn
- Interior: dark, humid rooms with long horizontal wooden planks/beams lining the walls and ceiling where nests are built

BIRD'S NEST (EDIBLE):
- Raw harvested nest: white or cream-coloured, cup or crescent-shaped, made of interlaced translucent saliva strands
- Delicate fibrous lattice structure, roughly 5–8 cm wide, very lightweight
- Grades: white (Grade A), yellow, and rare "blood nest" (red-tinged, highest grade)
- Soaked nest: expands to translucent, jelly-like, pale ivory strands floating in water
- Bird's nest soup: served in porcelain bowl with amber/golden broth, translucent strands visible

PROCESSING:
- Cleaning table: raw nests soaked in water bowls, feathers removed by tweezers
- Shaping: soft wet nests placed over dome-shaped plastic or metal molds to dry into perfect cups
- Drying racks: shaped nests drying on bamboo or mesh screens in bright indirect light
- Grading room: nests laid out on clean white surfaces, sorted by colour and quality

PREMIUM PACKAGING:
- Matte black gift boxes with gold embossing, silk-lined interior
- Sealed glass jars with dried whole nests inside, premium label
- Vacuum-sealed clear pouches showing the whole nest
- Luxury gift sets on dark marble surfaces with amber lighting

BRAND AESTHETIC:
- Dark moody cinematic lighting, warm amber/gold accent light, deep shadows
- Sabah Borneo tropical setting — misty rainforest, palm fronds, red soil
- No text in image. No people (unless specified). No logos. No city skyline.
- Medium format camera look. Nature documentary meets luxury product photography.
"""

def generate_image_prompt(post_text: str) -> str:
    """Generate a domain-accurate image generation prompt for Imagen 4."""
    return _claude(
        SWIFTLET_VISUAL_KNOWLEDGE,
        [{
            "role": "user",
            "content": (
                "Write a precise Imagen 4 image generation prompt for the following post. "
                "Choose ONE specific visual scene that is most relevant to the post topic — "
                "it could be the farm building, the raw nest, processing, or premium packaging. "
                "Be specific about lighting, angle, and setting. "
                "Return ONLY the prompt (2–4 sentences), no explanation.\n\n"
                f"Post:\n{post_text}"
            ),
        }],
        max_tokens=200,
    )


# ─────────────────────────────────────────────
#  Platform-specific: 小红书
# ─────────────────────────────────────────────

def generate_xhs_post(topic: str, track: str = "investor", research_angle: str = "") -> str:
    """
    Generate a 小红书-optimised post in DeepSeek.

    track: "investor" (finance/investment angle) or "consumer" (lifestyle/health angle)
    research_angle: optional angle from /research output
    """
    system = _xhs_system(track)
    angle_note = f"\n参考角度：{research_angle}" if research_angle else ""
    return _deepseek(
        system,
        f"话题：{topic}{angle_note}\n\n写一篇小红书爆款帖子，附上标题和正文。",
        max_tokens=1200,
    )


# ─────────────────────────────────────────────
#  Platform-specific: Douyin video script
# ─────────────────────────────────────────────

def generate_douyin_script(
    topic: str,
    duration: str = "30秒",
    track: str = "investor",
    research_angle: str = "",
) -> str:
    """
    Generate a Douyin video script.

    track: "investor" (data-led finance hook) or "consumer" (practical lifestyle hook)
    """
    system = _douyin_system(track)
    angle_note = f"\n参考热门角度：{research_angle}" if research_angle else ""
    return _deepseek(
        system,
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

def generate_wechat_post(topic: str, format_type: str = "moments", track: str = "investor") -> str:
    """
    Generate WeChat content.

    format_type: "moments" (short, founder voice) or "article" (long-form official account)
    track: "investor" or "consumer"
    """
    system = _deepseek_system(track)

    if format_type == "article":
        prompt = (
            f"为微信公众号写一篇关于「{topic}」的深度文章。\n"
            "格式：标题 + 导语 + 3-5个小节 + 结尾行动号召\n"
            "字数：800–1200字\n"
            "风格：专业、有深度、有价值感，适合微信生态\n"
            "重要：文章用中文创作。同时在文章最后附上英文摘要（3-4句话），标注为「English Summary:」。"
        )
    else:
        prompt = (
            f"为微信朋友圈写一条关于「{topic}」的帖子。\n"
            "字数：100–200字\n"
            "风格：个人化、真实、有温度，适合老板或创始人发朋友圈\n"
            "重要：帖子用中文创作。同时在最后附上英文摘要（2-3句话），标注为「English Summary:」。"
        )

    return _deepseek(system, prompt, max_tokens=1500)
