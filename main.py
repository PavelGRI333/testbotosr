import asyncio
from pathlib import Path

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from bot.core.config import settings
from bot.core.logger import logger
from bot.handlers.start import router as start_router
from bot.handlers.photo import register_photo_handler
from bot.services.gemini_service import GeminiService
from bot.services.telegram_file_service import TelegramFileService


def _create_temp_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
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

    dispatcher.include_router(start_router)

    photo_router = Router()
    register_photo_handler(
        router=photo_router,
        telegram_file_service=telegram_file_service,
        gemini_service=gemini_service,
        temp_dir=settings.temp_dir,
    )
    dispatcher.include_router(photo_router)

    logger.info("Starting bot...")

    try:
        asyncio.run(dispatcher.start_polling(bot))
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception:
        logger.exception("Bot stopped with error")
        raise


if __name__ == "__main__":
    main()
