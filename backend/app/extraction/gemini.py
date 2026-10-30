"""Google Gemini extractor: sends the PDF (or image) directly, with structured JSON output."""

from __future__ import annotations

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image

from app.extraction.base import Extractor, ProviderError
from app.extraction.prompt import SYSTEM_PROMPT, json_schema, user_prompt


def map_gemini_error(exc: Exception) -> ProviderError:
    """Translate SDK / network exceptions into our error types."""
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return ProviderError("timeout", str(exc))
    if isinstance(exc, genai_errors.APIError):
        code = exc.code or 0
        text = f"{code} {exc.status or ''} {exc.message or ''}"
        if code == 429:
            return ProviderError("rate_limited", text)
        if code in (401, 403) or (code == 400 and "api key" in text.lower()) or "API_KEY_INVALID" in text:
            return ProviderError("auth_error", text)
        if code == 504 or "DEADLINE" in text.upper():
            return ProviderError("timeout", text)
        return ProviderError("provider_error", text)
    if isinstance(exc, httpx.HTTPError):
        return ProviderError("provider_error", f"network: {exc}")
    return ProviderError("provider_error", f"{type(exc).__name__}: {exc}")


class GeminiExtractor(Extractor):
    provider = "gemini"

    def __init__(self, api_key: str, model_name: str, timeout_s: int = 60, client: object | None = None) -> None:
        super().__init__(model_name)
        if client is None and not api_key:
            raise ProviderError("auth_error", "GEMINI_API_KEY is not set")
        self.client = client or genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_s * 1000))

    def _call(self, file_bytes: bytes, mime: str, page_images: list[Image.Image] | None, repair: str | None) -> str:
        contents: list = [types.Part.from_bytes(data=file_bytes, mime_type=mime), user_prompt()]
        if repair:
            contents.append(repair)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=json_schema(),
        )
        try:
            response = self.client.models.generate_content(model=self.model_name, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a typed error
            raise map_gemini_error(exc) from exc
        return response.text or ""
