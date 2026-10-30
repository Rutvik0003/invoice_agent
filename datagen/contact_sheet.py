"""Thumbnail grids of generated invoices, and box-check images that draw field boxes on a page."""

from __future__ import annotations

import math
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from datagen.labels import Label

THUMB_W = 300
CAPTION_H = 34


def first_page(path: Path, page: int = 1, dpi: int = 60) -> Image.Image:
    if path.suffix.lower() == ".pdf":
        pix = pymupdf.open(path)[page - 1].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return Image.open(path).convert("RGB")


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def contact_sheet(items: list[tuple[Path, Label]], out_path: Path, columns: int = 6) -> None:
    """Grid of first-page thumbnails captioned with id, scenario and expected decision."""
    rows = math.ceil(len(items) / columns)
    cell_h = int(THUMB_W * 1.42) + CAPTION_H
    sheet = Image.new("RGB", (columns * (THUMB_W + 10) + 10, rows * (cell_h + 10) + 10), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (path, label) in enumerate(items):
        thumb = first_page(path)
        thumb.thumbnail((THUMB_W, int(THUMB_W * 1.42)))
        x = 10 + (index % columns) * (THUMB_W + 10)
        y = 10 + (index // columns) * (cell_h + 10)
        sheet.paste(thumb, (x, y))
        draw.rectangle([x, y, x + thumb.width, y + thumb.height], outline=(180, 180, 180))
        draw.text((x, y + int(THUMB_W * 1.42) + 3), f"{label.invoice_id}  {label.expected_decision}", fill="black", font=_font(14))
        extra = f"{label.scenario} | {label.template}{' | ' + label.scan_level + ' scan' if label.is_scanned else ''}"
        draw.text((x, y + int(THUMB_W * 1.42) + 19), extra[:48], fill=(90, 90, 90), font=_font(11))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, optimize=True)


def box_check(path: Path, label: Label, out_path: Path) -> None:
    """The first page with every recorded field box drawn on it (red = obscured field)."""
    page = first_page(path, dpi=110)
    draw = ImageDraw.Draw(page)
    for name, box in label.field_boxes.items():
        if box.page != 1:
            continue
        x0, y0, x1, y1 = box.bbox[0] * page.width, box.bbox[1] * page.height, box.bbox[2] * page.width, box.bbox[3] * page.height
        colour = (220, 30, 30) if name in label.obscured_fields else (20, 160, 60)
        draw.rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], outline=colour, width=2)
        draw.text((x0, max(0, y0 - 12)), name, fill=colour, font=_font(10))
    page.save(out_path, optimize=True)
