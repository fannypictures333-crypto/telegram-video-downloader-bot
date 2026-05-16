import os
import asyncio
import logging
import yt_dlp
import re
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Уменьшаем шум от библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)

# Токен
TOKEN = os.getenv("BOT_TOKEN", "8552385894:AAFlgzHaXol-tby4ZU-nmpripIRfrs_oax8")

# Директория для временных файлов
DOWNLOAD_DIR = "downloads"
# Список возможных имен для файла с куками
POSSIBLE_COOKIE_NAMES = ["cookies.txt", "Cookies.txt", "youtube.com_cookies.txt", "youtube_cookies.txt"]

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Регулярное выражение для проверки ссылок
URL_PATTERN = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')

def find_cookies():
    """Ищет файл с куками среди возможных имен"""
    for name in POSSIBLE_COOKIE_NAMES:
        if os.path.exists(name):
            return name
    return None

def get_ydl_opts(custom_opts=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'geo_bypass': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'referer': 'https://www.google.com/',
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
    }
    
    cookie_file = find_cookies()
    if cookie_file:
        opts['cookiefile'] = cookie_file
        logger.info(f"Используется файл куки: {cookie_file}")
    
    if custom_opts:
        opts.update(custom_opts)
    logger.info(f"YDL options: {opts}")
    return opts

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я твой бот-загрузчик. 🚀\n\n"
        "Используйте команду /check, чтобы проверить статус файлов на сервере.\n\n"
        "Просто отправь мне ссылку на видео! 🎬"
    )

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для диагностики файлов на сервере"""
    # Список всех файлов в текущей директории
    all_files = os.listdir('.')
    files_list = "\n".join([f"- {f}" for f in all_files if os.path.isfile(f)])
    
    cookie_file = find_cookies()
    
    if cookie_file:
        size = os.path.getsize(cookie_file)
        cookie_status = f"✅ Файл найден: `{cookie_file}` ({size} байт)"
    else:
        cookie_status = "❌ Файл cookies.txt НЕ найден"

    # Проверка ffmpeg
    import subprocess
    try:
        ffmpeg_version = subprocess.check_output(["ffmpeg", "-version"], stderr=subprocess.STDOUT).decode().split('\n')[0]
        ffmpeg_status = f"✅ Доступен: `{ffmpeg_version}`"
    except Exception as e:
        ffmpeg_status = f"❌ Не найден или ошибка: {str(e)}"

    response = (
        f"🔍 **Диагностика системы**\n\n"
        f"**Cookies:** {cookie_status}\n"
        f"**FFmpeg:** {ffmpeg_status}\n\n"
        f"**Файлы в корне:**\n{files_list}\n\n"
        f"Если FFmpeg не найден, видео не сможет быть обработано."
    )
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    logger.info(f"Получено сообщение от {update.effective_user.id}: {url}")
    
    if not URL_PATTERN.search(url):
        logger.info("Сообщение не содержит валидной ссылки.")
        return

    logger.info(f"Начинаю анализ ссылки: {url}")
    wait_message = await update.message.reply_text("Анализирую видео... 🔍")

    try:
        ydl_opts = get_ydl_opts()
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=False)

        formats = info.get('formats', [])
        available_qualities = []
        seen_heights = set()
        
        for f in formats:
            height = f.get('height')
            vcodec = f.get('vcodec', 'none')
            if height and height not in seen_heights and vcodec != 'none':
                available_qualities.append({
                    'height': height,
                    'format_id': f.get('format_id'),
                    'ext': 'mp4'
                })
                seen_heights.add(height)
        
        available_qualities = sorted(available_qualities, key=lambda x: x['height'], reverse=True)[:5]

        keyboard = []
        for q in available_qualities:
            keyboard.append([InlineKeyboardButton(f"{q['height']}p", callback_data=f"dl|{q['format_id']}|{url}")])
        
        keyboard.append([InlineKeyboardButton("Лучшее качество", callback_data=f"dl|best|{url}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await wait_message.edit_text("Выбери качество видео:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error: {e}")
        error_text = str(e)
        if "Sign in to confirm you’re not a bot" in error_text or "Please log in" in error_text:
            await wait_message.edit_text(
                "❌ Не удалось получить информацию о видео. Возможно, требуется вход в аккаунт или подтверждение, что вы не бот.\n\n"
                "Пожалуйста, убедитесь, что файл `cookies.txt` актуален и содержит необходимые куки для доступа к платформе. Используйте команду /check для проверки наличия файла куки."
            )
        elif "Private video" in error_text or "This video is unavailable" in error_text:
            await wait_message.edit_text("❌ Видео недоступно или является приватным. Убедитесь, что ссылка верна и видео общедоступно. 😔")
        elif "Unsupported URL" in error_text:
            await wait_message.edit_text("❌ Неподдерживаемый URL. Пожалуйста, отправьте ссылку на видео с поддерживаемой платформы (YouTube, TikTok, Rutube, Instagram, VK). 😔")
        else:
            await wait_message.edit_text(f"Ошибка при анализе видео: {error_text[:200]}... 😔\n\nПопробуйте еще раз или проверьте ссылку.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('|')
    if data[0] == 'dl':
        format_id = data[1]
        url = data[2]
        logger.info(f"Пользователь {update.effective_user.id} выбрал качество {format_id} для {url}")
        
        status_msg = await query.edit_message_text("Загрузка началась... ⏳")
        
        try:
            file_id = f"{query.from_user.id}_{int(time.time())}"
            video_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp4")
            audio_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp3")

            # Скачивание видео
            v_opts = get_ydl_opts({
                'format': f"{format_id}+bestaudio/best" if format_id != 'best' else 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
                'outtmpl': video_path,
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
	                    'preferredformat': 'mp4'
                }],
            })
            
            try:
                with yt_dlp.YoutubeDL(v_opts) as ydl:
                    await asyncio.to_thread(ydl.download, [url])
            except Exception as ve:
                logger.error(f"Video download error: {ve}")
            
            # Скачивание аудио
            a_opts = get_ydl_opts({
                'format': 'bestaudio/best',
                'outtmpl': audio_path.replace('.mp3', ''),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }, {
                    'key': 'FFmpegPostProcessor',
                    'args': ['-metadata', 'title=%(title)s', '-metadata', 'artist=%(artist)s']
                }],
            })
            
            try:
                with yt_dlp.YoutubeDL(a_opts) as ydl:
                    await asyncio.to_thread(ydl.download, [url])
            except Exception as ae:
                logger.error(f"Audio download error: {ae}")

            # Отправка
            if os.path.exists(video_path):
                await status_msg.edit_text("Отправляю видео... 📤")
                await context.bot.send_video(chat_id=query.message.chat_id, video=open(video_path, 'rb'), caption="Ваше видео! 🎬")
            
            if os.path.exists(audio_path):
                await status_msg.edit_text("Отправляю аудио... 📤")
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=open(audio_path, 'rb'), caption="Аудиодорожка 🎶")

            if not os.path.exists(video_path) and not os.path.exists(audio_path):
                await status_msg.edit_text("❌ Не удалось скачать ни видео, ни аудио. Возможно, платформа блокирует загрузку с сервера. Попробуйте другую ссылку.")
            else:
                await status_msg.delete()

        except Exception as e:
            logger.error(f"Download error: {e}")
            await query.message.reply_text(f"Ошибка при скачивании: {str(e)[:100]}")
        finally:
            # Очистка
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(file_id):
                    try:
                        os.remove(os.path.join(DOWNLOAD_DIR, f))
                        logger.info(f"Удален временный файл: {f}")
                    except Exception as cleanup_e:
                        logger.error(f"Ошибка при удалении временного файла {f}: {cleanup_e}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('check', check_status))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("Бот запущен...")
    application.run_polling()
