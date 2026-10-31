"""Held-out test set: invoices the pipeline was never tuned on (data/invoices/holdout).

What is new compared with golden + stress:
- three layouts written after tuning (templates/holdout_layouts.py: bilingual Hindi/English, narrow receipt,
  inverted header with labels above values);
- two image types never used before: phone photos (perspective, glare, shadow) and small low-resolution web
  images (like a screenshot or an image saved from a website);
- plus digital PDFs and ordinary mild scans of the new layouts.

The invoices are planned AFTER golden and stress with the same planner, so those sets are unchanged. The seeded
POs are all used by then, so the holdout adds new open POs (never vendors or invoice history) and data/master is
rewritten with them; anything else changing in the master data stops the script. Expected decisions come from the
scenario, never from the engine (rule 6).

Usage: python -m datagen.holdout          (do not tune the pipeline on these results; that would spoil the test)
"""

from __future__ import annotations

import io
import random
import tempfile
from pathlib import Path

from PIL import Image

from datagen.degrade import degrade, phone_photo, rasterise, save_scan
from datagen.labels import Label, ground_truth
from datagen.master_data import DEFAULT_SEED, build_master, write_master
from datagen.render import write_label
from datagen.scenarios import NOT_INVOICE_DOCS, PlannedInvoice, Planner, plan_golden, plan_stress
from datagen.self_verify import verify_digital
from datagen.templates.holdout_layouts import HOLDOUT_RENDERERS

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "invoices" / "holdout"
MASTER_DIR = REPO_ROOT / "data" / "master"
LAYOUTS = tuple(HOLDOUT_RENDERERS)
# (image type, share): digital PDF, mild scan, phone photo, low-resolution web image
IMAGE_TYPES = ("none", "mild", "photo", "web")


def plan_holdout(p: Planner) -> list[PlannedInvoice]:
    """~42 invoices across scenarios that need no new master data."""
    counts = [
        ("CLEAN_EXACT", 10, lambda i: p.clean(i, "holdout")),
        ("CLEAN_WITHIN_TOLERANCE", 4, lambda i: p.within_tolerance(i, "holdout")),
        ("PRICE_OVER_TOLERANCE", 4, lambda i: p.price_over(i, "holdout")),
        ("BANK_CHANGE", 4, lambda i: p.bank_change(i, "holdout")),
        ("GST_WRONG_TYPE", 4, lambda i: p.wrong_gst(i, "holdout")),
        ("ARITHMETIC_ERROR", 4, lambda i: p.arithmetic_error(i, "holdout")),
        ("QTY_EXCEEDS_PO", 3, lambda i: p.qty_exceeds(i, "holdout")),
        ("VENDOR_UNKNOWN", 3, lambda i: p.vendor_unknown(i, "holdout")),
        ("BUYER_MISMATCH", 3, lambda i: p.buyer_mismatch(i, "holdout")),
        ("NOT_AN_INVOICE", 3, lambda i: p.not_an_invoice(i, "holdout", doc=p.rng.choice(NOT_INVOICE_DOCS))),
    ]
    planned = [build("pending") for _, n, build in counts for _ in range(n)]
    p.rng.shuffle(planned)
    for index, item in enumerate(planned, start=1):
        item.set_name = "holdout"
        item.spec.invoice_id = f"H{index:03d}"
        item.spec.template = LAYOUTS[index % len(LAYOUTS)]
        item.spec.knobs["template"] = item.spec.template
        item.scan = IMAGE_TYPES[index % len(IMAGE_TYPES)] if not item.obscured_fields else item.scan
        item.file_format = {"none": "pdf", "mild": "pdf", "photo": "jpg", "web": "png"}[item.scan]
    return planned


def web_image(page: Image.Image, rng: random.Random) -> Image.Image:
    """An invoice image as found on a website or in a chat: about 700-1000 px wide, softened by resizing."""
    width = rng.randint(700, 1000)
    small = page.resize((width, round(page.height * width / page.width)), Image.BILINEAR)
    return small.convert("P", palette=Image.ADAPTIVE, colors=128).convert("RGB") if rng.random() < 0.5 else small


def render_holdout(planned: PlannedInvoice, out_dir: Path, seed: int) -> Label:
    """Write one held-out invoice and return its label (field boxes are dropped for photos: not tracked)."""
    spec = planned.spec
    rng = random.Random(f"{seed}-holdout-{spec.invoice_id}")
    buffer = io.BytesIO()
    result = HOLDOUT_RENDERERS[spec.template](spec, buffer)
    level, boxes, degradations = planned.scan, result.field_boxes, []
    if result.page_count > 1 and level in ("photo", "web"):
        level = "mild"  # photos and web images hold one page
    if level == "none":
        file_format, path = "pdf", out_dir / f"{spec.invoice_id}.pdf"
        path.write_bytes(buffer.getvalue())
    elif level == "mild":
        scan = degrade(buffer.getvalue(), boxes, "mild", [], rng)
        file_format, path = "pdf", out_dir / f"{spec.invoice_id}.pdf"
        save_scan(scan, path, "pdf")
        boxes, degradations = scan.field_boxes, scan.degradations
    else:
        page = rasterise(buffer.getvalue(), 200)[0][0]
        if level == "photo":
            image, boxes, degradations = phone_photo(page, rng), {}, ["phone_photo"]
            file_format, path = "jpg", out_dir / f"{spec.invoice_id}.jpg"
            image.save(path, "JPEG", quality=85)
        else:
            image, degradations = web_image(page, rng), ["web_lowres"]
            file_format, path = "png", out_dir / f"{spec.invoice_id}.png"
            image.save(path, "PNG", optimize=True)
    return Label(
        invoice_id=spec.invoice_id, file_name=path.name, set_name="holdout", scenario=planned.scenario,
        template=spec.template, is_scanned=level != "none", scan_level=level, file_format=file_format,
        degradations=degradations, ground_truth=ground_truth(spec, result.page_count), field_boxes=boxes,
        obscured_fields=planned.obscured_fields, rules_eval_signals=planned.rules_eval_signals(),
        expected_decision=planned.expected_decision, acceptable_decisions=planned.acceptable_decisions,
        expected_reason_codes=planned.expected_reason_codes,
        expected_reason_codes_any_of=planned.expected_reason_codes_any_of,
        true_po_number=planned.true_po_number, knobs=spec.knobs,
        notes=(planned.notes + " Held-out layout/image type.").strip(),
    )


def only_pos_added(md) -> bool:
    """True when, compared with data/master, the holdout only added POs: vendors, buyer and history identical,
    and every existing PO header and line still present unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        write_master(md, Path(tmp))
        same = all((MASTER_DIR / n).read_bytes() == (Path(tmp) / n).read_bytes()
                   for n in ("buyer.json", "vendors.csv", "invoice_history.csv"))
        kept = all(set((MASTER_DIR / n).read_text(encoding="utf-8").splitlines())
                   <= set((Path(tmp) / n).read_text(encoding="utf-8").splitlines())
                   for n in ("po_headers.csv", "po_lines.csv"))
        return same and kept


def main(seed: int = DEFAULT_SEED) -> None:
    md = build_master(seed)
    planner = Planner(md, seed)
    plan_golden(planner)
    plan_stress(planner)
    planned = plan_holdout(planner)
    if not only_pos_added(md):
        raise SystemExit("Planning the holdout changed more than adding POs; refusing to write.")
    write_master(md, MASTER_DIR)
    (OUT_DIR / "labels").mkdir(parents=True, exist_ok=True)
    for pattern in ("*.pdf", "*.png", "*.jpg", "labels/*.json"):
        for old in OUT_DIR.glob(pattern):
            old.unlink()
    labels = []
    for item in planned:
        label = render_holdout(item, OUT_DIR, seed)
        write_label(label, OUT_DIR / "labels")
        labels.append(label)
    checks = verify_digital(labels, {"holdout": OUT_DIR})
    passed = sum(c.passed for c in checks)
    print(f"Holdout: {len(labels)} invoices in {OUT_DIR}")
    for kind in ("template", "scan_level", "expected_decision"):
        counts: dict[str, int] = {}
        for l in labels:
            counts[getattr(l, kind)] = counts.get(getattr(l, kind), 0) + 1
        print(f"  {kind}: {counts}")
    print(f"  self-check (digital: value in text layer inside its box): {passed}/{len(checks)}")
    for c in checks:
        if not c.passed:
            print("   FAIL", c)


if __name__ == "__main__":
    main()
