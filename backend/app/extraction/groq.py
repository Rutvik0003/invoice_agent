"""Groq extractor: renders pages to images (max 5, ~150 DPI, size-limited) for a vision model, JSON mode."""

from __future__ import annotations

import base64
import re

import groq
from PIL import Image

from app.extraction.base import Extractor, InvalidOutput, ProviderError
from app.extraction.pdf_utils import encode_image, render_page_images
from app.extraction.prompt import COMPACT_NOTE, SYSTEM_PROMPT, user_prompt

MAX_PAGES = 5
DPI = 150
MAX_IMAGE_BYTES = 3_000_000  # Groq limits base64 image payloads; stay well under
# Groq's free tier allows ~7,000 input and ~1,000 output tokens per minute for this model and rejects any
# request expected to exceed them, so page images are kept modest and the answer compact and capped.
MAX_SIDE = 1400  # long side in pixels: still readable for an A4 page
MAX_OUTPUT_TOKENS = 1000


TOO_LARGE = ("This invoice is too large for Groq's free tier (it allows about 1,000 output and 7,000 input "
             "tokens per minute; long or multi-page invoices exceed that on every attempt). Retry with Gemini.")


def map_groq_error(exc: Exception) -> ProviderError | InvalidOutput:
    """Translate SDK exceptions into our error types (JSON-mode failures go to the repair retry)."""
    if isinstance(exc, groq.APIStatusError) and "request too large" in str(exc).lower():
        # a per-request size cap, not a passing rate limit: waiting will not help
        return ProviderError("rate_limited", str(exc), message=TOO_LARGE)
    if isinstance(exc, groq.APITimeoutError):
        return ProviderError("timeout", str(exc))
    if isinstance(exc, groq.RateLimitError):
        text = str(exc)
        if "per day" in text:  # the daily allowance, not a short burst limit
            wait = re.search(r"try again in ([\dhms.]+)", text)
            return ProviderError("rate_limited", text, message="Groq's free daily token allowance is used up"
                                 + (f" (it frees up in about {wait.group(1).split('.')[0]}s)" if wait else "")
                                 + ". Retry with Gemini, or try Groq again later.")
        return ProviderError("rate_limited", text)
    if isinstance(exc, (groq.AuthenticationError, groq.PermissionDeniedError)):
        return ProviderError("auth_error", str(exc))
    if isinstance(exc, groq.BadRequestError):
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error", body) if isinstance(body, dict) else {}
        if isinstance(error, dict) and error.get("code") == "json_validate_failed":
            return InvalidOutput(str(error.get("failed_generation") or ""), "Output was not valid JSON")
        return ProviderError("provider_error", str(exc))
    if isinstance(exc, groq.APIConnectionError):
        return ProviderError("provider_error", f"network: {exc}")
    if isinstance(exc, groq.APIStatusError):
        return ProviderError("rate_limited" if exc.status_code == 429 else "provider_error", str(exc))
    return ProviderError("provider_error", f"{type(exc).__name__}: {exc}")


class GroqExtractor(Extractor):
    provider = "groq"

    def __init__(self, api_key: str, model_name: str, timeout_s: int = 60, client: object | None = None) -> None:
        super().__init__(model_name)
        if client is None and not api_key:
            raise ProviderError("auth_error", "GROQ_API_KEY is not set")
        # no hidden SDK retries: a rate limit must surface so the user can choose to retry or switch
        self.client = client or groq.Groq(api_key=api_key, timeout=timeout_s, max_retries=0)

    def _images(self, file_bytes: bytes, mime: str, page_images: list[Image.Image] | None) -> list[dict]:
        pages = (page_images or render_page_images(file_bytes, mime, DPI, MAX_PAGES))[:MAX_PAGES]
        parts = []
        for page in pages:
            data, image_mime = encode_image(page, MAX_IMAGE_BYTES, MAX_SIDE)
            url = f"data:{image_mime};base64,{base64.b64encode(data).decode()}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
        return parts

    def _call(self, file_bytes: bytes, mime: str, page_images: list[Image.Image] | None, repair: str | None) -> str:
        text = SYSTEM_PROMPT + "\n\n" + user_prompt() + "\n" + COMPACT_NOTE + (f"\n\n{repair}" if repair else "")
        messages = [{"role": "user", "content": [{"type": "text", "text": text}, *self._images(file_bytes, mime, page_images)]}]
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
                max_completion_tokens=MAX_OUTPUT_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 - every failure becomes a typed error
            raise map_groq_error(exc) from exc
        return response.choices[0].message.content or ""
