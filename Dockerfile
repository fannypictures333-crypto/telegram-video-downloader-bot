FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем все файлы из текущей директории в /app внутри контейнера
COPY . .

# Установка зависимостей Python
RUN pip install --no-cache-dir -r requirements.txt

# Проверка наличия файла перед запуском (для отладки в логах)
RUN ls -la /app

# Запуск бота. Используем python без цифр для универсальности
CMD ["python", "bot.py"]
