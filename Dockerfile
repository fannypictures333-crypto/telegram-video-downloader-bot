FROM python:3.12-slim

# Install system dependencies: ffmpeg for video processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Create download temp directory
RUN mkdir -p /tmp/video_bot_downloads

# Run the bot
CMD ["python", "bot.py"]
