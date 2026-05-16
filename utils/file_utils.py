def format_size(size_bytes: int | float | None) -> str:
    """Format file size into a human-readable string."""
    if size_bytes is None:
        return "неизвестно"
    size_bytes = int(size_bytes)
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} КБ"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.1f} МБ"
    else:
        return f"{size_bytes / 1024 ** 3:.2f} ГБ"


def exceeds_telegram_limit(size_bytes: int | float | None, limit: int) -> bool:
    """Return True if size_bytes exceeds the given byte limit."""
    if size_bytes is None:
        return False
    return int(size_bytes) > limit
