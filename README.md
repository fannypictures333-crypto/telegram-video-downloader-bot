# 🎬 Video Download Telegram Bot

Telegram-бот для скачивания видео и аудио с YouTube, RuTube, VK Видео, TikTok и Instagram.

## ✨ Возможности

- 📹 Скачивание видео в выбранном качестве (144p — 1080p+)
- 🎵 Извлечение аудио в формате MP3
- 📊 Отображение размера каждого формата перед скачиванием
- ✂️ Автоматическое разбиение видео >50 МБ на части
- 💬 Красивый интерфейс с эмодзи, inline-кнопками и статусами
- ⚡ Асинхронная архитектура (aiogram 3.x + asyncio)

## 📁 Структура проекта

```
video_bot/
├── bot.py                  # Точка входа
├── config/
│   ├── __init__.py
│   └── settings.py         # Настройки (токен, лимиты)
├── handlers/
│   ├── __init__.py
│   ├── start.py            # /start команда
│   ├── url_handler.py      # Приём ссылок, анализ форматов
│   └── download.py         # Скачивание, разбиение, отправка
├── services/
│   ├── __init__.py
│   ├── video_service.py    # yt-dlp + ffmpeg логика
│   └── cache.py            # In-memory кэш URL-данных
├── utils/
│   ├── __init__.py
│   ├── url_utils.py        # Валидация и определение платформы
│   ├── file_utils.py       # Форматирование размеров
│   └── keyboards.py        # Построители inline-клавиатур
├── requirements.txt
├── Dockerfile
└── .env.example
```

## 🚀 Запуск локально

### 1. Требования

- Python 3.12+
- `ffmpeg` установлен в системе (`apt install ffmpeg` / `brew install ffmpeg`)

### 2. Клонирование и установка зависимостей

```bash
git clone <your-repo-url>
cd video_bot
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Настройка переменных окружения

```bash
cp .env.example .env
# Отредактируйте .env, вставьте ваш BOT_TOKEN
```

Получить токен: [@BotFather](https://t.me/BotFather) → `/newbot`

### 4. Запуск

```bash
python bot.py
```

## 🚂 Деплой на Railway

### Шаг 1 — Создайте проект на Railway

1. Зарегистрируйтесь на [railway.app](https://railway.app)
2. New Project → **Deploy from GitHub repo** (или загрузите через CLI)

### Шаг 2 — Добавьте переменную окружения

В Railway: **Variables** → добавьте:

| Имя       | Значение                          |
|-----------|-----------------------------------|
| BOT_TOKEN | `ваш_токен_от_BotFather`          |

### Шаг 3 — Деплой

Railway автоматически обнаружит `Dockerfile` и запустит сборку. После сборки бот стартует автоматически.

> ℹ️ Railway предоставляет постоянный диск через `/tmp` — временные файлы удаляются после каждой отправки.

### Шаг 4 — Проверка

Откройте вашего бота в Telegram и отправьте `/start`.

## ⚙️ Переменные окружения

| Переменная        | Описание                                       | Значение по умолчанию          |
|-------------------|------------------------------------------------|--------------------------------|
| `BOT_TOKEN`       | Токен Telegram-бота (обязательно)              | —                              |
| `DOWNLOAD_DIR`    | Директория для временных файлов                | `/tmp/video_bot_downloads`     |
| `DOWNLOAD_TIMEOUT`| Максимальное время ожидания скачивания (сек.)  | `600`                          |

## 🛠 Технологии

- [aiogram 3.x](https://docs.aiogram.dev/) — Telegram Bot framework
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — Скачивание с видеоплатформ
- [ffmpeg](https://ffmpeg.org/) — Обработка и нарезка видео
- [python-dotenv](https://pypi.org/project/python-dotenv/) — Управление переменными окружения

## ⚠️ Ограничения

- Telegram ограничивает размер файлов до **50 МБ** при отправке через Bot API
- Instagram и TikTok могут требовать cookies/авторизацию для некоторых видео
- VK видео доступны только для публичных записей
