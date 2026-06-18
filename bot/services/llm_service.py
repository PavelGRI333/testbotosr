from __future__ import annotations

import json
import logging
import re
import base64
import tempfile
from pathlib import Path

import httpx
import fitz  # PyMuPDF
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bot.core.config import LLMSettings
from bot.core.prompts import INVOICE_SYSTEM_PROMPT
from bot.schemas.invoice import InvoiceData

logger = logging.getLogger(__name__)

_USER_PROMPT = "Распознай накладную на изображении и верни JSON."


def _strip_fences(text: str) -> str:
    """Извлекает JSON из ответа LLM, удаляя Markdown-обрамление и лишний текст."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        first = text.find("```")
        last = text.rfind("```")
        if first != -1 and last != -1 and last > first:
            inner = text[first + 3:last].strip()
            lines = inner.splitlines()
            if lines and lines[0].strip().lower() == "json":
                inner = "\n".join(lines[1:]).strip()
            return inner
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


class LLMService:
    def __init__(self, settings: LLMSettings) -> None:
        self._model = settings.model
        self._temperature = settings.temperature
        self._base_url = settings.base_url.rstrip("/")
        self._api_key = settings.api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": settings.http_referer or "https://your-bot-domain.com",
            "X-Title": settings.app_title or "Invoice Bot",
            "Content-Type": "application/json",
        }

    def _pdf_first_page_to_jpeg(self, pdf_path: Path) -> Path:
        """Конвертирует первую страницу PDF в JPEG и возвращает путь к временному файлу."""
        doc = fitz.open(pdf_path)
        page = doc[0]  # первая страница
        pix = page.get_pixmap(dpi=300)  # увеличиваем разрешение для лучшего распознавания
        # Сохраняем во временный файл
        temp_jpeg = Path(tempfile.mkstemp(suffix=".jpg", prefix="page_")[1])
        pix.save(temp_jpeg, "jpeg")
        doc.close()
        logger.info("Converted first page of PDF to JPEG: %s", temp_jpeg)
        return temp_jpeg

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    async def extract_invoice_data(
        self,
        file_path: str | Path,
        mime_type: str = "application/pdf",
    ) -> InvoiceData:
        """
        Отправляет файл в OpenRouter.
        Если это PDF, то конвертирует первую страницу в JPEG и отправляет как изображение.
        """
        path = Path(file_path)
        file_size = path.stat().st_size
        logger.info("Processing file: %s, size: %.2f KB", path.name, file_size / 1024)

        # Если это PDF – конвертируем первую страницу в JPEG
        if mime_type == "application/pdf":
            image_path = self._pdf_first_page_to_jpeg(path)
            # теперь работаем с изображением
            actual_mime = "image/jpeg"
            actual_path = image_path
        else:
            actual_mime = mime_type
            actual_path = path

        # Кодируем изображение в base64
        with open(actual_path, "rb") as f:
            b64_content = base64.b64encode(f.read()).decode("ascii")
        data_url = f"data:{actual_mime};base64,{b64_content}"

        # Если это было изображение, отправляем как image_url, чтобы модель лучше понимала
        # Для OpenRouter лучше использовать тип "image_url" для изображений
        content_parts = [
            {"type": "text", "text": _USER_PROMPT},
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            },
        ]

        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": INVOICE_SYSTEM_PROMPT},
                {"role": "user", "content": content_parts},
            ],
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=self._headers,
            )
            if response.status_code != 200:
                logger.error("OpenRouter error: %s", response.text)
            response.raise_for_status()
            result = response.json()
            raw = result["choices"][0]["message"]["content"] or ""
            logger.debug("LLM raw response: %s", raw)

            clean = _strip_fences(raw)
            try:
                parsed = json.loads(clean)
            except json.JSONDecodeError:
                logger.error("Failed to parse LLM response as JSON: %s", raw)
                raise

            try:
                return InvoiceData.model_validate(parsed)
            except Exception as exc:
                logger.exception("Invoice data validation error: %s", exc)
                raise
            finally:
                # Удаляем временный JPEG, если он был создан
                if mime_type == "application/pdf" and actual_path.exists():
                    actual_path.unlink(missing_ok=True)
                    logger.debug("Deleted temporary image: %s", actual_path)