from pathlib import Path

from aiogram import Bot

from bot.core.logger import logger


class TelegramFileService:
    """Service for downloading files from Telegram.

    The original implementation was specific to photos (``PhotoSize``).  It now
    supports downloading any file type – photos, PDFs, etc. – given a ``file_id``
    returned by Telegram.
    """

    def __init__(self, bot: Bot, temp_dir: Path) -> None:
        self._bot = bot
        self._temp_dir = temp_dir

    async def download_file(self, file_id: str, destination: Path) -> Path:
        """Download a file identified by ``file_id`` to ``destination``.

        The method ensures that temporary and destination directories exist and
        uses :pymeth:`aiogram.Bot.download_file` for the actual download.
        """
        file = await self._bot.get_file(file_id)
        if file.file_path is None:
            raise ValueError(f"File path not found for file_id: {file_id}")

        # Ensure directories exist
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)

        await self._bot.download_file(file.file_path, destination=str(destination.resolve()))
        logger.info("File downloaded: %s", destination)
        return destination
