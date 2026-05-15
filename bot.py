import asyncio
import logging
import os
import re
import subprocess
import time
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv
from flask import Flask

# Загрузка переменных окружения из .env файла
load_dotenv()

# Инициализация Flask приложения
app = Flask(__name__)

# Обработчик для корневого URL, чтобы Render видел, что сервер работает
@app.route("/")
def hello_world():
    return "Bot is alive!"

# Запуск Flask приложения в отдельном потоке
def run_flask():
    port = int(os.environ.get("PORT", 10000)) # Используем порт из переменной окружения или 10000
    app.run(host=\'0.0.0.0\', port=port)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
TOKEN = os.getenv(\'BOT_TOKEN\')
if not TOKEN:
    logging.error("BOT_TOKEN не найден в переменных окружения. Убедитесь, что он установлен.")
    exit(1)

bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# Папка для временных файлов
DOWNLOAD_DIR = \'downloads\'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Максимальный размер файла для Telegram (50 МБ)
MAX_FILE_SIZE_MB = 48  # Чуть меньше 50, чтобы избежать проблем с кодировкой и метаданными
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# --- Вспомогательные функции ---

def get_video_info(url):
    try:
        command = [\'yt-dlp\', \'--dump-json\', url]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        import json # Импортируем здесь, чтобы избежать циклической зависимости с Flask
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка при получении информации о видео: {e.stderr}")
        return None
    except json.JSONDecodeError:
        logging.error("Не удалось декодировать JSON из yt-dlp.")
        return None

def get_available_formats(info):
    formats = []
    for f in info.get(\'formats\', []):
        if f.get(\'vcodec\') != \'none\' and f.get(\'acodec\') != \'none\' and f.get(\'ext\') == \'mp4\':
            filesize = f.get(\'filesize\') or f.get(\'filesize_approx\')
            if filesize:
                formats.append({
                    \'format_id\': f[\'format_id\'],
                    \'resolution\': f.get(\'resolution\', f.get(\'height\', \'N/A\')), # Используем resolution или height
                    \'filesize\': filesize,
                    \'url\': f[\'url\']
                })
        elif f.get(\'acodec\') != \'none\' and f.get(\'vcodec\') == \'none\' and f.get(\'ext\') == \'m4a\':
            filesize = f.get(\'filesize\') or f.get(\'filesize_approx\')
            if filesize:
                formats.append({
                    \'format_id\': f[\'format_id\'],
                    \'resolution\': \'audio\',
                    \'filesize\': filesize,
                    \'url\': f[\'url\']
                })
    # Сортируем по размеру файла (от меньшего к большему) и разрешению
    formats.sort(key=lambda x: (x[\'filesize\'] if x[\'filesize\'] else float(\'inf\'), x[\'resolution\']), reverse=True)
    return formats

async def download_video(url, format_id, output_path):
    command = [\'yt-dlp\', \'-f\', format_id, \'-o\', output_path, url]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logging.error(f"yt-dlp download failed: {stderr.decode()}")
        return False
    return True

async def split_video(input_path, output_prefix, max_size_bytes):
    logging.info(f"Начинаю разделение видео {input_path} на части по {max_size_bytes / (1024*1024):.2f} МБ.")
    parts = []
    segment_duration = 60  # Начальная длительность сегмента в секундах
    probe_command = [\'ffprobe\', \'-v\', \'error\', \'-show_entries\', \'format=duration\', \'-of\', \'default=noprint_wrappers=1:nokey=1\', input_path]
    try:
        duration_str = subprocess.check_output(probe_command, text=True).strip()
        total_duration = float(duration_str)
    except (subprocess.CalledProcessError, ValueError) as e:
        logging.error(f"Не удалось получить длительность видео: {e}")
        total_duration = 3600 # Предполагаем 1 час, если не удалось получить

    # Оценим битрейт, чтобы понять, сколько секунд в 48 МБ
    file_size = os.path.getsize(input_path)
    estimated_bitrate = (file_size * 8) / total_duration if total_duration > 0 else 0
    if estimated_bitrate > 0:
        segment_duration = (max_size_bytes * 8) / estimated_bitrate
        segment_duration = max(30, min(segment_duration, 600)) # От 30 секунд до 10 минут

    current_time = 0
    part_num = 0
    while current_time < total_duration:
        part_num += 1
        part_output_path = f"{output_prefix}_part{part_num}.mp4"
        command = [
            \'ffmpeg\',
            \'-i\', input_path,
            \'-ss\', str(current_time),
            \'-t\', str(segment_duration),
            \'-c\', \'copy\',
            \'-map\', \'0\',
            \'-avoid_negative_ts\', \'make_zero\',
            part_output_path
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logging.error(f"Ошибка при создании части {part_num}: {stderr.decode()}")
            # Если ошибка, попробуем перекодировать, если это не первая попытка
            if \'-c copy\' in command:
                logging.warning("Попытка перекодирования сегмента из-за ошибки \'copy\'.")
                command = [
                    \'ffmpeg\',
                    \'-i\', input_path,
                    \'-ss\', str(current_time),
                    \'-t\', str(segment_duration),
                    \'-c:v\', \'libx264\',
                    \'-preset\', \'fast\',
                    \'-crf\', \'28\',
                    \'-c:a\', \'aac\',
                    \'-b:a\', \'128k\',
                    \'-map\', \'0\',
                    \'-avoid_negative_ts\', \'make_zero\',
                    part_output_path
                ]
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    logging.error(f"Повторная ошибка при создании части {part_num} с перекодированием: {stderr.decode()}")
                    break # Выходим, если не удалось даже с перекодированием

        if os.path.exists(part_output_path) and os.path.getsize(part_output_path) > 0:
            parts.append(part_output_path)
            current_time += segment_duration
        else:
            logging.error(f"Часть {part_num} не была создана или пуста. Завершаю разделение.")
            break

    logging.info(f"Видео разделено на {len(parts)} частей.")
    return parts

async def convert_to_mp3(input_path, output_path):
    command = [\'ffmpeg\', \'-i\', input_path, \'-vn\', \'-ab\', \'128k\', \'-ar\', \'44100\', \'-y\', output_path]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logging.error(f"FFmpeg MP3 conversion failed: {stderr.decode()}")
        return False
    return True

# --- Обработчики команд ---

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n\n"\
        "Я бот для скачивания видео с YouTube, TikTok, RuTube и ВКонтакте. "\
        "Просто отправь мне ссылку на видео, и я предложу варианты для скачивания.\n\n"\
        "*Важно:* Если видео очень большое (больше 50 МБ), я отправлю его несколькими частями, "\
        "чтобы сохранить качество и обойти ограничения Telegram. "\
        "Это нормально, просто скачивай их по порядку! 😉"
    )

@dp.message()
async def handle_message(message: types.Message):
    url_pattern = r\'https?://[^\s]+\'
    urls = re.findall(url_pattern, message.text)

    if not urls:
        await message.reply("Пожалуйста, отправьте мне ссылку на видео.")
        return

    url = urls[0]
    await message.reply("Получил ссылку, обрабатываю... Это может занять некоторое время.")

    try:
        info = get_video_info(url)
        if not info:
            await message.reply("Не удалось получить информацию о видео. Возможно, ссылка неверна или видео недоступно.")
            return

        formats = get_available_formats(info)
        if not formats:
            await message.reply("Не найдено доступных форматов для скачивания.")
            return

        keyboard_buttons = []
        for f in formats:
            res = f[\'resolution\']
            size_mb = f[\'filesize\'] / (1024 * 1024) if f[\'filesize\'] else 0
            button_text = f"{res} ({size_mb:.1f} МБ)" if res != \'audio\' else f"Аудио MP3 ({size_mb:.1f} МБ)"
            keyboard_buttons.append([types.InlineKeyboardButton(text=button_text, callback_data=f"download_{f[\'format_id\']}")])

        keyboard_buttons.append([types.InlineKeyboardButton(text="Отмена", callback_data="cancel")])

        reply_markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        # Предупреждение о разделении видео
        if any(f[\'filesize\'] > MAX_FILE_SIZE_BYTES for f in formats if f[\'filesize\']):
            await message.reply(
                "*Внимание:* Некоторые выбранные форматы видео могут быть больше 50 МБ. "\
                "Для сохранения качества я отправлю их несколькими частями. "\
                "Просто скачивайте их по порядку!",
                reply_markup=reply_markup
            )
        else:
            await message.reply("Выберите качество для скачивания:", reply_markup=reply_markup)

    except Exception as e:
        logging.error(f"Ошибка в handle_message: {e}")
        await message.reply("Произошла непредвиденная ошибка. Попробуйте позже.")

@dp.callback_query(lambda c: c.data.startswith(\'download_\'))
async def process_callback_download(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Начинаю скачивание...")
    format_id = callback_query.data.split(\'_\')[1]
    url = callback_query.message.reply_to_message.text # Получаем URL из исходного сообщения

    message_id = callback_query.message.message_id
    chat_id = callback_query.message.chat.id

    try:
        await bot.edit_message_text("Скачиваю видео...", chat_id=chat_id, message_id=message_id)

        info = get_video_info(url)
        if not info:
            await bot.edit_message_text("Не удалось получить информацию о видео.", chat_id=chat_id, message_id=message_id)
            return

        selected_format = next((f for f in get_available_formats(info) if f[\'format_id\'] == format_id), None)
        if not selected_format:
            await bot.edit_message_text("Выбранный формат не найден.", chat_id=chat_id, message_id=message_id)
            return

        title = info.get(\'title\', \'video\').replace(\'/\', \'_\').replace(\'\\\', \'_\')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = os.path.join(DOWNLOAD_DIR, f"{title}_{timestamp}")

        if selected_format[\'resolution\'] == \'audio\':
            temp_video_path = f"{base_filename}.mp4"
            output_mp3_path = f"{base_filename}.mp3"
            if not await download_video(url, format_id, temp_video_path):
                await bot.edit_message_text("Ошибка при скачивании аудио.", chat_id=chat_id, message_id=message_id)
                return
            await bot.edit_message_text("Конвертирую в MP3...", chat_id=chat_id, message_id=message_id)
            if await convert_to_mp3(temp_video_path, output_mp3_path):
                await bot.edit_message_text("Отправляю аудио...", chat_id=chat_id, message_id=message_id)
                await bot.send_audio(chat_id, FSInputFile(output_mp3_path), caption=title)
                await bot.edit_message_text("Готово!", chat_id=chat_id, message_id=message_id)
            else:
                await bot.edit_message_text("Ошибка при конвертации в MP3.", chat_id=chat_id, message_id=message_id)
            # Очистка временных файлов
            if os.path.exists(temp_video_path): os.remove(temp_video_path)
            if os.path.exists(output_mp3_path): os.remove(output_mp3_path)

        else:
            output_video_path = f"{base_filename}.mp4"
            if not await download_video(url, format_id, output_video_path):
                await bot.edit_message_text("Ошибка при скачивании видео.", chat_id=chat_id, message_id=message_id)
                return

            file_size = os.path.getsize(output_video_path)

            if file_size > MAX_FILE_SIZE_BYTES:
                await bot.edit_message_text("Видео слишком большое, отправляю частями...", chat_id=chat_id, message_id=message_id)
                video_parts = await split_video(output_video_path, base_filename, MAX_FILE_SIZE_BYTES)
                if video_parts:
                    for i, part_path in enumerate(video_parts):
                        await bot.send_video(chat_id, FSInputFile(part_path), caption=f"{title} (Часть {i+1}/{len(video_parts)})")
                        # Небольшая задержка между отправками, чтобы не перегружать Telegram API
                        await asyncio.sleep(1)
                    await bot.edit_message_text("Все части отправлены!", chat_id=chat_id, message_id=message_id)
                else:
                    await bot.edit_message_text("Не удалось разделить видео на части.", chat_id=chat_id, message_id=message_id)
            else:
                await bot.edit_message_text("Отправляю видео...", chat_id=chat_id, message_id=message_id)
                await bot.send_video(chat_id, FSInputFile(output_video_path), caption=title)
                await bot.edit_message_text("Готово!", chat_id=chat_id, message_id=message_id)

            # Очистка временных файлов
            if os.path.exists(output_video_path): os.remove(output_video_path)
            for part_path in video_parts if \'video_parts\' in locals() else []:
                if os.path.exists(part_path): os.remove(part_path)

    except Exception as e:
        logging.error(f"Ошибка в process_callback_download: {e}")
        await bot.edit_message_text("Произошла непредвиденная ошибка при скачивании/отправке.", chat_id=chat_id, message_id=message_id)

@dp.callback_query(lambda c: c.data == \'cancel\')
async def process_callback_cancel(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Отменено.")
    await bot.edit_message_text("Скачивание отменено.", chat_id=callback_query.message.chat.id, message_id=callback_query.message.message_id)


async def main() -> None:
    # Запускаем Flask в отдельном потоке
    import threading
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    import json # Импортируем здесь, чтобы избежать циклической зависимости с Flask
    asyncio.run(main())