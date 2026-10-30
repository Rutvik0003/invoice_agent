"""Tests for Stage 2 extraction using recorded provider responses and fake clients (no network)."""

from pathlib import Path
from types import SimpleNamespace

import groq
import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import Settings
from app.db import make_engine
from app.extraction import extract_document, file_hash
from app.extraction.base import Extractor, InvalidOutput, ProviderError, parse_invoice
from app.extraction.cache import get_cached, put_cached
from app.extraction.gemini import GeminiExtractor, map_gemini_error
from app.extraction.groq import GroqExtractor, map_groq_error
from app.extraction.prompt import json_schema, user_prompt
from app.models import Base
from app.schemas import ExtractedInvoice

FIXTURES = Path(__file__).parent / "fixtures"
GEMINI_RAW = (FIXTURES / "gemini_golden01_response.json").read_text(encoding="utf-8")
GROQ_RAW = (FIXTURES / "groq_golden01_response.json").read_text(encoding="utf-8")
PDF = b"%PDF-1.4 fake"


class ScriptedExtractor(Extractor):
    """Returns (or raises) the scripted answers in order and records what it was asked."""

    provider = "gemini"

    def __init__(self, answers):
        super().__init__("test-model")
        self.answers = list(answers)
        self.repairs = []

    def _call(self, file_bytes, mime, page_images, repair):
        self.repairs.append(repair)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


# ---------------------------------------------------------------- parsing


def test_recorded_gemini_response_parses_to_the_printed_values():
    invoice, problem = parse_invoice(GEMINI_RAW)
    assert problem is None
    assert invoice.invoice_number.value == "VE0393"
    assert invoice.vendor_gstin.value == "27TSSPN3544X1ZU"
    assert invoice.total_amount.value == 167723.0
    assert invoice.igst.value is None
    assert len(invoice.line_items) == 6


def test_recorded_groq_response_parses_including_its_mistakes():
    invoice, _ = parse_invoice(GROQ_RAW)
    assert invoice.invoice_number.value == "VE0393"
    assert invoice.vendor_gstin.value == "27TSSPN3544XIZU"  # Groq misread '1' as 'I' - Stage 3 must catch this


def test_parse_handles_fences_thinking_and_printed_numbers():
    raw = '<think>looking at the page</think>\n```json\n{"total_amount": {"value": "Rs. 1,18,000/-", "confidence": 0.9}}\n```'
    invoice, problem = parse_invoice(raw)
    assert problem is None and invoice.total_amount.value == 118000.0


@pytest.mark.parametrize("raw", ["", "no json here", "[1, 2]", '{"total_amount": {"value": "abc"}}',
                                 '{"document_type": {"value": "invoice-ish"}}'])
def test_parse_rejects_unusable_output(raw):
    invoice, problem = parse_invoice(raw)
    assert invoice is None and problem


def test_absent_fields_stay_null():
    invoice, _ = parse_invoice('{"invoice_number": {"value": null, "confidence": 0.9}}')
    assert invoice.invoice_number.value is None
    assert invoice.po_reference.value is None and invoice.line_items == []


def test_schema_requires_every_key_and_prompt_lists_every_field():
    schema = json_schema()
    assert set(schema["required"]) == set(ExtractedInvoice.model_fields)
    text_field = schema["$defs"]["TextField"]
    assert set(text_field["required"]) == {"value", "printed", "confidence", "evidence"}
    assert all(name in user_prompt() for name in ExtractedInvoice.model_fields)


# ---------------------------------------------------------------- repair retry


def test_one_repair_retry_fixes_bad_json():
    extractor = ScriptedExtractor(['{"total_amount": }', GEMINI_RAW])
    result = extractor.extract(PDF, "application/pdf")
    assert result.invoice is not None and result.repaired
    assert extractor.repairs[0] is None and "Invalid JSON" in extractor.repairs[1]


def test_second_bad_answer_is_invalid_response():
    result = ScriptedExtractor(["{not json", "still not json"]).extract(PDF, "application/pdf")
    assert result.invoice is None and result.error.type == "invalid_response" and result.repaired


def test_provider_rejected_json_goes_to_repair():
    result = ScriptedExtractor([InvalidOutput("{bad", "Output was not valid JSON"), GROQ_RAW]).extract(PDF, "application/pdf")
    assert result.invoice is not None and result.repaired


def test_provider_errors_become_typed_errors_with_friendly_messages():
    result = ScriptedExtractor([ProviderError("rate_limited", "429 quota")]).extract(PDF, "application/pdf")
    assert result.error.type == "rate_limited"
    assert "rate limit" in result.error.message.lower() and "other model" in result.error.message
    assert result.error.detail == "429 quota"


def test_unsupported_file_type():
    result = ScriptedExtractor([]).extract(b"hello", "text/plain")
    assert result.error.type == "unsupported_file"


# ---------------------------------------------------------------- providers with fake clients


def test_gemini_sends_the_pdf_with_schema_and_temperature_zero():
    calls = []

    def generate_content(model, contents, config):
        calls.append((model, contents, config))
        return SimpleNamespace(text=GEMINI_RAW)

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result = GeminiExtractor("", "gemini-test", client=client).extract(PDF, "application/pdf")
    assert result.invoice.invoice_number.value == "VE0393" and result.provider == "gemini"
    model, contents, config = calls[0]
    assert model == "gemini-test"
    assert contents[0].inline_data.mime_type == "application/pdf" and contents[0].inline_data.data == PDF
    assert config.temperature == 0 and config.response_json_schema == json_schema()


def test_groq_sends_page_images_and_json_mode():
    from PIL import Image

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=GROQ_RAW))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    pages = [Image.new("RGB", (800, 1100), "white") for _ in range(7)]
    result = GroqExtractor("", "vision-test", client=client).extract(PDF, "application/pdf", page_images=pages)
    assert result.invoice is not None
    sent = calls[0]
    images = [part for part in sent["messages"][0]["content"] if part["type"] == "image_url"]
    assert len(images) == 5  # max 5 pages
    assert sent["response_format"] == {"type": "json_object"} and sent["temperature"] == 0


def _gemini_error(code: int, message: str) -> genai_errors.APIError:
    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_gemini_error(429, "Resource exhausted"), "rate_limited"),
        (_gemini_error(400, "API key not valid. Please pass a valid API key."), "auth_error"),
        (_gemini_error(403, "Permission denied"), "auth_error"),
        (_gemini_error(503, "The model is overloaded"), "provider_error"),
        (_gemini_error(504, "Deadline exceeded"), "timeout"),
        (httpx.ReadTimeout("timed out"), "timeout"),
        (RuntimeError("boom"), "provider_error"),
    ],
)
def test_gemini_error_mapping(exc, expected):
    assert map_gemini_error(exc).error_type == expected


def _groq_status(cls, code: int, body=None):
    response = httpx.Response(code, request=httpx.Request("POST", "https://api.groq.com/x"))
    return cls("error", response=response, body=body)


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_groq_status(groq.RateLimitError, 429), "rate_limited"),
        (_groq_status(groq.AuthenticationError, 401), "auth_error"),
        (_groq_status(groq.InternalServerError, 500), "provider_error"),
        (groq.APITimeoutError(request=httpx.Request("POST", "https://api.groq.com/x")), "timeout"),
        (_groq_status(groq.BadRequestError, 400, {"error": {"code": "model_decommissioned"}}), "provider_error"),
    ],
)
def test_groq_error_mapping(exc, expected):
    assert map_groq_error(exc).error_type == expected


def test_groq_json_validation_failure_goes_to_repair():
    exc = _groq_status(groq.BadRequestError, 400, {"error": {"code": "json_validate_failed", "failed_generation": "{bad"}})
    mapped = map_groq_error(exc)
    assert isinstance(mapped, InvalidOutput) and mapped.text == "{bad"


# ---------------------------------------------------------------- service + cache


def test_missing_model_or_key_is_a_clean_auth_error():
    settings = Settings(_env_file=None, gemini_api_key="", gemini_model="")
    result = extract_document(PDF, "application/pdf", "gemini", settings)
    assert result.error.type == "auth_error" and "GEMINI_API_KEY" in result.error.message
    settings = Settings(_env_file=None, groq_api_key="", groq_model="some-model")
    assert extract_document(PDF, "application/pdf", "groq", settings).error.type == "auth_error"


def test_cache_round_trip_marks_result_cached(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    Base.metadata.create_all(engine)
    result = ScriptedExtractor([GEMINI_RAW]).extract(PDF, "application/pdf")
    digest = file_hash(PDF)
    assert get_cached(engine, digest, "gemini", "test-model") is None
    put_cached(engine, digest, result)
    cached = get_cached(engine, digest, "gemini", "test-model")
    assert cached.cached and cached.invoice == result.invoice
    assert get_cached(engine, digest, "gemini", "other-model") is None
    failed = ScriptedExtractor([ProviderError("timeout")]).extract(b"%PDF-other", "application/pdf")
    put_cached(engine, file_hash(b"%PDF-other"), failed)  # errors are never cached
    assert get_cached(engine, file_hash(b"%PDF-other"), "gemini", "test-model") is None
    engine.dispose()


def test_groq_request_too_large_says_switch_to_gemini_not_wait():
    exc = _groq_status(groq.RateLimitError, 429)
    exc = groq.RateLimitError("Request too large for model on output tokens per minute (OTPM): Limit 1000",
                              response=exc.response, body=None)
    mapped = map_groq_error(exc)
    assert mapped.error_type == "rate_limited" and "Retry with Gemini" in mapped.message
    result = ScriptedExtractor([mapped]).extract(PDF, "application/pdf")
    assert "too large for Groq" in result.error.message
