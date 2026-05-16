from aiogram import Router
from .start import router as start_router
from .url_handler import router as url_router
from .download import router as download_router

__all__ = ["start_router", "url_router", "download_router"]


def register_all_handlers(dp) -> None:
    dp.include_router(start_router)
    dp.include_router(url_router)
    dp.include_router(download_router)
