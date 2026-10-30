"""The eight invoice layouts. Each draws an InvoiceSpec to a PDF and returns where key values landed."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

from reportlab.lib.colors import HexColor, black, white

from datagen.formats import format_number
from datagen.invoice_spec import InvoiceSpec
from datagen.templates.base import (
    GREY,
    LIGHT,
    Column,
    Doc,
    RenderResult,
    bank_block,
    buyer_block,
    draw_table,
    draw_totals,
    line_amount,
    line_qty,
    line_rate,
    logo,
    meta_rows,
    notes_block,
    palette,
    signature_block,
    totals_rows,
    vendor_block,
    words_block,
)

M = 36  # page margin


def _continued(doc: Doc, spec: InvoiceSpec, size: float = 8) -> Callable[[], float]:
    """Page-break handler: footer note, new page, small running header. Returns the y to resume at."""
    def handler() -> float:
        doc.text(doc.w - M, doc.h - 30, "Continued on next page...", size, color=GREY, align="right")
        doc.new_page()
        doc.text(M, 40, spec.vendor_name_printed, size + 1, bold=True)
        ref = f"{spec.invoice_no_label} {spec.invoice_number}" if spec.invoice_number else spec.title
        doc.text(doc.w - M, 40, f"{ref}  (continued)", size, color=GREY, align="right")
        return 56
    return handler


def _per_line_tax_columns(spec: InvoiceSpec, w: float) -> list[Column]:
    if spec.tax_split == "igst":
        return [
            Column("IGST %", w * 0.8, "right", lambda l, i: f"{l.gst_rate:g}"),
            Column("IGST Amt", w * 1.2, "right", lambda l, i: format_number(l.igst)),
        ]
    return [
        Column("CGST %", w * 0.8, "right", lambda l, i: f"{l.gst_rate / 2:g}"),
        Column("CGST Amt", w * 1.2, "right", lambda l, i: format_number(l.cgst)),
        Column("SGST %", w * 0.8, "right", lambda l, i: f"{l.gst_rate / 2:g}"),
        Column("SGST Amt", w * 1.2, "right", lambda l, i: format_number(l.sgst)),
    ]


# ---------------------------------------------------------------- 1. classic


def render_classic(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Classic GST invoice: page border, bordered table with HSN and CGST/SGST (or IGST) columns per line."""
    doc = Doc(path, "times")
    doc.rect(24, 24, doc.w - 48, doc.h - 48, line_width=1)
    doc.text(doc.w / 2, 50, spec.title.upper(), 15, bold=True, align="center")
    doc.text(doc.w - M, 50, "Original for Recipient", 7, color=GREY, align="right")
    logo(doc, M, 62, 44, spec.vendor_name_printed)
    y_vendor = vendor_block(doc, spec, M + 54, 76, 250, name_size=13, size=8)
    # meta grid on the right
    mx, my, mw = doc.w - M - 200, 62, 200
    rows = meta_rows(spec)
    doc.rect(mx, my, mw, len(rows) * 16)
    for i, (label, value, field) in enumerate(rows):
        ry = my + i * 16
        doc.line(mx, ry, mx + mw, ry)
        doc.line(mx + 82, ry, mx + 82, ry + 16)
        doc.text(mx + 4, ry + 11, label, 8, color=GREY)
        doc.text(mx + 86, ry + 11, value, 8.5, bold=True, field=field)
    y = max(y_vendor, my + len(rows) * 16) + 10
    doc.line(24, y, doc.w - 24, y)
    buyer_block(doc, spec, M, y + 14, 250, "Details of Receiver (Billed to)")
    ship_y = y + 14
    doc.text(doc.w / 2 + 10, ship_y, "Details of Consignee (Shipped to)", 8, bold=True, color=GREY)
    doc.text(doc.w / 2 + 10, ship_y + 12, spec.buyer.name, 9, bold=True)
    doc.paragraph(doc.w / 2 + 10, ship_y + 24, "Central Warehouse, Gala No. 14-18, Vashere Village, Bhiwandi - 421302, Maharashtra",
                  220, 8, color=GREY)
    y += 92
    tax_cols = _per_line_tax_columns(spec, 40)
    fixed = [
        Column("S.No", 24, "center", lambda l, i: str(i)),
        Column("HSN/SAC", 40, "center", lambda l, i: l.hsn_sac),
        Column("Qty", 34, "right", line_qty),
        Column("Unit", 30, "center", lambda l, i: l.unit),
        Column("Rate", 50, "right", line_rate),
        Column("Taxable", 58, "right", line_amount),
    ]
    used = sum(c.width for c in fixed + tax_cols)
    columns = fixed[:1] + [Column("Description of Goods / Services", doc.w - 2 * M - used, "left",
                                  lambda l, i: l.description, wrap=True)] + fixed[1:] + tax_cols
    y = draw_table(doc, M, y, columns, spec.lines, size=7.5, header_size=6.5, on_page_break=_continued(doc, spec),
                   bottom_limit=doc.h - 200)
    if y > doc.h - 250:
        y = _continued(doc, spec)()
    y += 16
    draw_totals(doc, spec, doc.w - M - 200, doc.w - M, y, size=9)
    words_y = words_block(doc, spec, M, y, 280)
    bank_block(doc, spec, M, max(words_y, y + 34) + 10)
    sig_y = doc.h - 140
    notes_block(doc, spec, M, sig_y + 14, 300)
    signature_block(doc, spec, doc.w - M, sig_y + 14)
    doc.text(doc.w / 2, doc.h - 34, "This is a computer generated invoice.", 7, color=GREY, align="center")
    return doc.save()


# ---------------------------------------------------------------- 2. modern


def render_modern(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Modern minimal: no borders, accent bar, big amount due."""
    doc = Doc(path, "segoe")
    main, accent = palette(spec.vendor_name_printed)
    doc.rect(0, 0, 10, doc.h, stroke=None, fill=main)
    doc.text(M + 4, 66, spec.title.upper() if spec.document_type != "tax_invoice" else spec.title, 26, bold=True, color=main)
    logo(doc, doc.w - M - 40, 36, 40, spec.vendor_name_printed)
    vendor_block(doc, spec, doc.w - M - 52, 52, 220, name_size=12, size=8, align="right")
    y = 110
    rows = [r for r in meta_rows(spec) if r[0] != "Place of Supply"]
    col_w = (doc.w - 2 * M - 8) / max(len(rows), 1)
    for i, (label, value, field) in enumerate(rows):
        x = M + 4 + i * col_w
        doc.text(x, y, label.upper(), 7, color=GREY)
        doc.text(x, y + 14, value, 10, bold=True, field=field)
    y += 40
    buyer_block(doc, spec, M + 4, y, 240, "BILLED TO", title_color=main)
    y += 90
    columns = [
        Column("Item", doc.w - 2 * M - 8 - 250, "left", lambda l, i: l.description, wrap=True),
        Column("HSN/SAC", 50, "left", lambda l, i: l.hsn_sac),
        Column("Qty", 45, "right", line_qty),
        Column("Unit price", 75, "right", line_rate),
        Column("Amount", 80, "right", line_amount),
    ]
    if spec.tax_per_line:
        columns.insert(4, Column("GST", 30, "right", lambda l, i: f"{l.gst_rate:g}%"))
        columns[0].width -= 30
    y = draw_table(doc, M + 4, y, columns, spec.lines, size=8.5, header_fill=None, grid=False, row_rule=LIGHT,
                   header_color=GREY, on_page_break=_continued(doc, spec), bottom_limit=doc.h - 230)
    if y > doc.h - 260:
        y = _continued(doc, spec)()
    y += 22
    # big amount due first so it is the recorded total
    doc.text(M + 4, y, "AMOUNT DUE", 8, color=GREY)
    doc.text(M + 4, y + 30, spec.amount_text(spec.total_amount), 24, bold=True, color=main, field="total_amount")
    words_block(doc, spec, M + 4, y + 50, 230, size=7.5, label="In words")
    draw_totals(doc, spec, doc.w - M - 200, doc.w - M, y, size=9, total_label="Total payable")
    bank_block(doc, spec, M + 4, doc.h - 150, title="PAYMENT DETAILS")
    notes_block(doc, spec, M + 230, doc.h - 150, 140, title="NOTES")
    signature_block(doc, spec, doc.w - M, doc.h - 150)
    doc.text(doc.w / 2, doc.h - 28, "Thank you for your business.", 8, color=accent, align="center")
    return doc.save()


# ---------------------------------------------------------------- 3. services


def render_services(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Services invoice: coloured header band, SAC codes, hours/units x rate."""
    doc = Doc(path, "verdana")
    main, _ = palette(spec.vendor_name_printed)
    doc.rect(0, 0, doc.w, 96, stroke=None, fill=main)
    name_size = 16
    while doc.width(spec.vendor_name_printed, name_size, bold=True) > doc.w - 2 * M - 190 and name_size > 9:
        name_size -= 0.5
    doc.text(M, 40, spec.vendor_name_printed, name_size, bold=True, color=white, field="vendor_name")
    doc.text(M, 56, spec.vendor.address, 7.5, color=white)
    gstin = spec.gstin_text(spec.vendor.gstin)
    if gstin:
        w = doc.text(M, 70, "GSTIN:", 7.5, color=white)
        doc.text(M + w + 6, 70, gstin, 7.5, bold=True, color=white, field="vendor_gstin")
    doc.text(M, 84, f"{spec.vendor.phone}   {spec.vendor.email}", 7.5, color=white)
    doc.text(doc.w - M, 48, spec.title.upper(), 18, bold=True, color=white, align="right")
    doc.text(doc.w - M, 66, "Services", 9, color=white, align="right")
    y = 122
    buyer_block(doc, spec, M, y, 250, "CLIENT")
    my = y
    for label, value, field in meta_rows(spec):
        doc.text(doc.w - M - 110, my, label, 8, color=GREY, align="right")
        doc.text(doc.w - M, my, value, 8.5, bold=True, align="right", field=field)
        my += 14
    y = max(y + 86, my + 10)
    doc.text(M, y, f"Service period: {spec.invoice_date.strftime('%B %Y')}", 8, color=GREY)
    y += 12
    columns = [
        Column("#", 22, "center", lambda l, i: str(i)),
        Column("Service description", doc.w - 2 * M - 22 - 58 - 64 - 78 - 86, "left", lambda l, i: l.description, wrap=True),
        Column("SAC", 58, "center", lambda l, i: l.hsn_sac),
        Column(f"Hours/Units", 64, "right", lambda l, i: f"{l.quantity:,} {l.unit}"),
        Column("Rate", 78, "right", line_rate),
        Column("Amount", 86, "right", line_amount),
    ]
    y = draw_table(doc, M, y, columns, spec.lines, size=8, header_fill=HexColor("#E8EEF4"), grid=False,
                   row_rule=LIGHT, on_page_break=_continued(doc, spec), bottom_limit=doc.h - 220)
    if y > doc.h - 250:
        y = _continued(doc, spec)()
    y += 18
    draw_totals(doc, spec, doc.w - M - 210, doc.w - M, y, size=8.5)
    notes_block(doc, spec, M, y, 250, title="Terms")
    y = words_block(doc, spec, M, doc.h - 190, 280)
    bank_block(doc, spec, M, doc.h - 140, title="Remit to")
    signature_block(doc, spec, doc.w - M, doc.h - 140)
    return doc.save()


# ---------------------------------------------------------------- 4. compact


def render_compact(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Compact: two boxed columns (supplier | recipient), meta strip, rate-wise tax summary at the bottom."""
    doc = Doc(path, "arial")
    doc.text(doc.w / 2, 42, spec.title, 13, bold=True, align="center")
    half = (doc.w - 2 * M) / 2
    doc.rect(M, 52, half, 112)
    doc.rect(M + half, 52, half, 112)
    doc.text(M + 6, 64, "Supplier", 7, bold=True, color=GREY)
    vendor_block(doc, spec, M + 6, 78, half - 12, name_size=10, size=7.5)
    buyer_block(doc, spec, M + half + 6, 64, half - 12, "Recipient", size=7.5)
    rows = meta_rows(spec, include_due=False)
    cell = (doc.w - 2 * M) / len(rows)
    doc.rect(M, 164, doc.w - 2 * M, 30)
    for i, (label, value, field) in enumerate(rows):
        x = M + i * cell
        if i:
            doc.line(x, 164, x, 194)
        doc.text(x + 4, 175, label, 6.5, color=GREY)
        doc.text(x + 4, 188, value, 8, bold=True, field=field)
    columns = [
        Column("Sr", 20, "center", lambda l, i: str(i)),
        Column("Particulars", doc.w - 2 * M - 20 - 44 - 40 - 32 - 60 - 34 - 70, "left", lambda l, i: l.description, wrap=True),
        Column("HSN/SAC", 44, "center", lambda l, i: l.hsn_sac),
        Column("Qty", 40, "right", line_qty),
        Column("UOM", 32, "center", lambda l, i: l.unit),
        Column("Rate", 60, "right", line_rate),
        Column("GST%", 34, "right", lambda l, i: f"{l.gst_rate:g}"),
        Column("Amount", 70, "right", line_amount),
    ]
    y = draw_table(doc, M, 204, columns, spec.lines, size=7.5, on_page_break=_continued(doc, spec), bottom_limit=doc.h - 260)
    if y > doc.h - 290:
        y = _continued(doc, spec)()
    y += 14
    draw_totals(doc, spec, doc.w - M - 190, doc.w - M, y, size=8.5)
    # rate-wise tax summary
    doc.text(M, y, "Tax summary (rate-wise)", 7.5, bold=True)
    groups: dict[float, list] = {}
    for line in spec.lines:
        groups.setdefault(line.gst_rate, []).append(line)
    sx, sy = M, y + 6
    heads = ["Rate", "Taxable", "CGST" if spec.tax_split != "igst" else "IGST", "SGST" if spec.tax_split != "igst" else "", "Total tax"]
    widths = [40, 70, 60, 60, 66]
    doc.rect(sx, sy, sum(widths), 14, fill=LIGHT)
    cx = sx
    for head, w in zip(heads, widths):
        doc.text(cx + w - 3, sy + 10, head, 7, bold=True, align="right")
        cx += w
    sy += 14
    for rate, lines in sorted(groups.items()):
        taxable = sum(l.amount for l in lines)
        if spec.discount or spec.other_charges:
            tax_a = tax_b = None
        else:
            tax_a = sum(l.igst for l in lines) if spec.tax_split == "igst" else sum(l.cgst for l in lines)
            tax_b = None if spec.tax_split == "igst" else sum(l.sgst for l in lines)
        values = [f"{rate:g}%", format_number(taxable), format_number(tax_a) if tax_a is not None else "-",
                  format_number(tax_b) if tax_b is not None else "", format_number((tax_a or 0) + (tax_b or 0)) if tax_a is not None else "-"]
        doc.rect(sx, sy, sum(widths), 13)
        cx = sx
        for value, w in zip(values, widths):
            doc.text(cx + w - 3, sy + 9.5, value, 7, align="right")
            cx += w
        sy += 13
    words_block(doc, spec, M, sy + 16, 290, size=7.5)
    bank_block(doc, spec, M, doc.h - 150, size=7.5)
    notes_block(doc, spec, M + 170, doc.h - 150, 160, size=7)
    signature_block(doc, spec, doc.w - M, doc.h - 150, size=7.5)
    return doc.save()


# ---------------------------------------------------------------- 5. multipage


def render_multipage(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Multi-page: items spread over 2-3 pages with 'continued', totals only on the last page."""
    doc = Doc(path, "georgia")
    n = len(spec.lines)
    item_pages = 2 if n >= 4 else 1  # items on 1-2 pages, then a final page with the totals
    rows_per_page = math.ceil(n / item_pages)
    total_pages = item_pages + 1

    def page_header(first: bool) -> float:
        logo(doc, M, 30, 30, spec.vendor_name_printed)
        doc.text(doc.w - M, 44, f"Page {doc.page} of {total_pages}", 8, color=GREY, align="right")
        if not first:
            doc.text(M + 40, 50, spec.vendor_name_printed, 11, bold=True)
            ref = f"{spec.invoice_no_label} {spec.invoice_number}" if spec.invoice_number else spec.title
            doc.text(doc.w - M, 58, ref, 8, color=GREY, align="right")
            return 84
        return 0

    def page_break() -> float:
        doc.text(doc.w / 2, doc.h - 40, "-- Continued on next page --", 8, color=GREY, align="center")
        doc.new_page()
        return page_header(first=False)

    page_header(first=True)
    vendor_block(doc, spec, M + 40, 48, 280, name_size=13, size=8)
    doc.text(doc.w - M, 74, spec.title.upper(), 16, bold=True, align="right")
    my = 92
    for label, value, field in meta_rows(spec):
        doc.label_value(doc.w - M - 190, my, f"{label}:", value, 8.5, field=field, bold_value=True)
        my += 13
    y = max(my, 140) + 10
    buyer_block(doc, spec, M, y, 260, "Invoice To")
    y += 96
    columns = [
        Column("No.", 26, "center", lambda l, i: str(i)),
        Column("Description", doc.w - 2 * M - 26 - 52 - 46 - 70 - 84, "left",
               lambda l, i: f"{l.description} — supplied as per agreed specification and delivery schedule", wrap=True),
        Column("HSN/SAC", 52, "center", lambda l, i: l.hsn_sac),
        Column("Qty", 46, "right", lambda l, i: f"{l.quantity:,} {l.unit}"),
        Column("Rate", 70, "right", line_rate),
        Column("Amount", 84, "right", line_amount),
    ]
    y = draw_table(doc, M, y, columns, spec.lines, size=8.5, rows_per_page=rows_per_page, on_page_break=page_break,
                   bottom_limit=doc.h - 70)
    if doc.page < total_pages:
        y = page_break()
    y += 18
    doc.text(M, y, "Summary", 11, bold=True)
    y = draw_totals(doc, spec, doc.w - M - 220, doc.w - M, y + 18, size=9.5)
    y = words_block(doc, spec, M, y + 6, 400)
    y = bank_block(doc, spec, M, y + 16)
    notes_block(doc, spec, M, y + 12, 300)
    signature_block(doc, spec, doc.w - M, y + 12)
    return doc.save()


# ---------------------------------------------------------------- 6. landscape


def render_landscape(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Landscape: three header columns and a wide table with discount and taxable-value columns."""
    doc = Doc(path, "calibri", is_landscape=True)
    main, _ = palette(spec.vendor_name_printed)
    logo(doc, M, 30, 38, spec.vendor_name_printed)
    vendor_block(doc, spec, M + 48, 44, 230, name_size=13, size=8)
    buyer_block(doc, spec, M + 310, 36, 220, "Buyer")
    doc.text(doc.w - M, 44, spec.title.upper(), 16, bold=True, color=main, align="right")
    my = 62
    for label, value, field in meta_rows(spec):
        doc.text(doc.w - M - 112, my, label, 8.5, color=GREY, align="right")
        doc.text(doc.w - M, my, value, 9, bold=True, align="right", field=field)
        my += 13
    y = max(my, 130) + 8
    doc.line(M, y - 6, doc.w - M, y - 6, color=main, width=1.2)
    columns = [
        Column("#", 22, "center", lambda l, i: str(i)),
        Column("Item description", 0, "left", lambda l, i: l.description, wrap=True),
        Column("HSN/SAC", 56, "center", lambda l, i: l.hsn_sac),
        Column("Qty", 52, "right", line_qty),
        Column("UOM", 44, "center", lambda l, i: l.unit),
        Column("Rate", 72, "right", line_rate),
        Column("Disc.", 46, "right", lambda l, i: "0.00"),
        Column("Taxable value", 84, "right", line_amount),
        Column("GST %", 44, "right", lambda l, i: f"{l.gst_rate:g}"),
        Column("Freight", 52, "right", lambda l, i: "-"),
    ]
    columns[1].width = doc.w - 2 * M - sum(c.width for c in columns)
    y = draw_table(doc, M, y, columns, spec.lines, size=8.5, header_fill=HexColor("#DDE6F0"), zebra=HexColor("#F6F8FA"),
                   on_page_break=_continued(doc, spec), bottom_limit=doc.h - 150)
    if y > doc.h - 170:
        y = _continued(doc, spec)()
    y += 14
    draw_totals(doc, spec, doc.w - M - 230, doc.w - M, y, size=9, leading=1.45)
    y2 = words_block(doc, spec, M, y, 330)
    y2 = bank_block(doc, spec, M, y2 + 10)
    notes_block(doc, spec, M + 350, y, 180)
    signature_block(doc, spec, doc.w - M, doc.h - 70 - 50 + 6)
    return doc.save()


# ---------------------------------------------------------------- 7. tally


def render_tally(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Tally-style: dense boxed grid, small font, tax rows inside the table, HSN summary, declaration."""
    doc = Doc(path, "arial")
    s = 7
    L, R = 28, doc.w - 28
    W = R - L
    doc.text(doc.w / 2, 36, spec.title.upper(), 11, bold=True, align="center")
    doc.text(R, 36, "(ORIGINAL FOR RECIPIENT)", 6, align="right")
    top = 42
    doc.rect(L, top, W, doc.h - top - 30)
    mid = L + W * 0.5
    # left: supplier then buyer
    doc.line(mid, top, mid, top + 190)
    vendor_block(doc, spec, L + 4, top + 12, W * 0.5 - 8, name_size=9, size=s)
    doc.line(L, top + 92, mid, top + 92)
    buyer_block(doc, spec, L + 4, top + 102, W * 0.5 - 8, "Buyer (Bill to)", size=s, title_color=black)
    # right: grid of meta cells
    cells = [
        (spec.invoice_no_label, spec.invoice_number or "", "invoice_number" if spec.invoice_number else None),
        (spec.date_label, spec.date_text, "invoice_date"),
        ("Delivery Note", "", None),
        ("Mode/Terms of Payment", f"{spec.payment_terms_days} Days", None),
        ("Supplier's Ref.", "", None),
        ("Other Reference(s)", "", None),
        (spec.po_label, spec.po_reference if spec.po_reference and not spec.po_in_notes else "",
         "po_reference" if spec.po_reference and not spec.po_in_notes else None),
        ("Dated", "", None),
        ("Dispatched through", "By Road", None),
        ("Destination", "Bhiwandi", None),
    ]
    cw, ch = W * 0.25, 38
    for i, (label, value, field) in enumerate(cells):
        cx = mid + (i % 2) * cw
        cy = top + (i // 2) * ch
        doc.rect(cx, cy, cw, ch, line_width=0.4)
        doc.text(cx + 3, cy + 9, label, 6.5, color=GREY)
        if value:
            doc.text(cx + 3, cy + 22, value, 7.5, bold=True, field=field)
    y = top + 190
    doc.line(L, y, R, y)
    columns = [
        Column("Sl", 18, "center", lambda l, i: str(i)),
        Column("Description of Goods", W - 18 - 46 - 66 - 56 - 30 - 80, "left", lambda l, i: l.description, wrap=True),
        Column("HSN/SAC", 46, "center", lambda l, i: l.hsn_sac),
        Column("Quantity", 66, "right", lambda l, i: f"{l.quantity:,} {l.unit}"),
        Column("Rate", 56, "right", line_rate),
        Column("per", 30, "center", lambda l, i: l.unit),
        Column("Amount", 80, "right", line_amount),
    ]
    y = draw_table(doc, L, y, columns, spec.lines, size=s, header_fill=None, on_page_break=_continued(doc, spec, s),
                   bottom_limit=doc.h - 300)
    # tax and round-off rows inside the table area
    amount_x = R - 3
    for label, value, field, is_total in totals_rows(spec):
        if label == "Sub Total":
            doc.text(amount_x, y + 10, value, s, align="right", field=field)
            y += 13
            continue
        if is_total:
            doc.line(L, y + 2, R, y + 2)
            doc.text(L + W * 0.45, y + 13, "Total", 8, bold=True)
            doc.text(amount_x, y + 13, value, 8, bold=True, align="right", field=field)
            y += 18
            doc.line(L, y, R, y)
            continue
        doc.text(L + W * 0.45, y + 10, label, s, bold=True)
        doc.text(amount_x, y + 10, value, s, align="right", field=field)
        y += 12
    y += 4
    doc.text(L + 4, y + 8, "Amount Chargeable (in words)", 6.5, color=GREY)
    doc.text(R - 4, y + 8, "E. & O.E", 6.5, align="right")
    y = doc.paragraph(L + 4, y + 19, spec.words_text or "", W - 8, 7.5, bold=True)
    doc.line(L, y, R, y)
    # HSN/SAC summary
    sy = y + 10
    doc.text(L + 4, sy, "HSN/SAC", s, bold=True)
    doc.text(L + W * 0.45, sy, "Taxable Value", s, bold=True, align="right")
    doc.text(R - 4, sy, "Tax Rate", s, bold=True, align="right")
    for line in spec.lines:
        sy += 10
        doc.text(L + 4, sy, line.hsn_sac, s)
        doc.text(L + W * 0.45, sy, format_number(line.amount), s, align="right")
        doc.text(R - 4, sy, f"{line.gst_rate:g}%", s, align="right")
    y = sy + 8
    doc.line(L, y, R, y)
    by = bank_block(doc, spec, mid + 4, y + 12, size=s, title="Company's Bank Details")
    if spec.po_reference and spec.po_in_notes:
        doc.label_value(L + 4, y + 12, "Supplied against your Purchase Order", spec.po_reference, s, field="po_reference")
    doc.text(L + 4, y + 26, "Declaration", s, bold=True)
    doc.paragraph(L + 4, y + 36, "We declare that this invoice shows the actual price of the goods described and that "
                  "all particulars are true and correct.", W * 0.5 - 10, 6.5)
    signature_block(doc, spec, R - 4, max(by, y + 70) + 4, size=s)
    doc.text(doc.w / 2, doc.h - 20, "This is a Computer Generated Invoice", 6.5, color=GREY, align="center")
    return doc.save()


# ---------------------------------------------------------------- 8. small vendor


def render_small_vendor(spec: InvoiceSpec, path: Path) -> RenderResult:
    """Small-vendor bill book: printed labels, handwritten values, ruled table, rubber stamp."""
    doc = Doc(path, "arial")
    hand = "inkfree"
    ink = HexColor("#1A2A7A")
    main, _ = palette(spec.vendor_name_printed)
    doc.rect(30, 30, doc.w - 60, doc.h - 60, stroke=main, line_width=1.5)
    doc.text(doc.w / 2, 64, spec.vendor_name_printed, 17, bold=True, color=main, align="center", field="vendor_name")
    doc.text(doc.w / 2, 78, spec.vendor.address, 7.5, align="center", color=GREY)
    gstin = spec.gstin_text(spec.vendor.gstin)
    if gstin:
        gw = doc.width(gstin, 8, bold=True)
        lw = doc.width("GSTIN:", 8)
        start = doc.w / 2 - (gw + lw + 6) / 2
        doc.text(start, 91, "GSTIN:", 8, color=GREY)
        doc.text(start + lw + 6, 91, gstin, 8, bold=True, field="vendor_gstin")
    doc.text(doc.w / 2, 103, f"Mob: {spec.vendor.phone}", 7.5, align="center", color=GREY)
    doc.rect(doc.w / 2 - 50, 110, 100, 16, stroke=main, fill=main)
    doc.text(doc.w / 2, 121.5, spec.title.upper(), 8.5, bold=True, color=white, align="center")
    y = 148
    left = [(spec.invoice_no_label, spec.invoice_number, "invoice_number")] if spec.invoice_number else []
    left.append((spec.date_label, spec.date_text, "invoice_date"))
    if spec.po_reference and not spec.po_in_notes:
        left.append((spec.po_label, spec.po_reference, "po_reference"))
    for i, (label, value, field) in enumerate(left):
        ly = y + i * 20
        lw = doc.text(doc.w - 210, ly, label, 8)
        doc.line(doc.w - 210 + lw + 4, ly + 3, doc.w - 40, ly + 3, color=GREY, width=0.4, dash=[1, 2])
        doc.text(doc.w - 210 + lw + 10, ly - 1, value, 11, family=hand, color=ink, field=field)
    doc.text(44, y, "M/s.", 8)
    doc.line(66, y + 3, doc.w - 230, y + 3, color=GREY, width=0.4, dash=[1, 2])
    doc.text(72, y - 1, spec.buyer.name, 11, family=hand, color=ink)
    doc.paragraph(72, y + 16, spec.buyer.address, doc.w - 310, 9.5, family=hand, color=ink)
    bg = spec.gstin_text(spec.buyer.gstin)
    if bg:
        lw = doc.text(44, y + 56, "Party GSTIN", 8)
        doc.text(44 + lw + 8, y + 55, bg, 10.5, family=hand, color=ink, field="buyer_gstin")
    y += 76
    columns = [
        Column("Sr.", 26, "center", lambda l, i: str(i)),
        Column("Particulars", doc.w - 88 - 26 - 50 - 50 - 70 - 84, "left", lambda l, i: l.description, wrap=True),
        Column("HSN", 50, "center", lambda l, i: l.hsn_sac),
        Column("Qty", 50, "right", line_qty),
        Column("Rate", 70, "right", line_rate),
        Column("Amount", 84, "right", line_amount),
    ]
    y = draw_table(doc, 44, y, columns, spec.lines, size=8.5, header_fill=HexColor("#F2F2F2"),
                   on_page_break=_continued(doc, spec), bottom_limit=doc.h - 230)
    if y > doc.h - 260:
        y = _continued(doc, spec)()
    y += 18
    for label, value, field, is_total in totals_rows(spec):
        size = 13 if is_total else 11
        doc.text(doc.w - 200, y, label, 9 if not is_total else 10, bold=is_total)
        doc.text(doc.w - 46, y - 1, value, size, family=hand, color=ink, align="right", field=field)
        y += 20 if is_total else 16
    words = spec.words_text
    if words:
        doc.text(44, y - 60, "Rupees in words:", 8)
        doc.paragraph(44, y - 46, words, 260, 10, family=hand, color=ink)
    bank_block(doc, spec, 44, doc.h - 150, size=8, value_family=hand)
    notes_block(doc, spec, 44, doc.h - 92, 260, size=7)
    # rubber stamp near the signature
    sx, sy = doc.w - 120, doc.h - 120
    stamp = HexColor("#5B3FA8")
    doc.circle(sx, sy, 36, stroke=stamp, width=1.6)
    doc.circle(sx, sy, 28, stroke=stamp, width=0.8)
    stamp_name = spec.vendor_name_printed.removeprefix("M/s ").upper()
    stamp_size = 5.5
    while doc.width(stamp_name, stamp_size, bold=True) > 50 and stamp_size > 3.6:
        stamp_size -= 0.2
    doc.text(sx, sy - 6, stamp_name if doc.width(stamp_name, stamp_size, bold=True) <= 52 else stamp_name[:16],
             stamp_size, bold=True, color=stamp, align="center")
    doc.text(sx, sy + 4, "AUTHORISED", 6, bold=True, color=stamp, align="center")
    doc.text(sx, sy + 12, spec.vendor.state.upper()[:14], 5.5, color=stamp, align="center")
    doc.text(doc.w - 46, doc.h - 70, "Authorised Signatory", 8, align="right")
    return doc.save()


RENDERERS: dict[str, Callable[[InvoiceSpec, Path], RenderResult]] = {
    "classic": render_classic,
    "modern": render_modern,
    "services": render_services,
    "compact": render_compact,
    "multipage": render_multipage,
    "landscape": render_landscape,
    "tally": render_tally,
    "small_vendor": render_small_vendor,
}
