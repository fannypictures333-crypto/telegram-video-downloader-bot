from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()

WELCOME_TEXT = (
    "👋 <b>Привет, {name}!</b>\n\n"
    "Я умею скачивать видео и аудио с популярных платформ:\n"
    "▶️ YouTube  •  📺 RuTube  •  🎵 TikTok\n"
    "📸 Instagram  •  🔵 VK Видео\n\n"
    "📎 Просто <b>отправь мне ссылку</b> на видео — "
    "я покажу доступные качества и размеры файлов.\n\n"
    "⚠️ <i>Telegram поддерживает файлы до 50 МБ. "
    "Для больших видео предложу разбить на части.</i>"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    name = message.from_user.full_name if message.from_user else "друг"
    await message.answer(WELCOME_TEXT.format(name=name))
