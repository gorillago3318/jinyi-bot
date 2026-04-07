"""
kling.py — Kling AI video generation for JinYi Telegram Bot
API docs: app.klingai.com/global/dev

Workflow:
  1. Submit text-to-video task → get task_id
  2. Poll until status == "succeed"
  3. Return video URL
  4. Bot downloads and sends to Telegram
"""

import hashlib
import hmac
import logging
import os
import time
import base64
import requests

logger = logging.getLogger(__name__)

KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY")
KLING_BASE_URL = "https://api.klingai.com"

POLL_INTERVAL = 10   # seconds between status checks
MAX_WAIT = 300       # 5 minutes max wait


# ─────────────────────────────────────────────
#  JWT token generation
# ─────────────────────────────────────────────

def _generate_jwt() -> str:
    """Generate a short-lived JWT for Kling API authentication."""
    import json

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": KLING_ACCESS_KEY,
        "exp": int(time.time()) + 1800,  # 30 min expiry
        "nbf": int(time.time()) - 5,
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    signature = hmac.new(
        KLING_SECRET_KEY.encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).digest()

    return f"{signing_input}.{b64url(signature)}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_generate_jwt()}",
        "Content-Type": "application/json",
    }


# ─────────────────────────────────────────────
#  Text-to-video
# ─────────────────────────────────────────────

def submit_text_to_video(
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",  # vertical for Douyin
    model: str = "kling-v1-6",
    mode: str = "std",           # std or pro
) -> str:
    """Submit a text-to-video task. Returns task_id."""
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY not set")

    payload = {
        "model_name": model,
        "prompt": prompt,
        "duration": str(duration),
        "aspect_ratio": aspect_ratio,
        "mode": mode,
    }

    resp = requests.post(
        f"{KLING_BASE_URL}/v1/videos/text2video",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Kling API error: {data.get('message', data)}")

    task_id = data["data"]["task_id"]
    logger.info(f"Kling task submitted: {task_id}")
    return task_id


def poll_video_result(task_id: str) -> str:
    """
    Poll until video is ready. Returns the video URL.
    Raises TimeoutError if not ready within MAX_WAIT seconds.
    """
    elapsed = 0
    while elapsed < MAX_WAIT:
        resp = requests.get(
            f"{KLING_BASE_URL}/v1/videos/text2video/{task_id}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Kling poll error: {data.get('message', data)}")

        status = data["data"]["task_status"]
        logger.info(f"Kling task {task_id} status: {status} ({elapsed}s)")

        if status == "succeed":
            videos = data["data"]["task_result"].get("videos", [])
            if videos:
                return videos[0]["url"]
            raise RuntimeError("Task succeeded but no video URL returned")

        if status == "failed":
            reason = data["data"].get("task_status_msg", "unknown")
            raise RuntimeError(f"Kling task failed: {reason}")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"Kling video not ready after {MAX_WAIT}s")


def download_video(url: str, save_path: str) -> str:
    """Download video from Kling CDN to local path."""
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path


# ─────────────────────────────────────────────
#  Image-to-video (for posts with a photo)
# ─────────────────────────────────────────────

def submit_image_to_video(
    image_url: str,
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",
    model: str = "kling-v1-6",
    mode: str = "std",
) -> str:
    """Submit an image-to-video task. Returns task_id."""
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        raise ValueError("KLING_ACCESS_KEY and KLING_SECRET_KEY not set")

    payload = {
        "model_name": model,
        "image": image_url,
        "prompt": prompt,
        "duration": str(duration),
        "aspect_ratio": aspect_ratio,
        "mode": mode,
    }

    resp = requests.post(
        f"{KLING_BASE_URL}/v1/videos/image2video",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Kling API error: {data.get('message', data)}")

    return data["data"]["task_id"]
