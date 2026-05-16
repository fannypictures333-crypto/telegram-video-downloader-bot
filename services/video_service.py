"""
Video service: wraps yt-dlp to extract info and download videos/audio.
All heavy I/O is run in a thread pool so it does not block the event loop.
"""
import asyncio
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

import yt_dlp

from config.settings import DOWNLOAD_DIR, TELEGRAM_MAX_FILE_SIZE

logger = logging.getLogger(__name__)

# Ensure download directory exists
Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Info extraction
# ---------------------------------------------------------------------------

def _extract_info_sync(url: str) -> dict[str, Any]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "simulate": True,
        "noplaylist": True,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


async def extract_info(url: str) -> dict[str, Any]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract_info_sync, url)


def get_video_formats(info: dict) -> list[dict]:
    """
    Return a deduplicated list of video formats sorted by resolution (desc).
    Each entry: {format_id, height, ext, filesize}
    """
    formats = info.get("formats", [])
    seen_heights: set[int] = set()
    result = []

    # Prefer combined formats (has both video + audio), then video-only
    for fmt in reversed(formats):  # reversed = best quality first from yt-dlp
        vcodec = fmt.get("vcodec", "none")
        if vcodec == "none":
            continue
        height = fmt.get("height")
        if height is None:
            continue
        if height in seen_heights:
            continue
        seen_heights.add(height)
        result.append(
            {
                "format_id": fmt["format_id"],
                "height": height,
                "ext": fmt.get("ext", "mp4"),
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
            }
        )

    # Sort descending by height
    result.sort(key=lambda x: x["height"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def _download_video_sync(url: str, format_id: str, out_dir: str) -> str:
    """Download a video by format_id. Returns path to downloaded file."""
    uid = uuid.uuid4().hex
    outtmpl = os.path.join(out_dir, f"{uid}.%(ext)s")

    ydl_opts = {
        "format": f"{format_id}+bestaudio/best[height<={_height_from_fid(format_id)}]/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        # yt-dlp may change extension after merging
        if not os.path.exists(path):
            # Try .mp4
            path_mp4 = os.path.splitext(path)[0] + ".mp4"
            if os.path.exists(path_mp4):
                path = path_mp4
    return path


def _height_from_fid(format_id: str) -> int:
    """Fallback height — not really used in format string but kept as guard."""
    return 9999


async def download_video(url: str, format_id: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _download_video_sync, url, format_id, DOWNLOAD_DIR
    )


def _download_audio_sync(url: str, out_dir: str) -> str:
    uid = uuid.uuid4().hex
    outtmpl = os.path.join(out_dir, f"{uid}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        # After audio extraction, extension is .mp3
        path_mp3 = os.path.splitext(path)[0] + ".mp3"
        if os.path.exists(path_mp3):
            path = path_mp3
    return path


async def download_audio(url: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_audio_sync, url, DOWNLOAD_DIR)


# ---------------------------------------------------------------------------
# File splitting with ffmpeg
# ---------------------------------------------------------------------------

def _split_video_sync(file_path: str, max_bytes: int) -> list[str]:
    """
    Split a video file into parts, each < max_bytes.
    Uses ffmpeg segment muxer.
    Returns list of part file paths.
    """
    file_size = os.path.getsize(file_path)
    if file_size <= max_bytes:
        return [file_path]

    # Estimate number of parts needed
    num_parts = (file_size // max_bytes) + 1

    # Get video duration via ffprobe
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
        ],
        capture_output=True, text=True, timeout=60,
    )
    duration = float(probe.stdout.strip())
    segment_duration = duration / num_parts
    # Add 10% buffer to stay under the limit
    segment_duration *= 0.9

    base = os.path.splitext(file_path)[0]
    out_pattern = f"{base}_part%03d.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", file_path,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(int(segment_duration)),
            "-reset_timestamps", "1",
            out_pattern,
        ],
        check=True, capture_output=True, timeout=600,
    )

    # Collect output parts
    parts = sorted(
        p for p in Path(os.path.dirname(file_path)).iterdir()
        if p.name.startswith(os.path.basename(base) + "_part") and p.suffix == ".mp4"
    )

    # Remove original
    os.remove(file_path)
    return [str(p) for p in parts]


async def split_video(file_path: str, max_bytes: int = TELEGRAM_MAX_FILE_SIZE) -> list[str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _split_video_sync, file_path, max_bytes)


def cleanup_files(paths: list[str]) -> None:
    """Remove a list of files, ignoring errors."""
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)
