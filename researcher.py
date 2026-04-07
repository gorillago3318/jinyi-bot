"""
researcher.py — Weekly content research for JinYi Telegram Bot
Uses Kimi AI (Moonshot) to browse 小红书 and Douyin for trending content
about bird's nest / swiftlet farming, then adapts findings into JinYi post ideas.

Schedule: Every Monday 9:00 AM MYT
Output: Telegram message to owner with 5 content ideas + source angles
"""

import logging
import os
import json
from openai import OpenAI  # Kimi uses OpenAI-compatible API

logger = logging.getLogger(__name__)

KIMI_API_KEY = os.getenv("KIMI_API_KEY")
KIMI_BASE_URL = "https://api.moonshot.cn/v1"

# Search topics — what we hunt for on 小红书 / Douyin
RESEARCH_TOPICS = [
    "燕窝功效 真实体验",
    "燕窝投资 值不值",
    "燕屋养殖 怎么赚钱",
    "燕窝怎么辨别真假",
    "马来西亚燕窝 和印尼燕窝 区别",
    "燕窝 孕妇 功效",
    "燕屋 投资回报 多少年",
    "燕窝 每天吃 有什么好处",
    "沙巴燕窝 为什么贵",
    "燕窝 养颜 效果",
]

SYSTEM_PROMPT_RESEARCHER = """你是一名社交媒体内容研究员，专门研究中国社交平台（小红书、抖音）上关于燕窝和燕屋养殖的热门内容。

你的任务：
1. 分析用户提供的搜索话题
2. 找出该话题下最受欢迎的内容角度、钩子（hook）和用户痛点
3. 提炼出可供品牌借鉴的内容创意

输出格式（严格按此格式）：
每个创意用以下结构：
---
📌 Topic Angle (English): [one-line summary in English for the brand owner]
📌 话题角度: [核心角度，一句话]
🎯 User Pain Point (English): [what users really want to know, in English]
💡 Hook (Chinese): [开头的第一句话，能让人停下来看]
📝 Content Direction (English): [2-3 sentences in English describing what this post should cover]
🏷️ 建议标签: [3-5个相关标签]
---
"""


def research_trending_content(num_ideas: int = 5) -> str:
    """
    Browse 小红书 / Douyin via Kimi and return content ideas.
    Returns formatted string with ideas ready to send via Telegram.
    """
    if not KIMI_API_KEY:
        return "❌ KIMI_API_KEY not set. Add it to Railway environment variables."

    import random
    selected_topics = random.sample(RESEARCH_TOPICS, min(num_ideas, len(RESEARCH_TOPICS)))

    client = OpenAI(
        api_key=KIMI_API_KEY,
        base_url=KIMI_BASE_URL,
    )

    topics_str = "\n".join(f"- {t}" for t in selected_topics)

    try:
        response = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_RESEARCHER,
                },
                {
                    "role": "user",
                    "content": (
                        f"请研究以下话题在小红书和抖音上的热门内容趋势，"
                        f"为燕窝养殖投资品牌「锦益集团」提供{num_ideas}个内容创意：\n\n"
                        f"{topics_str}\n\n"
                        f"重点关注：\n"
                        f"1. 真实用户的问题和痛点（不是品牌想说的话）\n"
                        f"2. 评论区里反复出现的疑问\n"
                        f"3. 高赞内容的共同特征（情绪、角度、钩子）\n"
                        f"4. 锦益集团可以用权威和真实经验回答的话题\n\n"
                        f"输出{num_ideas}个完整的内容创意，按上述格式。"
                    ),
                },
            ],
            temperature=0.7,
        )

        ideas_text = response.choices[0].message.content

        # Wrap with header
        result = (
            "🔍 *本周内容研究报告*\n"
            f"_基于小红书 & 抖音热门趋势_\n\n"
            f"{ideas_text}\n\n"
            "———\n"
            "回复 /draft [话题角度] 让Claude起草对应帖子\n"
            "例：/draft 燕窝投资值不值，5年亲身经历告诉你"
        )

        return result

    except Exception as e:
        logger.error(f"Kimi research failed: {e}")
        return f"❌ Research failed: {e}"


def research_with_kimi_search(query: str) -> str:
    """
    Use Kimi's web search to find specific trending content.
    More targeted — searches a specific query on Chinese web.
    """
    if not KIMI_API_KEY:
        return "❌ KIMI_API_KEY not set."

    client = OpenAI(
        api_key=KIMI_API_KEY,
        base_url=KIMI_BASE_URL,
    )

    try:
        response = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是内容研究专家。用户会给你一个搜索词，"
                        "请分析该话题在小红书和抖音上的内容趋势，"
                        "包括：用户最常问的问题、热门内容的角度、"
                        "评论区的真实反馈。用中文回答。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"请分析「{query}」这个话题在小红书和抖音上的内容趋势。\n\n"
                        "我需要了解：\n"
                        "1. 用户最常问什么问题？\n"
                        "2. 哪类内容最受欢迎（教程/测评/故事/数据）？\n"
                        "3. 评论区里反复出现的疑虑或争议点？\n"
                        "4. 作为燕窝品牌，我们如何切入这个话题？\n\n"
                        "请给出3个具体的内容创意，附带钩子句和内容框架。"
                    ),
                },
            ],
            temperature=0.6,
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Kimi search failed: {e}")
        return f"❌ Search failed: {e}"
