import asyncio
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from bot.core.config import settings
from bot.core.logger import logger
from bot.handlers.start import router as start_router
from bot.handlers.photo import register_photo_handler
from bot.services.gemini_service import GeminiService
from bot.services.telegram_file_service import TelegramFileService
from services.iiko_catalog import IikoCatalog
from services.iiko_server_service import IikoServerService


def _create_temp_dir(path: Path) -> None:
    """Ensure the temporary directory exists."""
    path.mkdir(parents=True, exist_ok=True)


async def _init_iiko(catalog: IikoCatalog, service: IikoServerService) -> None:
    """Load supplier and product catalogs from iiko server."""
    await service.load_catalog(catalog)


async def main() -> None:
    _create_temp_dir(settings.temp_dir)

    bot = Bot(
        token=settings.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dispatcher = Dispatcher()

    telegram_file_service = TelegramFileService(
        bot=bot,
        temp_dir=settings.temp_dir,
    )

    gemini_service = GeminiService(
        api_key=settings.gemini.api_key,
        model=settings.gemini.model,
    )

    # iiko services
    catalog = IikoCatalog(settings.iiko_server.aliases_path)
    iiko_service = IikoServerService(settings)
    await _init_iiko(catalog, iiko_service)

    dispatcher.include_router(start_router)

    photo_router = Router()
    register_photo_handler(
        router=photo_router,
        telegram_file_service=telegram_file_service,
        gemini_service=gemini_service,
        iiko_catalog=catalog,
        iiko_service=iiko_service,
        temp_dir=settings.temp_dir,
    )
    dispatcher.include_router(photo_router)

    logger.info("Starting bot...")
    try:
        await dispatcher.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception:
        logger.exception("Bot stopped with error")
        raise


if __name__ == "__main__":
    asyncio.run(main())
