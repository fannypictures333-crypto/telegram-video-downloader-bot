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

# Токен берется из переменной окружения или вставляется напрямую
TOKEN = os.getenv("BOT_TOKEN", "8552385894:AAFlgzHaXol-tby4ZU-nmpripIRfrs_oax8")

# Директория для временных файлов
DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Регулярное выражение для проверки ссылок
URL_PATTERN = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')

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
    }
    
    # Если файл с куками существует, используем его
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
        logger.info("Используется файл cookies.txt.")
    
    if custom_opts:
        opts.update(custom_opts)
    return opts

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я твой бот-загрузчик. 🚀\n\n"
        "Если YouTube выдает ошибку 'Sign in', значит мне нужны ваши куки.\n"
        "Используйте команду /check, чтобы проверить, видит ли бот файл cookies.txt.\n\n"
        "Просто отправь мне ссылку на видео! 🎬"
    )

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки наличия cookies.txt на сервере"""
    status = "✅ Файл cookies.txt найден!" if os.path.exists(COOKIES_FILE) else "❌ Файл cookies.txt НЕ найден!"
    
    # Проверка размера файла, если он есть
    if os.path.exists(COOKIES_FILE):
        size = os.path.getsize(COOKIES_FILE)
        status += f"\nРазмер файла: {size} байт."
        if size < 100:
            status += "\n⚠️ Файл подозрительно маленький, проверьте содержимое!"
    
    await update.message.reply_text(
        f"Статус системы:\n\n{status}\n\n"
        "Если файл не найден, YouTube будет блокировать скачивание. "
        "Загрузите cookies.txt в корень вашего репозитория на GitHub."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not URL_PATTERN.search(url):
        return

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
        if "Sign in to confirm you’re not a bot" in error_text:
            await wait_message.edit_text(
                "❌ YouTube заблокировал сервер.\n\n"
                "Для работы необходимо добавить файл `cookies.txt` в репозиторий.\n"
                "Проверьте статус командой /check."
            )
        else:
            await wait_message.edit_text(f"Ошибка при анализе: {error_text[:150]}... 😔")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('|')
    if data[0] == 'dl':
        format_id = data[1]
        url = data[2]
        
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
            })
            
            with yt_dlp.YoutubeDL(v_opts) as ydl:
                await asyncio.to_thread(ydl.download, [url])
            
            # Скачивание аудио
            a_opts = get_ydl_opts({
                'format': 'bestaudio/best',
                'outtmpl': audio_path.replace('.mp3', ''),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
            
            with yt_dlp.YoutubeDL(a_opts) as ydl:
                await asyncio.to_thread(ydl.download, [url])

            # Отправка
            if os.path.exists(video_path):
                await status_msg.edit_text("Отправляю видео... 📤")
                await context.bot.send_video(chat_id=query.message.chat_id, video=open(video_path, 'rb'), caption="Ваше видео! 🎬")
            
            if os.path.exists(audio_path):
                await status_msg.edit_text("Отправляю аудио... 📤")
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=open(audio_path, 'rb'), caption="Аудиодорожка 🎶")

            await status_msg.delete()

            # Очистка
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(file_id):
                    try: os.remove(os.path.join(DOWNLOAD_DIR, f))
                    except: pass

        except Exception as e:
            logger.error(f"Download error: {e}")
            await query.message.reply_text(f"Ошибка при скачивании: {str(e)[:100]}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('check', check_status))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("Бот запущен...")
    application.run_polling()
