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
from pydantic import ValidationError
from typing import Optional

router = Router()


class PhotoHandler:
    def __init__(
        self,
        telegram_file_service: TelegramFileService,
        gemini_service: GeminiService,
        iiko_catalog: Optional[IikoCatalog],
        iiko_service: Optional[IikoServerService],
        temp_dir: Path,
    ) -> None:
        self._telegram_file_service = telegram_file_service
        self._gemini_service = gemini_service
        self._iiko_catalog = iiko_catalog
        self._iiko_service = iiko_service
        self._temp_dir = temp_dir

    async def handle(self, message: Message, photo_sizes: list[PhotoSize]) -> None:
        # initial status message
        status_msg = await message.answer("📸 Обрабатываю накладную, подождите…")

        try:
            file_id = self._telegram_file_service.get_highest_quality_file_id(photo_sizes)
            file_path = self._temp_dir / f"{uuid.uuid4().hex}.jpg"

            await self._telegram_file_service.download_photo(file_id, file_path)

            invoice_data = await self._gemini_service.extract_invoice_data(file_path)

            # ---- iiko integration branch ----
            if (
                settings.iiko_server
                and getattr(settings.iiko_server, "enabled", False)
                and self._iiko_catalog
                and self._iiko_service
            ):
                supplier_id = self._iiko_catalog.match_supplier(
                    inn=invoice_data.supplier.inn,
                    name=invoice_data.supplier.name,
                )
                if not supplier_id:
                    raise ValueError("Не найден поставщик в справочнике iiko.")
                store_id = settings.iiko_server.default_store_id

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
                        cand_str = ", ".join(f"{m[0]} ({m[1]}%)" for m in matches)
                        problems.append(f"Неоднозначный товар '{item.name}': {cand_str}")
                    else:
                        problems.append(f"Товар '{item.name}' с низким совпадением ({score}%).")
                if problems:
                    raise ValueError("\\n".join(problems))

                ok, result_msg = await self._iiko_service.create_incoming_invoice(
                    invoice=invoice_data,
                    supplier_id=supplier_id,
                    store_id=store_id,
                    resolved=resolved,
                )
                response_text = result_msg if ok else f"Ошибка импорта: {result_msg}"
            else:
                # ---- iiko disabled or unavailable ----
                response_text = self._format_invoice_response(invoice_data)

            await status_msg.edit_text(response_text)

        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON response from Gemini: %s", exc)
            await status_msg.edit_text(
                "⚠️ Не удалось распознать данные. Попробуйте ещё раз."
            )
        except ValidationError as exc:
            logger.exception("Ошибка валидации данных")
            await status_msg.edit_text(f"⚠️ Ошибка валидации данных: {exc}")
        except ValueError as exc:
            logger.error("Validation error: %s", exc)
            await status_msg.edit_text(f"⚠️ Ошибка валидации: {exc}")
        except Exception as exc:
            logger.exception("Unexpected error during photo processing")
            await status_msg.edit_text(f"⚠️ Ошибка обработки: {exc}")
        finally:
            # ensure temporary file removal even if download failed
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                logger.warning("Failed to delete temporary photo file")

    @staticmethod
    def _format_invoice_response(data: InvoiceData) -> str:
        """Human‑readable representation of the parsed invoice (iiko disabled)."""
        lines = [
            f"Поставщик: {data.supplier.name} (ИНН {data.supplier.inn or '—'})",
            f"Документ № {data.document_number} от {data.document_date.isoformat()}",
            f"Адрес доставки: {data.delivery_address or '—'}",
            "Товары:",
        ]
        for i, it in enumerate(data.items, start=1):
            unit = it.unit or ""
            price = f"{it.price:.2f}" if it.price is not None else "—"
            lines.append(
                f"  {i}. {it.name} — {it.quantity} {unit} × {price} = {it.amount}"
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
    iiko_catalog: Optional[IikoCatalog],
    iiko_service: Optional[IikoServerService],
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
