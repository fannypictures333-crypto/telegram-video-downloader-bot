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

TOKEN = "8552385894:AAFlgzHaXol-tby4ZU-nmpripIRfrs_oax8"

# Директория для временных файлов
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Регулярное выражение для проверки ссылок
URL_PATTERN = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')

# Общие опции для yt-dlp
YDL_COMMON_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'no_color': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'referer': 'https://www.google.com/',
    'geo_bypass': True,
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я твой обновленный бот-загрузчик. 🚀\n\n"
        "Я стал умнее и теперь лучше справляюсь с YouTube, Instagram, VK, Rutube и TikTok.\n\n"
        "Просто отправь мне ссылку на видео, и я помогу тебе его скачать! 🎬🎶"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not URL_PATTERN.search(url):
        return

    wait_message = await update.message.reply_text("Анализирую видео... Это может занять до 30 секунд. 🔍")

    try:
        ydl_opts = YDL_COMMON_OPTS.copy()
        
        # Специальные настройки для YouTube и Instagram
        if 'youtube.com' in url or 'youtu.be' in url:
            ydl_opts['extract_flat'] = False
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
            except Exception as e:
                logger.error(f"yt-dlp extract_info error: {e}")
                await wait_message.edit_text(f"Ошибка при анализе: {str(e)[:150]}... 😔\nПопробуйте отправить ссылку еще раз.")
                return

        formats = info.get('formats', [])
        available_qualities = []
        seen_heights = set()
        
        # Улучшенный поиск форматов
        for f in formats:
            height = f.get('height')
            ext = f.get('ext', '')
            vcodec = f.get('vcodec', 'none')
            
            if height and height not in seen_heights and vcodec != 'none':
                # Предпочитаем mp4 для совместимости с Telegram
                available_qualities.append({
                    'height': height,
                    'format_id': f.get('format_id'),
                    'ext': ext if ext in ['mp4', 'mkv', 'webm'] else 'mp4'
                })
                seen_heights.add(height)
        
        available_qualities = sorted(available_qualities, key=lambda x: x['height'], reverse=True)[:5]

        keyboard = []
        if available_qualities:
            for q in available_qualities:
                keyboard.append([InlineKeyboardButton(f"{q['height']}p ({q['ext']})", callback_data=f"dl|{q['format_id']}|{url}")])
        
        keyboard.append([InlineKeyboardButton("Лучшее качество (Auto)", callback_data=f"dl|best|{url}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await wait_message.edit_text("Выбери качество видео:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"General error in handle_message: {e}")
        await wait_message.edit_text("Произошла ошибка. Пожалуйста, убедитесь, что ссылка верна и видео доступно. 🛠")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('|')
    if data[0] == 'dl':
        format_id = data[1]
        url = data[2]
        
        status_msg = await query.edit_message_text("Начинаю загрузку... ⏳")
        
        try:
            file_id = f"{query.from_user.id}_{int(time.time())}"
            video_path = os.path.join(DOWNLOAD_DIR, f"{file_id}_video.mp4")
            audio_path = os.path.join(DOWNLOAD_DIR, f"{file_id}_audio.mp3")

            # Опции для видео
            ydl_opts_video = YDL_COMMON_OPTS.copy()
            if format_id == 'best':
                ydl_opts_video['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                ydl_opts_video['format'] = f"{format_id}+bestaudio/best"
            
            ydl_opts_video['outtmpl'] = video_path
            ydl_opts_video['merge_output_format'] = 'mp4'

            # Опции для аудио
            ydl_opts_audio = YDL_COMMON_OPTS.copy()
            ydl_opts_audio['format'] = 'bestaudio/best'
            ydl_opts_audio['outtmpl'] = audio_path.replace('.mp3', '')
            ydl_opts_audio['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

            # Скачиваем видео
            await status_msg.edit_text("Загружаю видео... 🎬")
            with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
                await asyncio.to_thread(ydl.download, [url])
            
            # Скачиваем аудио
            await status_msg.edit_text("Извлекаю аудио... 🎶")
            with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
                await asyncio.to_thread(ydl.download, [url])

            # Поиск реальных путей
            actual_video = video_path if os.path.exists(video_path) else None
            if not actual_video:
                for f in os.listdir(DOWNLOAD_DIR):
                    if f.startswith(f"{file_id}_video"):
                        actual_video = os.path.join(DOWNLOAD_DIR, f)
                        break

            actual_audio = audio_path if os.path.exists(audio_path) else None
            if not actual_audio:
                for f in os.listdir(DOWNLOAD_DIR):
                    if f.startswith(f"{file_id}_audio") and f.endswith(".mp3"):
                        actual_audio = os.path.join(DOWNLOAD_DIR, f)
                        break

            # Отправка
            if actual_video:
                await status_msg.edit_text("Отправляю видео... 📤")
                with open(actual_video, 'rb') as v:
                    await context.bot.send_video(chat_id=query.message.chat_id, video=v, caption="Твое видео! 🎬")
            
            if actual_audio:
                await status_msg.edit_text("Отправляю аудио... 📤")
                with open(actual_audio, 'rb') as a:
                    await context.bot.send_audio(chat_id=query.message.chat_id, audio=a, caption="Аудиодорожка 🎶")

            await status_msg.delete()

            # Очистка
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(file_id):
                    try: os.remove(os.path.join(DOWNLOAD_DIR, f))
                    except: pass

        except Exception as e:
            logger.error(f"Download error: {e}")
            await query.message.reply_text(f"Ошибка при скачивании: {str(e)[:150]}... 😢")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("Бот запущен с обновленной логикой...")
    application.run_polling()
