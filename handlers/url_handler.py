import logging

from aiogram import Router, F
from aiogram.types import Message

from config.settings import TELEGRAM_MAX_FILE_SIZE
from services import extract_info, get_video_formats, cache
from utils import (
    extract_url,
    is_supported_url,
    get_platform_name,
    format_size,
    build_format_keyboard,
)

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text.regexp(r"https?://[^\s]+"))
async def handle_url(message: Message) -> None:
    url = extract_url(message.text or "")
    if not url:
        return

    if not is_supported_url(url):
        await message.answer(
            "❌ <b>Неподдерживаемая платформа.</b>\n\n"
            "Поддерживаются: YouTube, RuTube, VK Видео, TikTok, Instagram."
        )
        return

    platform = get_platform_name(url)
    status_msg = await message.answer(
        f"🔍 <b>Анализируем ссылку…</b>\n"
        f"📡 Платформа: <i>{platform}</i>\n\n"
        f"<i>Это займёт несколько секунд.</i>"
    )

    try:
        info = await extract_info(url)
    except Exception as exc:
        logger.error("extract_info failed for %s: %s", url, exc)
        await status_msg.edit_text(
            "❌ <b>Не удалось получить информацию о видео.</b>\n\n"
            "Проверьте ссылку или попробуйте позже.\n"
            f"<code>{exc}</code>"
        )
        return

    title = info.get("title", "Без названия")
    duration = info.get("duration")
    duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "неизвестно"
    thumbnail = info.get("thumbnail", "")

    formats = get_video_formats(info)
    if not formats:
        await status_msg.edit_text(
            "⚠️ <b>Не удалось найти форматы для скачивания.</b>\n"
            "Возможно, видео недоступно или защищено."
        )
        return

    # Store in cache
    url_key = cache.store(url, {"url": url, "info": info, "formats": formats})

    # Build info text
    lines = [
    f"🎬 <b>Видео найдено</b>",
        f"⏱ Длительность: <i>{duration_str}</i>",
        "",
        "📊 <b>Доступные качества:</b>",
    ]
    for fmt in formats:
        size_label = format_size(fmt.get("filesize"))
        over = "⚠️ >50МБ " if (
            fmt.get("filesize") and fmt["filesize"] > TELEGRAM_MAX_FILE_SIZE
        ) else ""
        lines.append(f"  • {fmt['height']}p — {size_label} {over}")

    lines += [
        "",
        "⚠️ <i>Telegram поддерживает отправку файлов до 50 МБ.</i>",
        "",
        "👇 <b>Выберите качество или скачайте аудио:</b>",
    ]

    await status_msg.edit_text(
        "\n".join(lines),
        reply_markup=build_format_keyboard(formats, url_key),
    )
