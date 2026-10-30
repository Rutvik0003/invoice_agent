"""Tesseract OCR: words, boxes and confidences for scanned pages (word extraction in Phase 3)."""

from pydantic import BaseModel
import pytesseract

from app.config import Settings


class OcrStatus(BaseModel):
    available: bool
    version: str | None


def configure_tesseract(settings: Settings) -> None:
    """Point pytesseract at TESSERACT_CMD when set; otherwise it uses `tesseract` from PATH."""
    if settings.tesseract_cmd.strip():
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd.strip()


def tesseract_status(settings: Settings) -> OcrStatus:
    """Report whether Tesseract can be run; any failure means 'unavailable', never an exception."""
    try:
        configure_tesseract(settings)
        return OcrStatus(available=True, version=str(pytesseract.get_tesseract_version()))
    except Exception:
        return OcrStatus(available=False, version=None)
