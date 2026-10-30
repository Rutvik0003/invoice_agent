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
SETS = {"golden": INVOICE_DIR / "golden", "stress": INVOICE_DIR / "stress", "real_world": INVOICE_DIR / "real_world"}


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
                out.append((folder / file_name, label))
    return out


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
