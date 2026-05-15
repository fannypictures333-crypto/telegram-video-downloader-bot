import asyncio
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from threading import Thread

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv
from flask import Flask

# Загрузка переменных окружения
load_dotenv()

# Flask для Render
app = Flask(__name__)

@app.route("/")
def hello_world():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Логирование
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logging.error("BOT_TOKEN не найден в переменных окружения.")
    exit(1)

bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE_MB = 48
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Обновляем yt-dlp при запуске — самая частая причина поломки YouTube
def update_ytdlp():
    try:
        result = subprocess.run(
            ['pip', 'install', '--upgrade', 'yt-dlp'],
            capture_output=True, text=True, timeout=60
        )
        logging.info(f"yt-dlp обновлён: {result.stdout.strip()}")
    except Exception as e:
        logging.warning(f"Не удалось обновить yt-dlp: {e}")

# Базовые аргументы yt-dlp, общие для всех платформ
def get_base_ytdlp_args(url: str) -> list:
    args = [
        'yt-dlp',
        '--no-playlist',
        '--socket-timeout', '30',
        '--retries', '5',
        '--user-agent',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]

    # Instagram и ВКонтакте часто требуют cookies
    cookies_file = os.getenv('COOKIES_FILE')  # путь к cookies.txt, если есть
    if cookies_file and os.path.exists(cookies_file):
        args += ['--cookies', cookies_file]

    # RuTube — иногда нужен особый экстрактор
    if 'rutube.ru' in url:
        args += ['--extractor-args', 'rutube:cdn=true']

    return args


def get_video_info(url: str) -> dict | None:
    """Получает метаданные видео через yt-dlp."""
    args = get_base_ytdlp_args(url) + ['--dump-json', url]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            logging.error(f"yt-dlp info error:\n{result.stderr[-2000:]}")
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logging.error("yt-dlp завис при получении информации (timeout).")
        return None
    except json.JSONDecodeError:
        logging.error("Не удалось разобрать JSON от yt-dlp.")
        return None
    except Exception as e:
        logging.error(f"get_video_info: {e}")
        return None


def build_format_options(info: dict) -> list[dict]:
    """
    Формирует список вариантов качества для кнопок.

    Стратегия:
    - Пробуем найти progressive (video+audio в одном потоке) mp4 форматы.
    - Если их нет — добавляем варианты bestvideo+bestaudio для нескольких
      разрешений, yt-dlp сам смержит их через ffmpeg.
    - Всегда добавляем вариант «только аудио».
    """
    options = []
    seen_heights = set()

    all_formats = info.get('formats', [])

    # --- Progressive (merged) форматы ---
    for f in all_formats:
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        if vcodec == 'none' or acodec == 'none':
            continue
        height = f.get('height') or 0
        ext = f.get('ext', '')
        filesize = f.get('filesize') or f.get('filesize_approx') or 0
        if height in seen_heights:
            continue
        seen_heights.add(height)
        options.append({
            'label': f"{height}p" if height else ext,
            'format_spec': f['format_id'],
            'filesize': filesize,
            'is_audio': False,
        })

    # --- DASH / adaptive форматы (video-only + audio-only → мержим) ---
    # Собираем доступные высоты видео-потоков
    video_streams = [
        f for f in all_formats
        if f.get('vcodec', 'none') != 'none'
        and f.get('acodec', 'none') == 'none'
    ]
    audio_streams = [
        f for f in all_formats
        if f.get('acodec', 'none') != 'none'
        and f.get('vcodec', 'none') == 'none'
    ]

    if video_streams and audio_streams:
        # Лучший аудио-поток для оценки размера
        best_audio = max(
            audio_streams,
            key=lambda f: f.get('abr') or f.get('tbr') or 0
        )
        best_audio_size = (
            best_audio.get('filesize') or best_audio.get('filesize_approx') or 0
        )

        heights_seen_in_dash = set()
        for vf in sorted(
            video_streams,
            key=lambda f: f.get('height') or 0,
            reverse=True
        ):
            h = vf.get('height') or 0
            if h in seen_heights or h in heights_seen_in_dash:
                continue
            heights_seen_in_dash.add(h)
            vsize = vf.get('filesize') or vf.get('filesize_approx') or 0
            total_size = vsize + best_audio_size
            options.append({
                'label': f"{h}p" if h else 'best',
                # yt-dlp сам скачает и смержит через ffmpeg
                'format_spec': f"{vf['format_id']}+bestaudio/best",
                'filesize': total_size,
                'is_audio': False,
            })

    # --- Аудио ---
    if audio_streams or any(
        f.get('acodec', 'none') != 'none' for f in all_formats
    ):
        options.append({
            'label': 'Аудио MP3',
            'format_spec': 'bestaudio/best',
            'filesize': 0,
            'is_audio': True,
        })

    # Если совсем ничего не нашли — добавляем универсальный вариант
    if not options:
        options.append({
            'label': 'Лучшее качество',
            'format_spec': 'bestvideo+bestaudio/best',
            'filesize': 0,
            'is_audio': False,
        })
        options.append({
            'label': 'Аудио MP3',
            'format_spec': 'bestaudio/best',
            'filesize': 0,
            'is_audio': True,
        })

    # Убираем дубли по label, сортируем по убыванию размера
    seen_labels: set[str] = set()
    unique: list[dict] = []
    for opt in sorted(options, key=lambda x: x['filesize'], reverse=True):
        if opt['label'] not in seen_labels:
            seen_labels.add(opt['label'])
            unique.append(opt)

    return unique[:8]  # не больше 8 кнопок


async def download_media(url: str, format_spec: str, output_path: str) -> bool:
    """Скачивает видео/аудио через yt-dlp."""
    args = get_base_ytdlp_args(url) + [
        '-f', format_spec,
        '--merge-output-format', 'mp4',
        '-o', output_path,
        url,
    ]
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=600
        )
    except asyncio.TimeoutExpired:
        process.kill()
        logging.error("yt-dlp download timeout.")
        return False

    if process.returncode != 0:
        logging.error(f"yt-dlp download failed:\n{stderr.decode()[-2000:]}")
        return False
    return True


async def convert_to_mp3(input_path: str, output_path: str) -> bool:
    command = [
        'ffmpeg', '-i', input_path,
        '-vn', '-ab', '192k', '-ar', '44100', '-y', output_path
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logging.error(f"FFmpeg MP3 error: {stderr.decode()[-1000:]}")
        return False
    return True


async def split_video(
    input_path: str, output_prefix: str, max_size_bytes: int
) -> list[str]:
    logging.info(f"Разделяю видео {input_path}.")
    parts = []

    probe_cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        input_path,
    ]
    try:
        dur_str = subprocess.check_output(probe_cmd, text=True).strip()
        total_duration = float(dur_str)
    except Exception as e:
        logging.error(f"ffprobe: {e}")
        total_duration = 3600.0

    file_size = os.path.getsize(input_path)
    if total_duration > 0:
        bitrate = (file_size * 8) / total_duration
        segment_duration = max(30.0, min((max_size_bytes * 8) / bitrate, 600.0))
    else:
        segment_duration = 120.0

    current_time = 0.0
    part_num = 0
    while current_time < total_duration:
        part_num += 1
        part_path = f"{output_prefix}_part{part_num}.mp4"
        cmd = [
            'ffmpeg', '-i', input_path,
            '-ss', str(current_time),
            '-t', str(segment_duration),
            '-c', 'copy', '-map', '0',
            '-avoid_negative_ts', 'make_zero',
            '-y', part_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(part_path) or os.path.getsize(part_path) == 0:
            logging.error(f"Ошибка части {part_num}: {stderr.decode()[-500:]}")
            break
        parts.append(part_path)
        current_time += segment_duration

    logging.info(f"Видео разбито на {len(parts)} частей.")
    return parts


# ── Хранилище pending URL для callback ──────────────────────────────────────
# Ключ: chat_id:message_id (кнопки), значение: исходный URL
pending_urls: dict[str, str] = {}


# ── Обработчики ─────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n\n"
        "Я умею скачивать видео с YouTube, TikTok, Instagram, ВКонтакте и RuTube.\n"
        "Просто отправь ссылку — я предложу варианты качества.\n\n"
        "<b>Важно:</b> видео больше 50 МБ будет разбито на части — скачивай по порядку."
    )


@dp.message()
async def handle_message(message: types.Message):
    if not message.text:
        return

    urls = re.findall(r'https?://\S+', message.text)
    if not urls:
        await message.reply("Пожалуйста, отправьте ссылку на видео.")
        return

    url = urls[0]
    status_msg = await message.reply("⏳ Получаю информацию о видео...")

    try:
        info = await asyncio.get_event_loop().run_in_executor(
            None, get_video_info, url
        )
        if not info:
            await status_msg.edit_text(
                "❌ Не удалось получить информацию о видео.\n"
                "Проверьте ссылку или попробуйте позже.\n\n"
                "<i>Возможные причины: видео приватное, геоблок, "
                "или платформа временно недоступна.</i>"
            )
            return

        options = build_format_options(info)
        title = info.get('title', 'Без названия')

        buttons = []
        for i, opt in enumerate(options):
            size_str = (
                f" ({opt['filesize'] / 1024**2:.1f} МБ)"
                if opt['filesize'] > 0 else ""
            )
            btn_text = f"{opt['label']}{size_str}"
            buttons.append([
                types.InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"dl_{i}"
                )
            ])
        buttons.append([
            types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
        ])

        markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)

        reply = await status_msg.edit_text(
            f"🎬 <b>{title[:100]}</b>\n\nВыберите качество:",
            reply_markup=markup
        )

        # Сохраняем URL и опции для callback
        key = f"{reply.chat.id}:{reply.message_id}"
        pending_urls[key] = {'url': url, 'options': options}

    except Exception as e:
        logging.error(f"handle_message error: {e}", exc_info=True)
        await status_msg.edit_text("❌ Произошла ошибка. Попробуйте позже.")


@dp.callback_query(lambda c: c.data.startswith('dl_'))
async def process_callback_download(callback_query: types.CallbackQuery):
    await callback_query.answer("Начинаю скачивание...")
    chat_id = callback_query.message.chat.id
    msg_id = callback_query.message.message_id

    key = f"{chat_id}:{msg_id}"
    stored = pending_urls.get(key)

    if not stored:
        await bot.edit_message_text(
            "❌ Сессия устарела. Отправьте ссылку заново.",
            chat_id=chat_id, message_id=msg_id
        )
        return

    url = stored['url']
    options = stored['options']
    idx = int(callback_query.data.split('_')[1])

    if idx >= len(options):
        await bot.edit_message_text(
            "❌ Неверный выбор.", chat_id=chat_id, message_id=msg_id
        )
        return

    chosen = options[idx]
    format_spec = chosen['format_spec']
    is_audio = chosen['is_audio']

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(DOWNLOAD_DIR, f"video_{timestamp}")

    try:
        await bot.edit_message_text(
            "⬇️ Скачиваю...", chat_id=chat_id, message_id=msg_id
        )

        # yt-dlp добавит расширение сам; указываем шаблон
        output_template = f"{base}.%(ext)s"
        success = await download_media(url, format_spec, output_template)

        if not success:
            await bot.edit_message_text(
                "❌ Ошибка при скачивании. Попробуйте другое качество или позже.",
                chat_id=chat_id, message_id=msg_id
            )
            return

        # Ищем скачанный файл
        downloaded_file = None
        for ext in ('mp4', 'mkv', 'webm', 'm4a', 'mp3', 'opus'):
            candidate = f"{base}.{ext}"
            if os.path.exists(candidate):
                downloaded_file = candidate
                break

        if not downloaded_file:
            # yt-dlp мог дать другое имя — ищем любой новый файл в папке
            files = sorted(
                [f for f in os.listdir(DOWNLOAD_DIR)
                 if f.startswith(f"video_{timestamp}")],
                key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f))
            )
            if files:
                downloaded_file = os.path.join(DOWNLOAD_DIR, files[-1])

        if not downloaded_file or not os.path.exists(downloaded_file):
            await bot.edit_message_text(
                "❌ Файл не найден после скачивания.",
                chat_id=chat_id, message_id=msg_id
            )
            return

        # Аудио → конвертируем в MP3
        if is_audio:
            mp3_path = f"{base}.mp3"
            await bot.edit_message_text(
                "🎵 Конвертирую в MP3...", chat_id=chat_id, message_id=msg_id
            )
            if await convert_to_mp3(downloaded_file, mp3_path):
                await bot.edit_message_text(
                    "📤 Отправляю аудио...", chat_id=chat_id, message_id=msg_id
                )
                await bot.send_audio(
                    chat_id, FSInputFile(mp3_path),
                    caption=f"🎵 {os.path.basename(mp3_path)}"
                )
                await bot.edit_message_text(
                    "✅ Готово!", chat_id=chat_id, message_id=msg_id
                )
            else:
                await bot.edit_message_text(
                    "❌ Ошибка конвертации в MP3.",
                    chat_id=chat_id, message_id=msg_id
                )
            _cleanup(downloaded_file, mp3_path)
            return

        # Видео
        file_size = os.path.getsize(downloaded_file)

        if file_size > MAX_FILE_SIZE_BYTES:
            await bot.edit_message_text(
                "✂️ Видео большое, разбиваю на части...",
                chat_id=chat_id, message_id=msg_id
            )
            parts = await split_video(downloaded_file, base, MAX_FILE_SIZE_BYTES)
            if parts:
                for i, part in enumerate(parts, 1):
                    await bot.edit_message_text(
                        f"📤 Отправляю часть {i}/{len(parts)}...",
                        chat_id=chat_id, message_id=msg_id
                    )
                    await bot.send_video(
                        chat_id, FSInputFile(part),
                        caption=f"Часть {i}/{len(parts)}"
                    )
                    await asyncio.sleep(1)
                await bot.edit_message_text(
                    "✅ Все части отправлены!", chat_id=chat_id, message_id=msg_id
                )
                _cleanup(downloaded_file, *parts)
            else:
                await bot.edit_message_text(
                    "❌ Не удалось разбить видео.",
                    chat_id=chat_id, message_id=msg_id
                )
                _cleanup(downloaded_file)
        else:
            await bot.edit_message_text(
                "📤 Отправляю видео...", chat_id=chat_id, message_id=msg_id
            )
            await bot.send_video(chat_id, FSInputFile(downloaded_file))
            await bot.edit_message_text(
                "✅ Готово!", chat_id=chat_id, message_id=msg_id
            )
            _cleanup(downloaded_file)

        # Удаляем из хранилища
        pending_urls.pop(key, None)

    except Exception as e:
        logging.error(f"process_callback_download error: {e}", exc_info=True)
        try:
            await bot.edit_message_text(
                "❌ Непредвиденная ошибка при скачивании.",
                chat_id=chat_id, message_id=msg_id
            )
        except Exception:
            pass


@dp.callback_query(lambda c: c.data == 'cancel')
async def process_callback_cancel(callback_query: types.CallbackQuery):
    await callback_query.answer("Отменено.")
    key = f"{callback_query.message.chat.id}:{callback_query.message.message_id}"
    pending_urls.pop(key, None)
    await bot.edit_message_text(
        "❌ Скачивание отменено.",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id
    )


def _cleanup(*paths: str):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception as e:
            logging.warning(f"Не удалось удалить {p}: {e}")


async def main() -> None:
    # Обновляем yt-dlp перед запуском
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, update_ytdlp)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
