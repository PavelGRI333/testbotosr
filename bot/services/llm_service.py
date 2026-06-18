from __future__ import annotations

import json
import logging
import re
import base64
import tempfile
from pathlib import Path

import httpx
import fitz
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bot.core.config import LLMSettings
from bot.core.prompts import INVOICE_SYSTEM_PROMPT
from bot.schemas.invoice import InvoiceData

logger = logging.getLogger(__name__)

_USER_PROMPT = "Распознай накладную на изображении и верни JSON. Используй ТОЛЬКО первое изображение для списка товаров. Адрес и поставщика ищи на любой странице."


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

    def _pdf_pages_to_images(self, pdf_path: Path, max_pages: int = 3) -> list[Path]:
        """Конвертирует первые max_pages страниц PDF в JPEG и возвращает список временных файлов."""
        doc = fitz.open(pdf_path)
        total_pages = min(len(doc), max_pages)
        images = []
        for i in range(total_pages):
            page = doc[i]
            pix = page.get_pixmap(dpi=200)  # снизили с 300 до 200
            temp_jpeg = Path(tempfile.mkstemp(suffix=f"_page{i + 1}.jpg", prefix="pdf_")[1])
            pix.save(temp_jpeg, "jpeg")
            images.append(temp_jpeg)
            logger.info("Converted page %d to JPEG: %s", i + 1, temp_jpeg)
        doc.close()
        return images

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
        Если это PDF, конвертирует первые 4 страницы в JPEG и отправляет как несколько изображений.
        """
        path = Path(file_path)
        file_size = path.stat().st_size
        logger.info("Processing file: %s, size: %.2f KB", path.name, file_size / 1024)

        # Если это PDF – конвертируем страницы в изображения
        if mime_type == "application/pdf":
            image_paths = self._pdf_pages_to_images(path, max_pages=3)
            actual_mime = "image/jpeg"
        else:
            image_paths = [path]
            actual_mime = mime_type

        # Собираем контент: сначала текст, затем все изображения
        content_parts = [{"type": "text", "text": _USER_PROMPT}]
        for img_path in image_paths:
            with open(img_path, "rb") as f:
                b64_content = base64.b64encode(f.read()).decode("ascii")
            data_url = f"data:{actual_mime};base64,{b64_content}"
            content_parts.append({"type": "image_url", "image_url": {"url": data_url}})

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
                # Удаляем все временные JPEG-файлы, если они были созданы для PDF
                if mime_type == "application/pdf":
                    for img_path in image_paths:
                        if img_path.exists():
                            img_path.unlink(missing_ok=True)
                            logger.debug("Deleted temporary image: %s", img_path)