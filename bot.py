#!/usr/bin/env python3

import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import yt_dlp

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Bot token from environment variables
TOKEN = os.getenv("BOT_TOKEN")

# All of the bot's logic is in the main function
async def main():
    # Initialize Bot and Dispatcher
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Handler for the /start command
    @dp.message(CommandStart())
    async def command_start_handler(message: types.Message) -> None:
        await message.answer(f"Привет, {message.from_user.full_name}! Я бот для скачивания видео и аудио с YouTube, RuTube, TikTok, VK и Instagram. Просто отправь мне ссылку на видео.")

    # Handler for video URLs
    @dp.message(F.text.regexp(r"https?://[^ ]+"))
    async def handle_video_url(message: types.Message) -> None:
        url = message.text
        await message.answer(f"Получил ссылку: {url}. Пожалуйста, подождите, пока я получу информацию о видео...")

        try:
            ydl_opts = {
                'quiet': True,
                'simulate': True, # Do not download, just get info
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'noplaylist': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get('formats', [])
                video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('ext') == 'mp4']
                audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('ext') == 'm4a']

                if not video_formats and not audio_formats:
                    await message.answer("Не удалось найти доступные форматы для скачивания.")
                    return

                builder = InlineKeyboardBuilder()
                if video_formats:
                    builder.button(text="Скачать видео", callback_data=f"download_video_{url}")
                if audio_formats:
                    builder.button(text="Скачать аудио", callback_data=f"download_audio_{url}")

                await message.answer("Что вы хотите скачать?", reply_markup=builder.as_markup())

        except Exception as e:
            logging.error(f"Error processing URL {url}: {e}")
            await message.answer(f"Произошла ошибка при обработке ссылки: {e}")

    # Handler for inline keyboard callbacks
    @dp.callback_query(F.data.startswith("download_"))
    async def handle_download_callback(callback: types.CallbackQuery) -> None:
        action, url = callback.data.split("_", 1)
        action_type = action.split("_")[1] # video or audio

        await callback.message.edit_text(f"Начинаю скачивание {action_type}...")

        try:
            if action_type == "video":
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': '%(title)s.%(ext)s',
                    'noplaylist': True,
                }
            elif action_type == "audio":
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'outtmpl': '%(title)s.%(ext)s',
                    'noplaylist': True,
                }
            else:
                await callback.message.answer("Неизвестное действие.")
                return

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)

            await callback.message.answer_document(types.FSInputFile(file_path), caption=f"Ваш {action_type} готов!")
            os.remove(file_path) # Clean up the downloaded file

        except Exception as e:
            logging.error(f"Error downloading {action_type} from {url}: {e}")
            await callback.message.answer(f"Произошла ошибка при скачивании {action_type}: {e}")

        await callback.answer()

    # Start polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
