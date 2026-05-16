from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def build_format_keyboard(formats: list[dict], url_key: str) -> InlineKeyboardMarkup:
    """
    Build an inline keyboard with available video qualities + audio button.
    formats: list of dicts with keys: format_id, height, ext, filesize
    url_key: a short key (e.g. cache key) to embed in callback data
    """
    from utils.file_utils import format_size

    builder = InlineKeyboardBuilder()
    for fmt in formats:
        height = fmt.get("height") or "?"
        size_label = format_size(fmt.get("filesize"))
        label = f"📹 {height}p — {size_label}"
        builder.button(
            text=label,
            callback_data=f"dl_video|{url_key}|{fmt['format_id']}",
        )
    builder.button(
        text="🎵 Скачать аудио (MP3)",
        callback_data=f"dl_audio|{url_key}",
    )
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def build_split_keyboard(url_key: str, format_id: str) -> InlineKeyboardMarkup:
    """Ask user whether to split a large video."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, разбить на части", callback_data=f"split_yes|{url_key}|{format_id}")
    builder.button(text="❌ Нет, отменить", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def build_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel")
    return builder.as_markup()
