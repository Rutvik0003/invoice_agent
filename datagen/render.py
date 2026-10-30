"""Render planned invoices to files (digital PDF, or degraded scan as PDF/PNG/JPG) and build their labels."""

from __future__ import annotations

import io
import json
import random
from pathlib import Path

from datagen.degrade import degrade, save_scan
from datagen.labels import Label, ground_truth
from datagen.scenarios import PlannedInvoice
from datagen.templates.layouts import RENDERERS


def render_planned(planned: PlannedInvoice, out_dir: Path, seed: int) -> Label:
    """Write the invoice file into out_dir and return its validated label."""
    spec = planned.spec
    rng = random.Random(f"{seed}-{spec.invoice_id}")  # per-invoice randomness, independent of render order
    renderer = RENDERERS[spec.template]
    degradations: list[str] = []
    if not planned.is_scanned:
        file_format = "pdf"
        path = out_dir / f"{spec.invoice_id}.pdf"
        result = renderer(spec, path)
        boxes = result.field_boxes
    else:
        buffer = io.BytesIO()
        result = renderer(spec, buffer)
        file_format = planned.file_format if result.page_count == 1 else "pdf"
        missing = [f for f in planned.obscured_fields if f not in result.field_boxes]
        if missing:
            raise ValueError(f"{spec.invoice_id}: cannot obscure {missing}, not printed")
        scan = degrade(buffer.getvalue(), result.field_boxes, planned.scan, planned.obscured_fields, rng)
        path = out_dir / f"{spec.invoice_id}.{file_format}"
        save_scan(scan, path, file_format)
        boxes, degradations = scan.field_boxes, scan.degradations
    return Label(
        invoice_id=spec.invoice_id,
        file_name=path.name,
        set_name=planned.set_name,
        scenario=planned.scenario,
        template=spec.template,
        is_scanned=planned.is_scanned,
        scan_level=planned.scan,
        file_format=file_format,
        degradations=degradations,
        ground_truth=ground_truth(spec, result.page_count),
        field_boxes=boxes,
        obscured_fields=planned.obscured_fields,
        rules_eval_signals=planned.rules_eval_signals(),
        expected_decision=planned.expected_decision,
        acceptable_decisions=planned.acceptable_decisions,
        expected_reason_codes=planned.expected_reason_codes,
        expected_reason_codes_any_of=planned.expected_reason_codes_any_of,
        true_po_number=planned.true_po_number,
        knobs=spec.knobs,
        notes=planned.notes,
    )


def write_label(label: Label, labels_dir: Path) -> None:
    labels_dir.mkdir(parents=True, exist_ok=True)
    (labels_dir / f"{label.invoice_id}.json").write_text(
        json.dumps(label.model_dump(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
