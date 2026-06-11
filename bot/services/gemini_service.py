import json
from pathlib import Path

from google import genai
from google.genai import types

from bot.core.logger import logger
from bot.schemas.invoice import InvoiceData

from bot.core.prompts import INVOICE_SYSTEM_PROMPT  # noqa: E402

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
            contents=[image_part, INVOICE_SYSTEM_PROMPT],
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
        try:
            return InvoiceData.model_validate(data)
        except Exception as exc:
            # Log full validation error for debugging
            logger.exception("Invoice data validation error: %s", exc)
            raise


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
