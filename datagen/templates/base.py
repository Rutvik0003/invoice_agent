"""Drawing toolkit shared by all invoice templates.

Coordinates are in points with y measured from the TOP of the page (easier to lay out invoices).
Every key value is drawn with `text(..., field=...)`, which records its exact bounding box
(normalised 0-1, origin top-left) so labels can say where each printed value is.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from datagen.formats import format_number
from datagen.invoice_spec import InvoiceSpec, SpecLine

FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/msttcorefonts")]
# family -> (regular file, bold file); all contain the ₹ glyph
FONT_FILES: dict[str, tuple[str, str]] = {
    "arial": ("arial.ttf", "arialbd.ttf"),
    "times": ("times.ttf", "timesbd.ttf"),
    "courier": ("cour.ttf", "courbd.ttf"),
    "segoe": ("segoeui.ttf", "segoeuib.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "georgia": ("georgia.ttf", "georgiab.ttf"),
    "trebuchet": ("trebuc.ttf", "trebucbd.ttf"),
    "inkfree": ("Inkfree.ttf", "Inkfree.ttf"),
}
_registered: set[str] = set()

GREY = HexColor("#555555")
LIGHT = HexColor("#EEEEEE")


def _find_font(filename: str) -> Path:
    for directory in FONT_DIRS:
        for candidate in (directory / filename, directory / filename.lower()):
            if candidate.exists():
                return candidate
    raise FileNotFoundError(f"Font {filename} not found in {FONT_DIRS}. The generator needs the standard Windows fonts.")


def font_name(family: str, bold: bool = False) -> str:
    """Register (once) and return the ReportLab font name for a family."""
    name = f"{family}-{'bold' if bold else 'regular'}"
    if name not in _registered:
        pdfmetrics.registerFont(TTFont(name, str(_find_font(FONT_FILES[family][1 if bold else 0]))))
        _registered.add(name)
    return name


@dataclass
class Column:
    title: str
    width: float
    align: str  # left | right | center
    value: Callable[[SpecLine, int], str]
    wrap: bool = False


@dataclass
class RenderResult:
    page_count: int
    field_boxes: dict[str, dict] = field(default_factory=dict)


class Doc:
    """A PDF being drawn, which remembers where key values were printed."""

    def __init__(self, path: Path | BinaryIO, family: str, is_landscape: bool = False) -> None:
        size = landscape(A4) if is_landscape else A4
        target = str(path) if isinstance(path, Path) else path
        self.c = canvas.Canvas(target, pagesize=size, invariant=1, pageCompression=1)
        self.w, self.h = size
        self.family = family
        self.page = 1
        self.boxes: dict[str, dict] = {}

    # ----- text -----

    def width(self, s: str, size: float, bold: bool = False, family: str | None = None) -> float:
        return pdfmetrics.stringWidth(s, font_name(family or self.family, bold), size)

    def text(self, x: float, y: float, s: str, size: float = 9, bold: bool = False, family: str | None = None,
             color: Color = black, align: str = "left", field: str | None = None) -> float:
        """Draw one string with its baseline at y; record its box if it is a key value. Returns its width."""
        name = font_name(family or self.family, bold)
        w = pdfmetrics.stringWidth(s, name, size)
        x0 = x - w if align == "right" else x - w / 2 if align == "center" else x
        self.c.setFont(name, size)
        self.c.setFillColor(color)
        self.c.drawString(x0, self.h - y, s)
        if field:
            # first occurrence is the field's box; repeats (e.g. a total printed twice) are field#2, field#3...
            key, n = field, 1
            while key in self.boxes:
                n += 1
                key = f"{field}#{n}"
            ascent, descent = pdfmetrics.getAscentDescent(name, size)
            self.boxes[key] = {
                "page": self.page,
                "bbox": [round(x0 / self.w, 5), round((y - ascent) / self.h, 5),
                         round((x0 + w) / self.w, 5), round((y - descent) / self.h, 5)],
                "approximate": False,
            }
        return w

    def label_value(self, x: float, y: float, label: str, value: str, size: float = 9, field: str | None = None,
                    bold_label: bool = False, bold_value: bool = False, family: str | None = None,
                    value_family: str | None = None, color: Color = black) -> float:
        """'Label: value' with a clear gap, value drawn separately so its box is exact. Returns end x."""
        label_w = self.text(x, y, label, size, bold=bold_label, family=family, color=GREY if not bold_label else color)
        vx = x + label_w + size * 0.7
        value_w = self.text(vx, y, value, size, bold=bold_value, family=value_family or family, color=color, field=field)
        return vx + value_w

    def wrap(self, s: str, max_width: float, size: float, bold: bool = False, family: str | None = None) -> list[str]:
        return simpleSplit(s, font_name(family or self.family, bold), size, max_width) or [""]

    def paragraph(self, x: float, y: float, s: str, max_width: float, size: float = 8, leading: float | None = None,
                  bold: bool = False, color: Color = black, family: str | None = None) -> float:
        """Wrapped text starting at baseline y; returns the baseline after the last line."""
        leading = leading or size * 1.25
        for line in self.wrap(s, max_width, size, bold, family):
            self.text(x, y, line, size, bold, family, color)
            y += leading
        return y

    # ----- shapes -----

    def rect(self, x: float, y: float, w: float, h: float, stroke: Color | None = black, fill: Color | None = None,
             line_width: float = 0.6, dash: list[float] | None = None) -> None:
        self.c.setLineWidth(line_width)
        self.c.setDash(dash or [])
        if stroke is not None:
            self.c.setStrokeColor(stroke)
        if fill is not None:
            self.c.setFillColor(fill)
        self.c.rect(x, self.h - y - h, w, h, stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)
        self.c.setDash([])

    def line(self, x1: float, y1: float, x2: float, y2: float, color: Color = black, width: float = 0.6,
             dash: list[float] | None = None) -> None:
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.setDash(dash or [])
        self.c.line(x1, self.h - y1, x2, self.h - y2)
        self.c.setDash([])

    def circle(self, x: float, y: float, r: float, stroke: Color | None = black, fill: Color | None = None,
               width: float = 0.8) -> None:
        self.c.setLineWidth(width)
        if stroke is not None:
            self.c.setStrokeColor(stroke)
        if fill is not None:
            self.c.setFillColor(fill)
        self.c.circle(x, self.h - y, r, stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)

    # ----- pages -----

    def new_page(self) -> None:
        self.c.showPage()
        self.page += 1

    def save(self) -> RenderResult:
        self.c.save()
        return RenderResult(self.page, self.boxes)


# ---------------------------------------------------------------- shared blocks


def palette(name: str) -> tuple[Color, Color]:
    """A stable pair of brand colours derived from the vendor name."""
    digest = hashlib.md5(name.encode()).digest()
    choices = ["#1F4E79", "#7B2D26", "#2E6B3F", "#5B2C83", "#B35C00", "#0F6E78", "#3B3B98", "#8C1D40"]
    main = HexColor(choices[digest[0] % len(choices)])
    accent = HexColor(choices[digest[1] % len(choices)])
    return main, accent


def initials(name: str) -> str:
    words = [w for w in name.replace(".", "").split() if w[:1].isalpha() and w.lower() not in {"pvt", "ltd", "private", "limited", "m/s", "llp"}]
    return "".join(w[0] for w in words[:2]).upper() or "V"


def logo(doc: Doc, x: float, y: float, size: float, name: str) -> None:
    """Fictional logo made of simple shapes plus initials (top-left corner at x, y)."""
    main, accent = palette(name)
    shape = hashlib.md5(name.encode()).digest()[2] % 3
    cx, cy = x + size / 2, y + size / 2
    if shape == 0:
        doc.circle(cx, cy, size / 2, stroke=None, fill=main)
        doc.circle(cx + size * 0.18, cy - size * 0.18, size / 4, stroke=None, fill=accent)
    elif shape == 1:
        doc.rect(x, y, size, size, stroke=None, fill=main)
        doc.rect(x + size * 0.55, y, size * 0.45, size * 0.45, stroke=None, fill=accent)
    else:
        p = doc.c.beginPath()
        p.moveTo(x, doc.h - y - size)
        p.lineTo(x + size, doc.h - y - size)
        p.lineTo(cx, doc.h - y)
        p.close()
        doc.c.setFillColor(main)
        doc.c.drawPath(p, stroke=0, fill=1)
    doc.text(cx, cy + size * 0.13, initials(name), size * 0.36, bold=True, color=white, align="center")


def vendor_lines(spec: InvoiceSpec) -> list[str]:
    v = spec.vendor
    lines = [v.address]
    contact = "  ".join(s for s in (f"Ph: {v.phone}" if v.phone else "", f"Email: {v.email}" if v.email else "") if s)
    if contact:
        lines.append(contact)
    return lines


def vendor_block(doc: Doc, spec: InvoiceSpec, x: float, y: float, width: float, name_size: float = 13,
                 size: float = 8, align: str = "left", color: Color = black) -> float:
    """Vendor name, address, contact, GSTIN and state. Returns the y below the block."""
    doc.text(x, y, spec.vendor_name_printed, name_size, bold=True, color=color, align=align, field="vendor_name")
    y += name_size * 1.1
    for line in vendor_lines(spec):
        for part in doc.wrap(line, width, size):
            doc.text(x, y, part, size, color=GREY, align=align)
            y += size * 1.3
    gstin = spec.gstin_text(spec.vendor.gstin)
    if gstin:
        if align == "left":
            doc.label_value(x, y, "GSTIN:", gstin, size, field="vendor_gstin", bold_value=True)
        else:
            w = doc.width(gstin, size, bold=True)
            doc.text(x, y, gstin, size, bold=True, align="right", field="vendor_gstin")
            doc.text(x - w - size * 0.7, y, "GSTIN:", size, color=GREY, align="right")
        y += size * 1.3
    state_text = f"State: {spec.vendor.state}, Code: {spec.vendor.state_code}"
    doc.text(x, y, state_text, size, color=GREY, align=align)
    return y + size * 1.3


def buyer_block(doc: Doc, spec: InvoiceSpec, x: float, y: float, width: float, title: str = "Bill To",
                size: float = 8, title_color: Color = GREY) -> float:
    doc.text(x, y, title, size, bold=True, color=title_color)
    y += size * 1.4
    doc.text(x, y, spec.buyer.name, size + 1, bold=True)
    y += size * 1.35
    y = doc.paragraph(x, y, spec.buyer.address, width, size, color=GREY)
    gstin = spec.gstin_text(spec.buyer.gstin)
    if gstin:
        doc.label_value(x, y, "GSTIN:", gstin, size, field="buyer_gstin", bold_value=True)
        y += size * 1.3
    doc.text(x, y, f"State: {spec.buyer.state}, Code: {spec.buyer.state_code}", size, color=GREY)
    return y + size * 1.3


def meta_rows(spec: InvoiceSpec, include_due: bool = True) -> list[tuple[str, str, str | None]]:
    """(label, value, field) rows for the invoice header."""
    rows: list[tuple[str, str, str | None]] = []
    if spec.invoice_number:
        rows.append((spec.invoice_no_label, spec.invoice_number, "invoice_number"))
    rows.append((spec.date_label, spec.date_text, "invoice_date"))
    if spec.po_reference and not spec.po_in_notes:
        rows.append((spec.po_label, spec.po_reference, "po_reference"))
    if include_due and spec.document_type == "tax_invoice":
        from datagen.formats import format_date

        rows.append(("Due Date", format_date(spec.due_date, spec.date_style), None))
    rows.append(("Place of Supply", f"{spec.buyer.state} ({spec.buyer.state_code})", None))
    return rows


def tax_label(spec: InvoiceSpec, tax: str) -> str:
    if not spec.single_rate:
        return tax
    rate = spec.lines[0].gst_rate
    pct = rate / 2 if tax in ("CGST", "SGST") else rate
    return f"{tax} @ {pct:g}%"


def totals_rows(spec: InvoiceSpec) -> list[tuple[str, str, str | None, bool]]:
    """(label, printed value, field, is_grand_total) rows for the totals block."""
    rows: list[tuple[str, str, str | None, bool]] = [("Sub Total", spec.amount_text(spec.subtotal), "subtotal", False)]
    if spec.discount:
        rows.append(("Less: Discount", "-" + spec.amount_text(spec.discount), None, False))
    if spec.other_charges:
        rows.append((spec.other_charges_label, spec.amount_text(spec.other_charges), None, False))
    if spec.tax_split == "igst":
        rows.append((tax_label(spec, "IGST"), spec.amount_text(spec.igst), "igst", False))
    else:
        rows.append((tax_label(spec, "CGST"), spec.amount_text(spec.cgst), "cgst", False))
        rows.append((tax_label(spec, "SGST"), spec.amount_text(spec.sgst), "sgst", False))
    if spec.round_off is not None:
        sign = "-" if spec.round_off < 0 else ""
        rows.append(("Round Off", f"{sign}{format_number(abs(spec.round_off))}", None, False))
    rows.append(("Total", spec.amount_text(spec.total_amount), "total_amount", True))
    return rows


def draw_totals(doc: Doc, spec: InvoiceSpec, label_x: float, value_right: float, y: float, size: float = 9,
                leading: float = 1.55, total_label: str = "Total", total_size: float | None = None,
                rule: bool = True) -> float:
    for label, value, field_name, is_total in totals_rows(spec):
        s = (total_size or size + 1) if is_total else size
        if is_total:
            y += s * 0.35
            if rule:  # a rule between the last row's descenders and the grand total
                doc.line(label_x, y - s * 1.05, value_right, y - s * 1.05, width=0.5)
        doc.text(label_x, y, total_label if is_total else label, s, bold=is_total)
        doc.text(value_right, y, value, s, bold=is_total, align="right", field=field_name)
        y += s * leading
    return y


def bank_block(doc: Doc, spec: InvoiceSpec, x: float, y: float, size: float = 8, title: str = "Bank Details",
               value_family: str | None = None) -> float:
    if not spec.bank_account:
        return y
    doc.text(x, y, title, size, bold=True)
    y += size * 1.4
    doc.label_value(x, y, "Bank:", spec.bank_name or "", size, value_family=value_family)
    y += size * 1.35
    doc.label_value(x, y, "A/c No:", spec.bank_account, size, field="bank_account", bold_value=True, value_family=value_family)
    y += size * 1.35
    doc.label_value(x, y, "IFSC:", spec.bank_ifsc or "", size, field="bank_ifsc", value_family=value_family)
    return y + size * 1.35


def notes_block(doc: Doc, spec: InvoiceSpec, x: float, y: float, width: float, size: float = 7.5,
                title: str = "Notes / Terms") -> float:
    doc.text(x, y, title, size, bold=True)
    y += size * 1.4
    if spec.po_reference and spec.po_in_notes:
        doc.label_value(x, y, "Supplied against your Purchase Order", spec.po_reference, size, field="po_reference")
        y += size * 1.35
    for note in spec.notes:
        y = doc.paragraph(x, y, note, width, size, color=GREY)
    return y


def words_block(doc: Doc, spec: InvoiceSpec, x: float, y: float, width: float, size: float = 8,
                label: str = "Amount in words:") -> float:
    words = spec.words_text
    if not words:
        return y
    doc.text(x, y, label, size, bold=True)
    return doc.paragraph(x, y + size * 1.35, words, width, size)


def signature_block(doc: Doc, spec: InvoiceSpec, x_right: float, y: float, size: float = 8) -> float:
    doc.text(x_right, y, f"For {spec.vendor_name_printed}", size, bold=True, align="right")
    doc.line(x_right - 130, y + 32, x_right, y + 32, color=GREY, width=0.4)
    doc.text(x_right, y + 42, "Authorised Signatory", size, color=GREY, align="right")
    return y + 50


def line_amount(line: SpecLine, _: int) -> str:
    return format_number(line.amount)


def line_rate(line: SpecLine, _: int) -> str:
    return format_number(line.unit_price)


def line_qty(line: SpecLine, _: int) -> str:
    return f"{line.quantity:,}"


def draw_table(doc: Doc, x: float, y: float, columns: list[Column], lines: list[SpecLine], size: float = 8,
               header_fill: Color | None = LIGHT, header_color: Color = black, grid: bool = True,
               row_rule: Color | None = None, bottom_limit: float | None = None,
               on_page_break: Callable[[], float] | None = None, rows_per_page: int | None = None,
               zebra: Color | None = None, header_bold: bool = True, header_size: float | None = None) -> float:
    """Draw the line-item table, breaking onto new pages when needed. Returns y below the table."""
    total_w = sum(c.width for c in columns)
    bottom_limit = bottom_limit or doc.h - 60
    pad = 3

    def header(y: float) -> float:
        h = size * 2.0
        if header_fill is not None:
            doc.rect(x, y, total_w, h, stroke=black if grid else None, fill=header_fill)
        cx = x
        for col in columns:
            tx = cx + pad if col.align == "left" else cx + col.width - pad if col.align == "right" else cx + col.width / 2
            doc.text(tx, y + h * 0.65, col.title, header_size or size, bold=header_bold, color=header_color, align=col.align)
            if grid:
                doc.line(cx, y, cx, y + h)
            cx += col.width
        if grid:
            doc.line(cx, y, cx, y + h)
        return y + h

    y = header(y)
    rows_on_page = 0
    for index, line in enumerate(lines, start=1):
        cells = []
        for col in columns:
            value = col.value(line, index)
            cells.append(doc.wrap(value, col.width - 2 * pad, size) if col.wrap else [value])
        row_h = max(len(c) for c in cells) * size * 1.25 + size * 0.9
        page_full = rows_per_page is not None and rows_on_page >= rows_per_page
        if (y + row_h > bottom_limit or page_full) and on_page_break is not None:
            if grid:
                doc.line(x, y, x + total_w, y)
            y = header(on_page_break())
            rows_on_page = 0
        if grid:
            doc.line(x, y, x + total_w, y)
        if zebra is not None and index % 2 == 0:
            doc.rect(x, y, total_w, row_h, stroke=None, fill=zebra)
        cx = x
        for col, cell in zip(columns, cells):
            tx = cx + pad if col.align == "left" else cx + col.width - pad if col.align == "right" else cx + col.width / 2
            for i, part in enumerate(cell):
                doc.text(tx, y + size * 1.15 + i * size * 1.25, part, size, align=col.align)
            if grid:
                doc.line(cx, y, cx, y + row_h)
            cx += col.width
        if grid:
            doc.line(cx, y, cx, y + row_h)
        if row_rule is not None:
            doc.line(x, y + row_h, x + total_w, y + row_h, color=row_rule, width=0.4)
        y += row_h
        rows_on_page += 1
    if grid:
        doc.line(x, y, x + total_w, y)
    return y
