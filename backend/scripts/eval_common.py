"""Helpers shared by the evaluation scripts: loading labels and building invoices from ground truth."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
for _path in (BACKEND_DIR, BACKEND_DIR.parent):  # make `app` (and `datagen` for fault injection) importable
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.config import REPO_ROOT  # noqa: E402
from app.schemas import ExtractedInvoice  # noqa: E402

INVOICE_DIR = REPO_ROOT / "data" / "invoices"
REPORT_DIR = REPO_ROOT / "data" / "eval_reports"
SETS = {"golden": INVOICE_DIR / "golden", "stress": INVOICE_DIR / "stress", "holdout": INVOICE_DIR / "holdout",
        "real_world": INVOICE_DIR / "real_world"}  # "all" = golden + stress; holdout and real_world are run on their own


def load_labels(set_name: str) -> list[tuple[Path, dict]]:
    """(invoice file, label dict) for a set; 'all' = golden + stress."""
    names = ["golden", "stress"] if set_name == "all" else [set_name]
    out = []
    for name in names:
        folder = SETS[name]
        for label_path in sorted((folder / "labels").glob("*.json")):
            label = json.loads(label_path.read_text(encoding="utf-8"))
            file_name = label.get("file_name") or next(
                (p.name for p in folder.iterdir() if p.stem == label_path.stem and p.suffix != ".json"), None)
            if file_name and (folder / file_name).exists():
                out.append((folder / file_name, complete_label(label, folder / file_name)))
    return out


SCALAR_FIELDS = ("document_type", "vendor_name", "vendor_gstin", "vendor_address", "vendor_state", "buyer_name",
                 "buyer_gstin", "invoice_number", "invoice_date", "po_reference", "subtotal", "discount",
                 "other_charges", "cgst", "sgst", "igst", "round_off", "total_amount", "amount_in_words",
                 "bank_account", "bank_ifsc")


def complete_label(label: dict, path: Path) -> dict:
    """Fill what a hand-written real-world label may leave out (data/invoices/real_world/README.md): ids and
    defaults, scan detection from the file itself, and ground-truth values given plainly instead of as
    {value, printed}. A field left out means "not printed on the invoice" (null)."""
    from app.extraction.pdf_utils import guess_mime, text_layer_pages

    if "set_name" in label:  # generated labels are already complete
        return label
    truth = dict(label.get("ground_truth") or {})
    for name in SCALAR_FIELDS:
        value = truth.get(name, "tax_invoice" if name == "document_type" else None)
        truth[name] = value if isinstance(value, dict) else {"value": value, "printed": None if value is None else str(value)}
    truth.setdefault("line_items", [])
    scanned = not all(text_layer_pages(path.read_bytes(), guess_mime(path.name) or ""))
    return {"invoice_id": path.stem, "file_name": path.name, "set_name": "real_world", "scenario": "real_world",
            "template": "real_world", "is_scanned": scanned, "scan_level": "real_scan" if scanned else "digital",
            "obscured_fields": [], "field_boxes": {}, **label, "ground_truth": truth}


def degradation_level(label: dict) -> str:
    return label.get("scan_level") or ("digital" if not label.get("is_scanned") else "scan")


def ground_truth_invoice(label: dict, confidence: float = 0.95) -> ExtractedInvoice:
    """The label's true printed values as if a perfect extractor had returned them."""
    data = {}
    for name, field in label["ground_truth"].items():
        if isinstance(field, dict):
            data[name] = {"value": field.get("value"), "printed": field.get("printed"), "confidence": confidence}
    data["line_items"] = label["ground_truth"].get("line_items", [])
    return ExtractedInvoice.model_validate(data)
