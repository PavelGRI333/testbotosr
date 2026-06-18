import json
import uuid
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.core.logger import logger
from bot.handlers.invoice_edit import show_editor
from bot.services.llm_service import LLMService
from bot.services.telegram_file_service import TelegramFileService

router = Router()


class DocumentHandler:
    """Handle incoming PDF documents containing invoices.

    The handler validates the MIME type, downloads the file, forwards it to the
    LLM for extraction and finally opens the editor UI.
    """

    def __init__(
        self,
        telegram_file_service: TelegramFileService,
        llm_service: LLMService,
        temp_dir: Path,
    ) -> None:
        self._telegram_file_service = telegram_file_service
        self._llm_service = llm_service
        self._temp_dir = temp_dir

    async def handle(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        processing_msg = await message.answer("Обрабатываю PDF документ...")

        try:
            if not message.document:
                raise ValueError("No document attached")
            if message.document.mime_type != "application/pdf":
                await message.answer("Пожалуйста, отправьте PDF-файл.")
                return

            file_id = message.document.file_id
            file_path = self._temp_dir / f"{uuid.uuid4().hex}.pdf"

            await self._telegram_file_service.download_file(file_id, file_path)

            try:
                invoice_data = await self._llm_service.extract_invoice_data(
                    file_path, mime_type="application/pdf"
                )
            finally:
                self._safe_delete(file_path)

            await processing_msg.delete()
            await show_editor(message, state, invoice_data)

        except json.JSONDecodeError:
            logger.error("Invalid JSON response from LLM")
            await processing_msg.edit_text(
                "Ошибка: не удалось распознать данные. Попробуйте ещё раз."
            )
        except ValueError as exc:
            logger.error("Validation error: %s", exc)
            await processing_msg.edit_text(f"Ошибка валидации данных: {exc}")
        except Exception:
            logger.exception("Unexpected error during PDF processing")
            await processing_msg.edit_text(
                "Произошла ошибка при обработке. Попробуйте ещё раз."
            )

    @staticmethod
    def _safe_delete(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to delete temp file: %s", path)


def register_document_handler(
    router: Router,
    telegram_file_service: TelegramFileService,
    llm_service: LLMService,
    temp_dir: Path,
) -> None:
    handler = DocumentHandler(
        telegram_file_service=telegram_file_service,
        llm_service=llm_service,
        temp_dir=temp_dir,
    )

    @router.message(F.document)
    async def document_message_handler(message: Message, state: FSMContext) -> None:
        if not message.document:
            return
        await handler.handle(message, state)
