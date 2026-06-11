
import json
import uuid
from pathlib import Path

from aiogram import Router
from aiogram.types import Message, PhotoSize

from bot.core.logger import logger
from bot.schemas.invoice import InvoiceData
from bot.services.gemini_service import GeminiService
from bot.services.telegram_file_service import TelegramFileService

router = Router()


class PhotoHandler:
    def __init__(
        self,
        telegram_file_service: TelegramFileService,
        gemini_service: GeminiService,
        temp_dir: Path,
    ) -> None:
        self._telegram_file_service = telegram_file_service
        self._gemini_service = gemini_service
        self._temp_dir = temp_dir

    async def handle(self, message: Message, photo_sizes: list[PhotoSize]) -> None:
        processing_msg = await message.answer("Обрабатываю изображение...")

        try:
            file_id = self._telegram_file_service.get_highest_quality_file_id(photo_sizes)
            file_path = self._temp_dir / f"{uuid.uuid4().hex}.jpg"

            await self._telegram_file_service.download_photo(file_id, file_path)

            try:
                invoice_data = await self._gemini_service.extract_invoice_data(file_path)
                response_text = self._format_invoice_response(invoice_data)
            finally:
                self._safe_delete(file_path)

            await processing_msg.delete()
            await message.answer(response_text)

        except json.JSONDecodeError:
            logger.error("Invalid JSON response from Gemini")
            await processing_msg.edit_text("Ошибка: не удалось распознать данные. Попробуйте ещё раз.")
        except ValueError as exc:
            logger.error("Validation error: %s", exc)
            await processing_msg.edit_text(f"Ошибка валидации данных: {exc}")
        except Exception:
            logger.exception("Unexpected error during photo processing")
            await processing_msg.edit_text("Произошла ошибка при обработке. Попробуйте ещё раз.")

    @staticmethod
    def _format_invoice_response(data: InvoiceData) -> str:
        # Human‑readable summary as required
        lines: list[str] = []
        supplier_line = data.supplier.name
        if data.supplier.inn:
            supplier_line += f" (ИНН: {data.supplier.inn})"
        lines.append(supplier_line)
        lines.append(f"Номер: {data.document_number} Дата: {data.document_date.isoformat()}")
        if data.delivery_address:
            lines.append(f"Адрес доставки: {data.delivery_address}")
        lines.append("Товары:")
        for item in data.items:
            unit = f" {item.unit}" if item.unit else ""
            price = f"{item.price:.2f}" if item.price is not None else "null"
            vat = f"{item.vat_sum:.2f}" if item.vat_sum is not None else "null"
            lines.append(
                f"- {item.name}: {item.quantity}{unit} × {price} = {item.amount:.2f} (НДС: {vat})"
            )
        return "\n".join(lines)


    @staticmethod
    def _safe_delete(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to delete temp file: %s", path)


def register_photo_handler(
    router: Router,
    telegram_file_service: TelegramFileService,
    gemini_service: GeminiService,
    temp_dir: Path,
) -> None:
    handler = PhotoHandler(
        telegram_file_service=telegram_file_service,
        gemini_service=gemini_service,
        temp_dir=temp_dir,
    )

    @router.message(lambda msg: msg.photo is not None and len(msg.photo) > 0)
    async def photo_message_handler(message: Message) -> None:
        if message.photo is None:
            return
        await handler.handle(message, list(message.photo))
