"""
imager.py — AI image generation via Google Imagen 4 (Google AI Studio)

Generates premium brand images for:
- Blog posts (1:1 square)
- Facebook posts (4:5 portrait)
- XHS / Xiaohongshu (3:4 portrait)
- LinkedIn (1.91:1 landscape)

Returns: local file path to saved PNG
"""

import os
import logging
import tempfile
from pathlib import Path
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Aspect ratios supported by Imagen 3
ASPECT_RATIOS = {
    "square":    "1:1",    # Blog, general
    "portrait":  "3:4",    # XHS
    "facebook":  "4:5",    # Facebook feed
    "linkedin":  "16:9",   # LinkedIn
    "story":     "9:16",   # Stories / Douyin
}

# Brand style suffix appended to every prompt
BRAND_STYLE = (
    "Premium photorealistic quality. Dark moody luxury aesthetic. "
    "Malaysian Borneo / Sabah jungle setting. Deep shadows, warm amber and gold accent lighting. "
    "No text overlay. No people. No logos. No city skyline. No high-rise buildings. "
    "Shot on medium format camera. Nature documentary and agricultural photography style. "
    "Ultra high resolution. "
    # ── Swiftlet farm architecture constraints ──
    "If architecture is shown: it must be a SWIFTLET FARM — a low-rise 2 to 4 storey "
    "plain rectangular concrete or brick building, maximum 4 floors tall, standalone structure "
    "surrounded by tropical jungle or palm trees. "
    "The facade has rows of small circular or rectangular bird entry holes, NOT windows. "
    "NOT an apartment block. NOT a commercial tower. NOT a shophouse row. NOT a skyscraper. "
    "Swiftlets (small birds) may be seen flying around the building at dusk or dawn. "
    "Misty tropical rainforest background. Sabah Borneo rural landscape."
)


def generate_image(
    prompt: str,
    format: str = "square",
    save_dir: str | None = None,
) -> str:
    """
    Generate an image using Imagen 3.

    Args:
        prompt: Visual description (from generate_image_prompt())
        format: "square" | "portrait" | "facebook" | "linkedin" | "story"
        save_dir: Directory to save image. Uses temp dir if None.

    Returns:
        Absolute path to saved PNG file.

    Raises:
        Exception if generation fails.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=GEMINI_API_KEY)
    aspect_ratio = ASPECT_RATIOS.get(format, "1:1")
    full_prompt = f"{prompt.rstrip('.')}. {BRAND_STYLE}"

    logger.info(f"Generating Imagen 4 image — format={format} ({aspect_ratio})")

    response = client.models.generate_images(
        model="imagen-4.0-generate-001",
        prompt=full_prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_ratio,
            safety_filter_level="block_low_and_above",
            person_generation="dont_allow",
        ),
    )

    if not response.generated_images:
        raise ValueError("Imagen returned no images")

    image_data = response.generated_images[0].image.image_bytes

    # Save to file
    save_dir = save_dir or tempfile.gettempdir()
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(save_dir) / f"jinyi_{format}_{os.urandom(4).hex()}.png")

    with open(out_path, "wb") as f:
        f.write(image_data)

    logger.info(f"Image saved: {out_path} ({len(image_data) // 1024}KB)")
    return out_path


def generate_post_images(prompt: str, save_dir: str | None = None) -> dict[str, str]:
    """
    Generate all format variants for a post in one call.
    Returns dict: { "square": path, "portrait": path, "facebook": path, "linkedin": path }
    Only generates what succeeds — partial results returned on failure.
    """
    results = {}
    for fmt in ("square", "portrait", "facebook", "linkedin"):
        try:
            results[fmt] = generate_image(prompt, format=fmt, save_dir=save_dir)
            logger.info(f"Generated {fmt} image")
        except Exception as e:
            logger.warning(f"Image generation failed for {fmt}: {e}")
    return results
