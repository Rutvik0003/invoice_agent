"""Words and boxes from a PDF page's text layer (exact text, no OCR needed)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf


@dataclass
class Word:
    text: str
    bbox: tuple[float, float, float, float]  # normalised 0-1, origin top-left
    line: tuple  # words sharing a line key are on the same printed line
    conf: float | None = None  # OCR word confidence 0-100 (None for the text layer)


@dataclass
class PageWords:
    page: int  # 1-based
    source: str  # text_layer | ocr | unavailable
    words: list[Word] = field(default_factory=list)
    error: str | None = None

    @property
    def mean_conf(self) -> float | None:
        confs = [w.conf for w in self.words if w.conf is not None]
        return round(sum(confs) / len(confs), 1) if confs else None

    def to_json(self) -> dict:
        return {"page": self.page, "source": self.source,
                "words": [[w.text, list(w.bbox), list(w.line), w.conf] for w in self.words]}

    @classmethod
    def from_json(cls, data: dict) -> "PageWords":
        return cls(data["page"], data["source"],
                   [Word(t, tuple(b), tuple(line), c) for t, b, line, c in data["words"]])


def text_layer_words(page: pymupdf.Page, page_no: int) -> PageWords:
    """PyMuPDF words: (x0, y0, x1, y1, text, block, line, word_no) -> normalised Words."""
    w, h = page.rect.width, page.rect.height
    words = [
        Word(text, (x0 / w, y0 / h, x1 / w, y1 / h), (block, line))
        for x0, y0, x1, y1, text, block, line, _ in page.get_text("words")
        if text.strip()
    ]
    return PageWords(page_no, "text_layer", words)
