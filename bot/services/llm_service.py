from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bot.core.config import LLMSettings
from bot.core.prompts import INVOICE_SYSTEM_PROMPT
from bot.schemas.invoice import InvoiceData

logger = logging.getLogger(__name__)

_USER_PROMPT = "Распознай накладную на изображении и верни JSON."


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip().removeprefix("json").strip()
    return t.strip()


class LLMService:
    def __init__(self, settings: LLMSettings) -> None:
        self._model = settings.model
        self._temperature = settings.temperature
        headers: dict[str, str] = {}
        if settings.http_referer:
            headers["HTTP-Referer"] = settings.http_referer
        if settings.app_title:
            headers["X-Title"] = settings.app_title
        self._client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            default_headers=headers or None,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    async def extract_invoice_data(
        self,
        file_path: str | Path,
        mime_type: str = "image/jpeg",
    ) -> InvoiceData:
        """Send a file to the LLM and parse the JSON invoice data.

        ``file_path`` – path to the locally saved file (image or PDF).
        ``mime_type`` – MIME type to embed in the data URL; defaults to
        ``image/jpeg`` for backward compatibility.
        """
        path = Path(file_path)
        # Use provided mime_type directly; fallback to guess only if not supplied
        mime = mime_type or mimetypes.guess_type(path.name)[0] or "image/jpeg"
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": INVOICE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )

        raw = response.choices[0].message.content or ""
        logger.debug("LLM raw response: %s", raw)

        try:
            data = json.loads(_strip_fences(raw))
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response as JSON: %s", raw)
            raise

        try:
            return InvoiceData.model_validate(data)
        except Exception as exc:
            logger.exception("Invoice data validation error: %s", exc)
            raise
