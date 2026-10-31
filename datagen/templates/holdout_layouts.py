"""Three layouts used ONLY for the held-out test set (data/invoices/holdout). They were written after the
pipeline was tuned, so they show how it handles invoice designs it has never seen:

- bilingual: Hindi + English labels (Devanagari), key-value header grid
- receipt:   a narrow, monospaced, retail-receipt column with dashed rules and "qty x rate" lines
- stacked:   inverted (white-on-dark) header, labels printed ABOVE their values, boxed totals panel

Like the other layouts, each records where key values were printed (field boxes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from datagen.formats import format_number
from datagen.invoice_spec import InvoiceSpec
from datagen.templates.base import (
    FONT_FILES,
    GREY,
    LIGHT,
    Column,
    Doc,
    RenderResult,
    _find_font,
    _registered,
    bank_block,
    buyer_block,
    draw_table,
    line_amount,
    line_qty,
    line_rate,
    meta_rows,
    notes_block,
    signature_block,
    totals_rows,
    vendor_block,
    words_block,
)

M = 40
FONT_FILES.setdefault("trebuchet", ("trebuc.ttf", "trebucbd.ttf"))
FONT_FILES.setdefault("consolas", ("consola.ttf", "consolab.ttf"))
HINDI = "nirmala"


def _register_hindi() -> None:
    """Nirmala UI ships as a font collection (.ttc); register its first face for both weights."""
    for bold in (False, True):
        name = f"{HINDI}-{'bold' if bold else 'regular'}"  # the names font_name() looks up
        if name not in _registered:
            pdfmetrics.registerFont(TTFont(name, str(_find_font("Nirmala.ttc")), subfontIndex=0))
            _registered.add(name)
    FONT_FILES.setdefault(HINDI, ("Nirmala.ttc", "Nirmala.ttc"))


# Hindi words chosen to render correctly without complex text shaping (no conjuncts or pre-base vowel signs)
HI = {
    "title": "कर बीजक", "invoice_no": "बीजक नं.", "date": "तारीख", "po": "खरीद आदेश", "seller": "बेचने वाला",
    "buyer": "खरीदार", "subtotal": "उप योग", "tax": "कर", "total": "कुल योग", "bank": "बैंक", "words": "शब्दों में",
}


def _hi(doc: Doc, x: float, y: float, s: str, size: float, align: str = "left", color=GREY) -> float:
    return doc.text(x, y, s, size, family=HINDI, color=color, align=align)


def _page_guard(doc: Doc, spec: InvoiceSpec, y: float, need: float, top: float = 56) -> float:
    """Start a new page (with a small running header) when the next block would not fit."""
    if y + need <= doc.h - 50:
        return y
    doc.text(doc.w - M, doc.h - 30, "Continued on next page...", 7.5, color=GREY, align="right")
    doc.new_page()
    doc.text(M, 40, spec.vendor_name_printed, 9, bold=True)
    return top


def _continued(doc: Doc, spec: InvoiceSpec) -> Callable[[], float]:
    def handler() -> float:
        return _page_guard(doc, spec, doc.h, 1)
    return handler


def _columns(total: float) -> list[Column]:
    fixed = 22 + 48 + 40 + 34 + 62 + 34 + 72
    return [
        Column("#", 22, "center", lambda l, i: str(i)),
        Column("Item / Description", total - fixed, "left", lambda l, i: l.description, wrap=True),
        Column("HSN/SAC", 48, "center", lambda l, i: l.hsn_sac),
        Column("Qty", 40, "right", line_qty),
        Column("Unit", 34, "center", lambda l, i: l.unit),
        Column("Rate", 62, "right", line_rate),
        Column("GST %", 34, "right", lambda l, i: f"{l.gst_rate:g}"),
        Column("Amount", 72, "right", line_amount),
    ]


# ---------------------------------------------------------------- 1. bilingual (Hindi + English)


def render_bilingual(spec: InvoiceSpec, path: Path) -> RenderResult:
    _register_hindi()
    doc = Doc(path, "trebuchet")
    band = HexColor("#7A3E00")
    doc.rect(M, 30, doc.w - 2 * M, 30, stroke=None, fill=HexColor("#FFF3E0"))
    _hi(doc, doc.w / 2 - 6, 50, HI["title"] + "  /", 13, align="right", color=band)
    doc.text(doc.w / 2, 50, spec.title.upper(), 13, bold=True, color=band)
    _hi(doc, M, 80, HI["seller"], 8)
    y_left = vendor_block(doc, spec, M, 94, 250, name_size=12, size=8)
    # header grid: Hindi label / English label | value
    gx, gy, label_w, value_w = doc.w - M - 250, 74, 120, 130
    hi_labels = {"invoice_number": HI["invoice_no"], "invoice_date": HI["date"], "po_reference": HI["po"]}
    for label, value, field in meta_rows(spec):
        doc.rect(gx, gy, label_w, 22, stroke=GREY, fill=LIGHT, line_width=0.4)
        doc.rect(gx + label_w, gy, value_w, 22, stroke=GREY, line_width=0.4)
        if field in hi_labels:
            _hi(doc, gx + 4, gy + 9, hi_labels[field], 6.5)
            doc.text(gx + 4, gy + 18, label, 6.5, color=GREY)
        else:
            doc.text(gx + 4, gy + 14, label, 7, color=GREY)
        doc.text(gx + label_w + 5, gy + 15, value, 8.5, bold=True, field=field)
        gy += 22
    y = max(y_left, gy) + 12
    _hi(doc, M, y, HI["buyer"], 8)
    y = buyer_block(doc, spec, M, y + 13, 300, "Bill To", size=8) + 10
    y = draw_table(doc, M, y, _columns(doc.w - 2 * M), spec.lines, size=7.5, header_fill=HexColor("#FFE0B2"),
                   on_page_break=_continued(doc, spec), bottom_limit=doc.h - 70)
    y = _page_guard(doc, spec, y + 16, 190)
    # totals with Hindi labels for the main rows
    lx, vx, ty = doc.w - M - 230, doc.w - M, y
    hi_rows = {"subtotal": HI["subtotal"], "cgst": HI["tax"], "sgst": HI["tax"], "igst": HI["tax"], "total_amount": HI["total"]}
    for label, value, field, is_total in totals_rows(spec):
        size = 10 if is_total else 8.5
        if field in hi_rows:
            w = _hi(doc, lx, ty, hi_rows[field] + " /", size - 1)
            doc.text(lx + w + 4, ty, label, size, bold=is_total)
        else:
            doc.text(lx, ty, label, size)
        doc.text(vx, ty, value, size, bold=is_total, align="right", field=field)
        ty += size * 1.6
    if spec.words_text:
        _hi(doc, M, y, HI["words"], 7.5)
        words_block(doc, spec, M, y + 12, 260, size=7.5, label="Amount in words")
    if spec.bank_account:
        _hi(doc, M, y + 64, HI["bank"], 7.5)
        bank_block(doc, spec, M, y + 76, size=7.5)
    y = max(ty, y + 120) + 6
    notes_block(doc, spec, M, y, 300, size=7)
    signature_block(doc, spec, doc.w - M, y, size=8)
    return doc.save()


# ---------------------------------------------------------------- 2. receipt (narrow monospaced column)


def render_receipt(spec: InvoiceSpec, path: Path) -> RenderResult:
    doc = Doc(path, "consolas")
    width = 300
    x0, x1 = (doc.w - width) / 2, (doc.w + width) / 2
    size = 8.2

    def rule(y: float) -> float:
        doc.line(x0, y, x1, y, color=GREY, width=0.6, dash=[2, 2])
        return y + size * 1.3

    def guard(y: float, need: float) -> float:
        if y + need <= doc.h - 40:
            return y
        doc.text(x1, doc.h - 25, "contd...", size - 1, color=GREY, align="right")
        doc.new_page()
        return 50

    y = 50
    doc.text(doc.w / 2, y, spec.vendor_name_printed, 11, bold=True, align="center", field="vendor_name")
    y += 14
    for line in doc.wrap(spec.vendor.address, width, size - 0.5):
        doc.text(doc.w / 2, y, line, size - 0.5, color=GREY, align="center")
        y += size * 1.25
    gstin = spec.gstin_text(spec.vendor.gstin)
    if gstin:
        doc.label_value(x0, y, "GSTIN", gstin, size, field="vendor_gstin", bold_value=True)
        y += size * 1.4
    y = rule(y + 2)
    doc.text(doc.w / 2, y, spec.title.upper(), 10, bold=True, align="center")
    y += size * 1.8
    for label, value, field in meta_rows(spec, include_due=False):
        doc.text(x0, y, label, size, color=GREY)
        doc.text(x1, y, value, size, bold=True, align="right", field=field)
        y += size * 1.35
    y = rule(y + 2)
    doc.text(x0, y, "Billed to:", size, color=GREY)
    y += size * 1.35
    doc.text(x0, y, spec.buyer.name, size, bold=True)
    y += size * 1.35
    buyer_gstin = spec.gstin_text(spec.buyer.gstin)
    if buyer_gstin:
        doc.label_value(x0, y, "GSTIN", buyer_gstin, size, field="buyer_gstin")
        y += size * 1.35
    y = rule(y + 2)
    for index, line in enumerate(spec.lines, start=1):
        y = guard(y, size * 4)
        for part in doc.wrap(f"{index}. {line.description} (HSN {line.hsn_sac})", width, size):
            doc.text(x0, y, part, size)
            y += size * 1.25
        doc.text(x0 + 12, y, f"{line.quantity:,} {line.unit} x {format_number(line.unit_price)}  @{line.gst_rate:g}%",
                 size, color=GREY)
        doc.text(x1, y, format_number(line.amount), size, align="right")
        y += size * 1.5
    y = guard(rule(y), size * 12)
    for label, value, field, is_total in totals_rows(spec):
        s = size + 1.5 if is_total else size
        doc.text(x0, y, label.upper() if is_total else label, s, bold=is_total)
        doc.text(x1, y, value, s, bold=is_total, align="right", field=field)
        y += s * 1.45
    y = rule(y)
    if spec.words_text:
        y = guard(y, size * 4)
        y = doc.paragraph(x0, y, spec.words_text, width, size - 0.5, color=GREY) + 4
    if spec.bank_account:
        y = guard(y, size * 5)
        y = bank_block(doc, spec, x0, y, size=size - 0.5, title="Pay to")
    if spec.po_reference and spec.po_in_notes:
        y = guard(y, size * 3)
        doc.label_value(x0, y, "Against PO", spec.po_reference, size - 0.5, field="po_reference")
        y += size * 1.4
    y = guard(y, size * 3)
    doc.text(doc.w / 2, y + 6, "Thank you!  Goods once sold will not be taken back.", size - 1, color=GREY, align="center")
    return doc.save()


# ---------------------------------------------------------------- 3. stacked (inverted header, labels above values)


def render_stacked(spec: InvoiceSpec, path: Path) -> RenderResult:
    doc = Doc(path, "trebuchet")
    dark = HexColor("#1F2A44")
    doc.rect(0, 0, doc.w, 92, stroke=None, fill=dark)
    doc.text(M, 40, spec.vendor_name_printed, 16, bold=True, color=white, field="vendor_name")
    doc.text(M, 56, spec.vendor.address, 7.5, color=HexColor("#C9D1E3"))
    gstin = spec.gstin_text(spec.vendor.gstin)
    if gstin:
        w = doc.text(M, 74, "GSTIN", 7.5, color=HexColor("#C9D1E3"))
        doc.text(M + w + 6, 74, gstin, 8.5, bold=True, color=white, field="vendor_gstin")
    doc.text(doc.w - M, 48, spec.title.upper(), 18, bold=True, color=white, align="right")
    # labels ABOVE values, in a row of cells
    rows = meta_rows(spec)
    cell = (doc.w - 2 * M) / len(rows)
    for i, (label, value, field) in enumerate(rows):
        x = M + i * cell
        doc.text(x, 116, label.upper(), 6.5, color=GREY)
        doc.text(x, 131, value, 9.5, bold=True, field=field)
    doc.line(M, 142, doc.w - M, 142, color=LIGHT, width=1.2)
    y = buyer_block(doc, spec, M, 160, 260, "INVOICE TO", size=8)
    if spec.bank_account:
        bank_block(doc, spec, doc.w - M - 190, 160, size=8, title="PAYMENT DETAILS")
    y = draw_table(doc, M, max(y, 222) + 10, _columns(doc.w - 2 * M), spec.lines, size=7.5, header_fill=dark,
                   header_color=white, grid=False, zebra=HexColor("#F3F5F9"), on_page_break=_continued(doc, spec),
                   bottom_limit=doc.h - 70)
    y = _page_guard(doc, spec, y + 14, 170)
    # boxed totals panel on the right
    rows_t = totals_rows(spec)
    px, pw = doc.w - M - 220, 220
    doc.rect(px, y, pw, len(rows_t) * 17 + 12, stroke=None, fill=HexColor("#F3F5F9"))
    ty = y + 16
    for label, value, field, is_total in rows_t:
        s = 11 if is_total else 8.5
        if is_total:
            doc.rect(px, ty - 12, pw, 18, stroke=None, fill=dark)
        color = white if is_total else HexColor("#000000")
        doc.text(px + 8, ty, label, s, bold=is_total, color=color)
        doc.text(px + pw - 8, ty, value, s, bold=is_total, align="right", field=field, color=color)
        ty += 17
    words_block(doc, spec, M, y + 10, 250, size=7.5)
    notes_block(doc, spec, M, max(ty, y + 60) + 12, 300, size=7)
    signature_block(doc, spec, doc.w - M, max(ty, y + 60) + 12, size=8)
    return doc.save()


HOLDOUT_RENDERERS: dict[str, Callable[[InvoiceSpec, Path], RenderResult]] = {
    "bilingual": render_bilingual,
    "receipt": render_receipt,
    "stacked": render_stacked,
}
