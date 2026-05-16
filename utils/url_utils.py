import re
from config.settings import SUPPORTED_DOMAINS


URL_REGEX = re.compile(r"https?://[^\s]+")


def extract_url(text: str) -> str | None:
    """Extract the first URL from a text message."""
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


def is_supported_url(url: str) -> bool:
    """Check if the URL belongs to a supported platform."""
    return any(domain in url for domain in SUPPORTED_DOMAINS)


def get_platform_name(url: str) -> str:
    """Return a human-readable platform name for the URL."""
    mapping = {
        "youtu": "YouTube",
        "rutube": "RuTube",
        "vk.com": "VK Видео",
        "vkvideo": "VK Видео",
        "tiktok": "TikTok",
        "instagram": "Instagram",
    }
    for key, name in mapping.items():
        if key in url:
            return name
    return "Видео-платформа"
