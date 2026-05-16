import logging
import os

from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile

from config.settings import TELEGRAM_MAX_FILE_SIZE
from services import download_video, download_audio, split_video, cleanup_files, cache
from utils import format_size, build_split_keyboard, build_cancel_keyboard

router = Router()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "cancel")
async def handle_cancel(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "❌ <b>Загрузка отменена.</b>\n\nОтправьте новую ссылку для начала."
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Video download
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("dl_video|"))
async def handle_download_video(callback: CallbackQuery) -> None:
    _, url_key, format_id = callback.data.split("|", 2)

    cached = cache.get(url_key)
    if not cached:
        await callback.message.edit_text(
            "⏰ <b>Сессия истекла.</b> Пожалуйста, отправьте ссылку заново."
        )
        await callback.answer()
        return

    url = cached["url"]
    formats = cached["formats"]
    fmt_info = next((f for f in formats if f["format_id"] == format_id), None)
    height = fmt_info["height"] if fmt_info else "?"
    filesize = fmt_info.get("filesize") if fmt_info else None

    # Check size before downloading
    if filesize and filesize > TELEGRAM_MAX_FILE_SIZE:
        size_label = format_size(filesize)
        await callback.message.edit_text(
            f"⚠️ <b>Видео {height}p весит ~{size_label}</b> — это больше 50 МБ.\n\n"
            "Разбить видео на части и отправить по очереди?",
            reply_markup=build_split_keyboard(url_key, format_id),
        )
        await callback.answer()
        return

    await _do_download_video(callback, url, format_id, height, split=False)


async def _do_download_video(
    callback: CallbackQuery, url: str, format_id: str, height: str | int, split: bool
) -> None:
    await callback.message.edit_text(
        f"⏬ <b>Скачиваем видео {height}p…</b>\n\n"
        "<i>Это может занять некоторое время. Пожалуйста, подождите.</i>"
    )

    try:
        file_path = await download_video(url, format_id)
    except Exception as exc:
        logger.error("download_video error: %s", exc)
        await callback.message.edit_text(
            f"❌ <b>Ошибка при скачивании.</b>\n<code>{exc}</code>\n\n"
            "Попробуйте другое качество или отправьте ссылку заново.",
            reply_markup=build_cancel_keyboard(),
        )
        await callback.answer()
        return

    actual_size = os.path.getsize(file_path)

    if split or actual_size > TELEGRAM_MAX_FILE_SIZE:
        await _send_split(callback, file_path, height)
    else:
        await _send_single_video(callback, file_path, height)

    await callback.answer()


async def _send_single_video(
    callback: CallbackQuery, file_path: str, height: str | int
) -> None:
    try:
        await callback.message.edit_text(
            f"📤 <b>Отправляем видео {height}p…</b>"
        )
        await callback.message.answer_document(
            FSInputFile(file_path),
            caption=f"🎬 Видео {height}p готово!",
        )
        await callback.message.delete()
    except Exception as exc:
        logger.error("send_document error: %s", exc)
        await callback.message.edit_text(
            f"❌ <b>Ошибка при отправке файла.</b>\n<code>{exc}</code>"
        )
    finally:
        cleanup_files([file_path])


async def _send_split(
    callback: CallbackQuery, file_path: str, height: str | int
) -> None:
    await callback.message.edit_text(
        f"✂️ <b>Разбиваем видео {height}p на части…</b>"
    )
    try:
        parts = await split_video(file_path)
    except Exception as exc:
        logger.error("split_video error: %s", exc)
        cleanup_files([file_path])
        await callback.message.edit_text(
            f"❌ <b>Ошибка при разбиении видео.</b>\n<code>{exc}</code>"
        )
        return

    total = len(parts)
    for idx, part_path in enumerate(parts, start=1):
        await callback.message.edit_text(
            f"📤 <b>Отправляем часть {idx} из {total}…</b>"
        )
        try:
            await callback.message.answer_document(
                FSInputFile(part_path),
                caption=f"🎬 Видео {height}p — часть {idx}/{total}",
            )
        except Exception as exc:
            logger.error("send part %s error: %s", idx, exc)
            await callback.message.answer(
                f"❌ Не удалось отправить часть {idx}: <code>{exc}</code>"
            )
        finally:
            cleanup_files([part_path])

    await callback.message.edit_text(
        f"✅ <b>Готово! Отправлено {total} частей.</b>"
    )


# ---------------------------------------------------------------------------
# Split confirmation
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("split_yes|"))
async def handle_split_yes(callback: CallbackQuery) -> None:
    _, url_key, format_id = callback.data.split("|", 2)

    cached = cache.get(url_key)
    if not cached:
        await callback.message.edit_text(
            "⏰ <b>Сессия истекла.</b> Пожалуйста, отправьте ссылку заново."
        )
        await callback.answer()
        return

    url = cached["url"]
    formats = cached["formats"]
    fmt_info = next((f for f in formats if f["format_id"] == format_id), None)
    height = fmt_info["height"] if fmt_info else "?"

    await _do_download_video(callback, url, format_id, height, split=True)


# ---------------------------------------------------------------------------
# Audio download
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("dl_audio|"))
async def handle_download_audio(callback: CallbackQuery) -> None:
    _, url_key = callback.data.split("|", 1)

    cached = cache.get(url_key)
    if not cached:
        await callback.message.edit_text(
            "⏰ <b>Сессия истекла.</b> Пожалуйста, отправьте ссылку заново."
        )
        await callback.answer()
        return

    url = cached["url"]
    await callback.message.edit_text(
        "🎵 <b>Скачиваем аудио (MP3)…</b>\n\n"
        "<i>Пожалуйста, подождите.</i>"
    )

    try:
        file_path = await download_audio(url)
    except Exception as exc:
        logger.error("download_audio error: %s", exc)
        await callback.message.edit_text(
            f"❌ <b>Ошибка при скачивании аудио.</b>\n<code>{exc}</code>"
        )
        await callback.answer()
        return

    await callback.message.edit_text("📤 <b>Отправляем аудио…</b>")
    try:
        await callback.message.answer_audio(
            FSInputFile(file_path),
            caption="🎵 Аудио готово!",
        )
        await callback.message.delete()
    except Exception as exc:
        logger.error("send_audio error: %s", exc)
        # Fallback: send as document (audio may exceed 50 MB)
        try:
            await callback.message.answer_document(
                FSInputFile(file_path),
                caption="🎵 Аудио готово!",
            )
            await callback.message.delete()
        except Exception as exc2:
            await callback.message.edit_text(
                f"❌ <b>Ошибка при отправке аудио.</b>\n<code>{exc2}</code>"
            )
    finally:
        cleanup_files([file_path])

    await callback.answer()
