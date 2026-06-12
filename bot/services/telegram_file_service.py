from pathlib import Path

from aiogram import Bot
from aiogram.types import PhotoSize

from bot.core.logger import logger


class TelegramFileService:
    def __init__(self, bot: Bot, temp_dir: Path) -> None:
        self._bot = bot
        self._temp_dir = temp_dir

    async def download_photo(self, file_id: str, destination: Path) -> Path:
        file = await self._bot.get_file(file_id)
        if file.file_path is None:
            raise ValueError(f"File path not found for file_id: {file_id}")

        self._temp_dir.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)

        await self._bot.download_file(file.file_path, destination=str(destination.resolve()))
        logger.info("File downloaded: %s", destination)

        return destination

    def get_highest_quality_file_id(self, photo_sizes: list[PhotoSize]) -> str:
        return max(photo_sizes, key=lambda p: p.width * p.height).file_id
