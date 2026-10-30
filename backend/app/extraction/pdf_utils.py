"""PyMuPDF helpers: file-type checks, text-layer detection and page -> image rendering."""

from __future__ import annotations

import io

import pymupdf
from PIL import Image

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
SUPPORTED_MIME = (PDF, PNG, JPEG)
MIN_TEXT_WORDS = 5  # a page with fewer words than this is treated as scanned


def guess_mime(file_name: str) -> str | None:
    name = file_name.lower()
    if name.endswith(".pdf"):
        return PDF
    if name.endswith(".png"):
        return PNG
    if name.endswith((".jpg", ".jpeg")):
        return JPEG
    return None


def open_pdf(file_bytes: bytes) -> pymupdf.Document:
    return pymupdf.open(stream=file_bytes, filetype="pdf")


def page_count(file_bytes: bytes, mime: str) -> int:
    return len(open_pdf(file_bytes)) if mime == PDF else 1


def text_layer_pages(file_bytes: bytes, mime: str) -> list[bool]:
    """For each page: does it carry real text (True) or is it an image that needs OCR (False)?"""
    if mime != PDF:
        return [False]
    return [len(page.get_text("words")) >= MIN_TEXT_WORDS for page in open_pdf(file_bytes)]


def render_page_images(file_bytes: bytes, mime: str, dpi: int, max_pages: int | None = None) -> list[Image.Image]:
    """Pages as RGB images (an image file is its own single page)."""
    if mime != PDF:
        return [Image.open(io.BytesIO(file_bytes)).convert("RGB")]
    images = []
    for index, page in enumerate(open_pdf(file_bytes)):
        if max_pages is not None and index >= max_pages:
            break
        pix = page.get_pixmap(dpi=dpi)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return images


def encode_image(image: Image.Image, max_bytes: int, max_side: int = 2200) -> tuple[bytes, str]:
    """PNG if it fits, otherwise JPEG at falling quality (and size) until it fits under max_bytes."""
    image = image.copy()
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    if buf.tell() <= max_bytes:
        return buf.getvalue(), PNG
    for quality in (85, 75, 65, 55):
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            return buf.getvalue(), JPEG
    image.thumbnail((image.width * 2 // 3, image.height * 2 // 3))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=60)
    return buf.getvalue(), JPEG
