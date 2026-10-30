"""Stage 1: accept the file - check its type, size and readability, hash it, count pages, find text layers."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import pymupdf
from PIL import Image, UnidentifiedImageError

from app.extraction.pdf_utils import JPEG, PDF, PNG, guess_mime, text_layer_pages

MAX_BYTES = 10 * 1024 * 1024  # files are stored in the database (CLAUDE.md §4)


class IntakeError(ValueError):
    """The file cannot be processed; the message is shown to the user."""


@dataclass
class IntakeResult:
    file_name: str
    mime: str
    file_hash: str
    size_bytes: int
    page_count: int
    text_layer: list[bool]  # per page: has real text (True) or needs OCR (False)


def sniff_mime(file_name: str, data: bytes) -> str | None:
    """Trust the file's first bytes over its name."""
    if data[:5] == b"%PDF-":
        return PDF
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return PNG
    if data[:3] == b"\xff\xd8\xff":
        return JPEG
    return guess_mime(file_name)


def intake(file_name: str, data: bytes) -> IntakeResult:
    """Accept PDF/PNG/JPG up to 10 MB; reject empty, unreadable or password-protected files with a clear reason."""
    if not data:
        raise IntakeError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise IntakeError(f"The file is {len(data) / 1024 / 1024:.1f} MB; the limit is 10 MB.")
    mime = sniff_mime(file_name, data)
    if mime not in (PDF, PNG, JPEG):
        raise IntakeError("Unsupported file type. Upload a PDF, PNG or JPG invoice.")
    if mime == PDF:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 - any parse failure means the PDF is unusable
            raise IntakeError("The PDF could not be opened (it may be damaged).") from exc
        if doc.needs_pass:
            raise IntakeError("The PDF is password-protected. Upload an unprotected copy.")
        if len(doc) == 0:
            raise IntakeError("The PDF has no pages.")
        pages = len(doc)
    else:
        try:
            Image.open(io.BytesIO(data)).verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise IntakeError("The image could not be read (it may be damaged).") from exc
        pages = 1
    return IntakeResult(file_name, mime, hashlib.sha256(data).hexdigest(), len(data), pages, text_layer_pages(data, mime))
