import json
import uuid
from pathlib import Path

from aiogram import Router
from aiogram.types import Message, PhotoSize

from bot.core.logger import logger
from bot.core.config import settings
from bot.schemas.invoice import InvoiceData
from bot.services.gemini_service import GeminiService
from bot.services.telegram_file_service import TelegramFileService
from services.iiko_catalog import IikoCatalog
from services.iiko_server_service import IikoServerService

router = Router()


class PhotoHandler:
    def __init__(
        self,
        telegram_file_service: TelegramFileService,
        gemini_service: GeminiService,
        iiko_catalog: "IikoCatalog",
        iiko_service: "IikoServerService",
        temp_dir: Path,
    ) -> None:
        self._telegram_file_service = telegram_file_service
        self._gemini_service = gemini_service
        self._iiko_catalog = iiko_catalog
        self._iiko_service = iiko_service
        self._temp_dir = temp_dir

    async def handle(self, message: Message, photo_sizes: list[PhotoSize]) -> None:
        processing_msg = await message.answer("Обрабатываю изображение...")

        try:
            file_id = self._telegram_file_service.get_highest_quality_file_id(photo_sizes)
            file_path = self._temp_dir / f"{uuid.uuid4().hex}.jpg"

            await self._telegram_file_service.download_photo(file_id, file_path)

            try:
                invoice_data = await self._gemini_service.extract_invoice_data(file_path)

                # Resolve supplier
                supplier_id = self._iiko_catalog.match_supplier(
                    inn=invoice_data.supplier.inn,
                    name=invoice_data.supplier.name,
                )
                if not supplier_id:
                    raise ValueError("Не найден поставщик в справочнике iiko.")

                store_id = settings.iiko_server.default_store_id

                # Resolve products
                resolved: dict[str, str] = {}
                problems: list[str] = []
                for item in invoice_data.items:
                    matches = self._iiko_catalog.match_product(item.name)
                    if not matches:
                        problems.append(f"Товар '{item.name}' не найден.")
                        continue
                    name, score, gid = matches[0]
                    if score >= 92:
                        resolved[item.name] = gid
                    elif score >= 70:
                        # ambiguous – list top candidates
                        cand_str = ", ".join(f"{m[0]} ({m[1]}%)" for m in matches)
                        problems.append(f"Неоднозначный товар '{item.name}': {cand_str}")
                    else:
                        problems.append(f"Товар '{item.name}' с низким совпадением ({score}%).")
                if problems:
                    raise ValueError("\n".join(problems))

                ok, result_msg = await self._iiko_service.create_incoming_invoice(
                    invoice=invoice_data,
                    supplier_id=supplier_id,
                    store_id=store_id,
                    resolved=resolved,
                )
                response_text = result_msg if ok else f"Ошибка импорта: {result_msg}"
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
        return f"<pre>{json.dumps(data.model_dump(by_alias=True), indent=2, ensure_ascii=False)}</pre>"

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
    iiko_catalog: IikoCatalog,
    iiko_service: IikoServerService,
    temp_dir: Path,
) -> None:
    handler = PhotoHandler(
        telegram_file_service=telegram_file_service,
        gemini_service=gemini_service,
        iiko_catalog=iiko_catalog,
        iiko_service=iiko_service,
        temp_dir=temp_dir,
    )

    @router.message(lambda msg: msg.photo is not None and len(msg.photo) > 0)
    async def photo_message_handler(message: Message) -> None:
        if message.photo is None:
            return
        await handler.handle(message, list(message.photo))
