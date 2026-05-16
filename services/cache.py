"""
Simple in-memory URL cache.
Maps a short hash key → {url, info, formats}.
Entries expire after TTL seconds.
"""
import hashlib
import time
from typing import Any

TTL = 3600  # 1 hour

_cache: dict[str, dict[str, Any]] = {}


def _make_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]


def store(url: str, data: dict[str, Any]) -> str:
    key = _make_key(url)
    _cache[key] = {"data": data, "ts": time.time()}
    _evict()
    return key


def get(key: str) -> dict[str, Any] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry["ts"] > TTL:
        del _cache[key]
        return None
    return entry["data"]


def _evict() -> None:
    now = time.time()
    expired = [k for k, v in _cache.items() if now - v["ts"] > TTL]
    for k in expired:
        del _cache[k]
