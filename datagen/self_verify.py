"""Self-verification of generated digital PDFs (no AI, no OCR): every printed key value must be in the
PDF text layer, inside its recorded field box (IoU > 0.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from datagen.labels import Label

KEY_FIELDS = (
    "invoice_number", "invoice_date", "vendor_gstin", "buyer_gstin", "po_reference", "subtotal",
    "cgst", "sgst", "igst", "total_amount", "bank_account", "vendor_name",
)
MIN_IOU = 0.5


@dataclass
class FieldCheck:
    invoice_id: str
    field: str
    expected: str
    found: str
    iou: float

    @property
    def passed(self) -> bool:
        return self.found == self.expected and self.iou > MIN_IOU


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def check_file(label: Label, folder: Path) -> list[FieldCheck]:
    """Compare each key value's printed text with the PDF words that sit inside its box."""
    doc = pymupdf.open(folder / label.file_name)
    checks = []
    for name in KEY_FIELDS:
        expected = label.ground_truth[name]["printed"]
        if expected is None:
            continue
        box = label.field_boxes.get(name)
        if box is None:
            checks.append(FieldCheck(label.invoice_id, name, expected, "<no box>", 0.0))
            continue
        page = doc[box.page - 1]
        w, h = page.rect.width, page.rect.height
        bx = (box.bbox[0] * w, box.bbox[1] * h, box.bbox[2] * w, box.bbox[3] * h)
        inside = [wd for wd in page.get_text("words")
                  if bx[0] - 1 <= (wd[0] + wd[2]) / 2 <= bx[2] + 1 and bx[1] - 1 <= (wd[1] + wd[3]) / 2 <= bx[3] + 1]
        found = " ".join(wd[4] for wd in inside)
        union = (min(wd[0] for wd in inside), min(wd[1] for wd in inside),
                 max(wd[2] for wd in inside), max(wd[3] for wd in inside)) if inside else (0, 0, 0, 0)
        checks.append(FieldCheck(label.invoice_id, name, expected, found, iou(union, bx)))
    return checks


def verify_digital(labels: list[Label], folders: dict[str, Path]) -> list[FieldCheck]:
    """Run the check on every digital (non-scanned) file."""
    results = []
    for label in labels:
        if not label.is_scanned:
            results.extend(check_file(label, folders[label.set_name]))
    return results
