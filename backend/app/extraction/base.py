"""Extractor interface: one model call per invoice, Pydantic validation, one repair retry, typed errors."""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod

from PIL import Image
from pydantic import ValidationError

from app.extraction.pdf_utils import SUPPORTED_MIME
from app.extraction.prompt import repair_prompt
from app.schemas import ErrorType, ExtractedInvoice, ExtractionError, ExtractionResult

FRIENDLY = {
    "rate_limited": "{provider} rate limit reached (free tier). Wait a minute, or retry with the other model.",
    "timeout": "{provider} did not answer within the time limit. Retry, or switch to the other model.",
    "invalid_response": "{provider} returned data that could not be read as an invoice, even after one repair attempt.",
    "provider_error": "{provider} reported a problem on its side. Retry, or switch to the other model.",
    "auth_error": "The {provider} API key is missing or invalid. Check {env} in your .env file.",
    "unsupported_file": "This file type cannot be read. Upload a PDF, PNG or JPG.",
}
ENV_NAMES = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}


class ProviderError(Exception):
    """A provider call failed in a known way."""

    def __init__(self, error_type: ErrorType, detail: str = "") -> None:
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail


class InvalidOutput(Exception):
    """The provider answered, but with output that is not usable JSON (carries the text for the repair retry)."""

    def __init__(self, text: str, detail: str) -> None:
        super().__init__(detail)
        self.text = text
        self.detail = detail


def make_error(provider: str, error_type: ErrorType, detail: str = "") -> ExtractionError:
    message = FRIENDLY[error_type].format(provider=provider.capitalize(), env=ENV_NAMES.get(provider, "the API key"))
    return ExtractionError(type=error_type, message=message, detail=detail[:500] or None)


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def parse_invoice(raw: str) -> tuple[ExtractedInvoice | None, str | None]:
    """Turn model text into an ExtractedInvoice, or explain why not."""
    text = _THINK.sub("", raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None, "The answer contained no JSON object."
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "The JSON is not an object."
    try:
        return ExtractedInvoice.model_validate(data), None
    except ValidationError as exc:
        return None, f"JSON does not match the schema: {exc}"


class Extractor(ABC):
    """Reads one invoice with one provider/model."""

    provider: str = ""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @abstractmethod
    def _call(self, file_bytes: bytes, mime: str, page_images: list[Image.Image] | None, repair: str | None) -> str:
        """Send the document (plus the repair note, if any) and return the model's raw text.

        Raises ProviderError for known failures and InvalidOutput when the provider rejects its own output.
        """

    def extract(self, file_bytes: bytes, mime: str, page_images: list[Image.Image] | None = None) -> ExtractionResult:
        """One model call (plus at most one repair call) -> ExtractionResult with an invoice or a typed error."""
        started = time.monotonic()

        def result(**kwargs) -> ExtractionResult:
            return ExtractionResult(model_name=self.model_name, provider=self.provider,
                                    latency_ms=int((time.monotonic() - started) * 1000), **kwargs)

        if mime not in SUPPORTED_MIME:
            return result(error=make_error(self.provider, "unsupported_file", mime))
        try:
            raw = self._call(file_bytes, mime, page_images, None)
            invoice, problem = parse_invoice(raw)
        except InvalidOutput as bad:
            raw, invoice, problem = bad.text, None, bad.detail
        except ProviderError as exc:
            return result(error=make_error(self.provider, exc.error_type, exc.detail))
        if invoice is not None:
            return result(invoice=invoice, raw_response=raw)

        # one repair retry, showing the model its own output and the problem
        try:
            repaired_raw = self._call(file_bytes, mime, page_images, repair_prompt(raw, problem or ""))
            invoice, problem = parse_invoice(repaired_raw)
        except InvalidOutput as bad:
            repaired_raw, invoice, problem = bad.text, None, bad.detail
        except ProviderError as exc:
            return result(error=make_error(self.provider, exc.error_type, exc.detail), raw_response=raw)
        if invoice is None:
            return result(error=make_error(self.provider, "invalid_response", problem or ""), raw_response=repaired_raw,
                          repaired=True)
        return result(invoice=invoice, raw_response=repaired_raw, repaired=True)
