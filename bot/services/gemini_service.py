import json
from pathlib import Path

from google import genai
from google.genai import types

from bot.core.logger import logger
from bot.schemas.invoice import InvoiceData

INVOICE_PROMPT = """\
Ты — система распознавания товарных накладных (УПД / ТОРГ-12 / счёт-фактура).
На вход подаётся фотография документа на русском языке.

ФОРМАТ ОТВЕТА
- Верни ТОЛЬКО валидный JSON-объект по схеме ниже.
- НЕ оборачивай ответ в markdown, НЕ используй ```json и ```.
- НЕ добавляй никакого текста, пояснений или комментариев до или после JSON.
- Первый символ ответа — «{», последний — «}».

ОБЩИЕ ПРАВИЛА
1. Извлекай только то, что реально видно в документе. Ничего не додумывай.
2. Если поле не найдено или нечитаемо — поставь null. Позицию без названия
   и количества не добавляй вовсе. Не подставляй догадки и значения по умолчанию.
3. Все числа — с точкой как десятичным разделителем, без пробелов и разделителей
   тысяч и без знака валюты. Пример: «3 579,42» → 3579.42; «24,920» → 24.92.

НАИМЕНОВАНИЕ ТОВАРА (критично — соблюдай неукоснительно)
4. Поле name — ТОЧНАЯ посимвольная транскрипция наименования из документа.
5. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО исправлять орфографию, «угадывать», переводить,
   дополнять или нормализовать слова — даже если слово кажется ошибочным,
   незнакомым, обрезанным или с опечаткой. Копируй ровно то, что напечатано.
   Пример: если в документе написано «Шпик» — верни «Шпик», а НЕ «Шинк»
   и НЕ «Шпинат». Если написано «зам.» — так и пиши «зам.», не разворачивай
   в «замороженный».
6. Сохраняй регистр, сокращения, кавычки, знаки и числа внутри названия как есть.

ДАТА
7. document_date — дата документа ПОЛНОСТЬЮ, включая год, в формате YYYY-MM-DD.
8. Внимательно читай год, не путай похожие цифры (0/6/8/9). Если дата написана
   прописью («7 мая 2026 года») — преобразуй её в 2026-05-07.

ПОСТАВЩИК И ПОКУПАТЕЛЬ
9.  supplier.name — наименование продавца (поле «Продавец»).
10. supplier.inn — ИНН продавца из поля «ИНН/КПП продавца» (только цифры ИНН,
    без КПП). buyer_inn — ИНН покупателя из поля «ИНН/КПП покупателя».

ПОЗИЦИИ (по каждой строке товарной таблицы)
11. name        — наименование (правила 4–6).
12. quantity    — количество (графа «Количество (объём)»).
13. unit        — единица измерения («кг», «шт», «порц» и т.п.) или null.
14. price       — цена за единицу БЕЗ НДС (графа «Цена за единицу»).
15. amount      — стоимость позиции БЕЗ НДС (графа «Стоимость без налога»).
16. vat_rate    — ставка НДС в процентах (10, 20) или null, если «без НДС».
17. vat_sum     — сумма НДС по позиции или null.

СХЕМА ОТВЕТА
{
  "supplier":        {"name": "строка", "inn": "строка или null"},
  "buyer_inn":       "строка или null",
  "document_number": "строка",
  "document_date":   "YYYY-MM-DD",
  "delivery_address": "строка или null",
  "items": [
    {
      "name":     "строка",
      "quantity": число,
      "unit":     "строка или null",
      "price":    число или null,
      "amount":   число,
      "vat_rate": число или null,
      "vat_sum":  число или null
    }
  ]
}

ПРИМЕР КОРРЕКТНОГО ОТВЕТА
{
  "supplier": {"name": "ООО \\"Камелот\\"", "inn": "5190052187"},
  "buyer_inn": "230907402771",
  "document_number": "47536",
  "document_date": "2026-05-07",
  "delivery_address": "Мурманская обл, Мурманск г, Домостроительная ул, д.8 к.3 кв.6",
  "items": [
    {
      "name": "Шпик боковой зам. весовой 20-25",
      "quantity": 24.92,
      "unit": "кг",
      "price": 143.64,
      "amount": 3579.42,
      "vat_rate": 10,
      "vat_sum": 357.94
    }
  ]
}
"""


class GeminiService:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def extract_invoice_data(self, image_path: Path) -> InvoiceData:
        logger.info("Sending image to Gemini: %s", image_path)

        image_bytes = image_path.read_bytes()
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=self._detect_mime_type(image_path),
        )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[image_part, INVOICE_PROMPT],
        )

        text = response.text
        logger.debug("Gemini raw response: %s", text)

        return self._parse_response(text)

    def _parse_response(self, text: str) -> InvoiceData:
        cleaned = self._strip_markdown(text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse Gemini response as JSON: %s", cleaned)
            raise

        return InvoiceData.model_validate(data)

    @staticmethod
    def _strip_markdown(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[len("```json"):]
        elif cleaned.startswith("```"):
            cleaned = cleaned[len("```"):]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-len("```")]
        return cleaned.strip()

    @staticmethod
    def _detect_mime_type(path: Path) -> str:
        suffix = path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        return mime_map.get(suffix, "image/jpeg")
