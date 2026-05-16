import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Telegram file size limit in bytes (50 MB)
TELEGRAM_MAX_FILE_SIZE: int = 50 * 1024 * 1024

# Download directory
DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", "/tmp/video_bot_downloads")

# Max download timeout in seconds
DOWNLOAD_TIMEOUT: int = int(os.getenv("DOWNLOAD_TIMEOUT", "600"))

# Supported URL patterns
SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "rutube.ru",
    "vk.com", "vkvideo.ru",
    "tiktok.com",
    "instagram.com",
]
