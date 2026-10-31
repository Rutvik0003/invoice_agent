"""Stage 1: accept the file - check its type, size and readability, hash it, count pages, find text layers."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import pymupdf
from PIL import Image, UnidentifiedImageError

from app.extraction.pdf_utils import JPEG, PDF, PNG, guess_mime, text_layer_pages

MAX_BYTES = 10 * 1024 * 1024  # files are stored in the database (CLAUDE.md §4)
MAX_PAGES = 20  # one invoice per file; longer documents are statements or bundles, and slow to OCR


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


def check_image(data: bytes) -> None:
    """The image must decode completely (a truncated upload passes a header check but fails later) and not be
    absurdly large (Pillow refuses 'decompression bomb' sizes)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except Image.DecompressionBombError as exc:
        raise IntakeError("The image is too large to process. Upload a smaller photo or a PDF.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise IntakeError("The image could not be read (it may be damaged or incomplete).") from exc


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
        if len(doc) > MAX_PAGES:
            raise IntakeError(f"The PDF has {len(doc)} pages; the limit is {MAX_PAGES} (one invoice per file). "
                              "Upload just the invoice pages.")
        pages = len(doc)
    else:
        check_image(data)
        pages = 1
    return IntakeResult(file_name, mime, hashlib.sha256(data).hexdigest(), len(data), pages, text_layer_pages(data, mime))
