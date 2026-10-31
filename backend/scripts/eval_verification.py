"""Evaluate Stage 3 verification on generated invoices - NO AI calls.

  a) recall: is each true printed value (not obscured) found? by source and degradation level
  b) box accuracy: IoU of the found box vs the label's field box(es) (exact boxes only)
  c) fault injection: plausible AI mistakes must come back not_found (catch rate)
  d) obscured fields must come back not_found

Usage: python backend/scripts/eval_verification.py --set golden|stress|holdout|real_world|all [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import time
from collections import defaultdict
from datetime import datetime

from eval_common import REPORT_DIR, degradation_level, ground_truth_invoice, load_labels

from app.config import get_settings
from app.db import get_engine
from app.extraction import file_hash
from app.extraction.pdf_utils import guess_mime
from app.models import Base
from app.schemas import ExtractedInvoice
from app.verification.page_text import PageWords
from app.verification.verify import VERIFIED_FIELDS, collect_page_words, verify

TARGETS = {"text_layer_recall": 100.0, "mild_recall": 95.0, "catch_rate": 98.0}


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _change_digit(text: str, rng: random.Random, skip_last: int = 0) -> str | None:
    """Change one digit (not among the last `skip_last` digits, e.g. paise / the rupee within ± ₹1 tolerance)."""
    positions = [i for i, ch in enumerate(text) if ch.isdigit()]
    if skip_last:
        positions = positions[:-skip_last]
    if not positions:
        return None
    i = rng.choice(positions)
    return text[:i] + rng.choice([d for d in "0123456789" if d != text[i]]) + text[i + 1:]


def _swap_digits(text: str, rng: random.Random) -> str | None:
    """Swap two adjacent, different digits (a classic transcription error)."""
    pairs = [i for i in range(len(text) - 1) if text[i].isdigit() and text[i + 1].isdigit() and text[i] != text[i + 1]]
    if not pairs:
        return None
    i = rng.choice(pairs)
    return text[:i] + text[i + 1] + text[i] + text[i + 2:]


def _other_gstin(gstin: str, rng: random.Random) -> str:
    """A different, checksum-valid GSTIN in the same state (what a model might confuse it with)."""
    from datagen.gstin import make_gstin, make_pan  # generator helper; evaluation code only

    return make_gstin(gstin[:2], make_pan(gstin[5], rng), 1)


def faults_for(label: dict, rng: random.Random) -> list[tuple[str, str, object]]:
    """(field, fault kind, wrong value) - the hallucinations the verifier must catch."""
    gt = label["ground_truth"]
    faults = []
    total = gt["total_amount"]["value"]
    if total is not None:
        wrong = _change_digit(f"{total:.2f}", rng, skip_last=3)  # skip paise and the units rupee (± ₹1 tolerance)
        if wrong and abs(float(wrong) - total) > 1:
            faults.append(("total_amount", "digit_changed", float(wrong)))
        faults.append(("total_amount", "plus_minus_100", total + rng.choice([-100, 100])))
    number = gt["invoice_number"]["value"]
    if number:
        swapped = _swap_digits(number, rng)
        if swapped:
            faults.append(("invoice_number", "digits_swapped", swapped))
        changed = _change_digit(number, rng)
        if changed:
            faults.append(("invoice_number", "digit_changed", changed))
    if gt["vendor_gstin"]["value"]:
        faults.append(("vendor_gstin", "other_valid_gstin", _other_gstin(gt["vendor_gstin"]["value"], rng)))
    return faults


def with_value(invoice: ExtractedInvoice, field: str, value: object) -> ExtractedInvoice:
    changed = getattr(invoice, field).model_copy(update={"value": value})
    return invoice.model_copy(update={field: changed})


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 2) if d else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", default="all", choices=["golden", "stress", "holdout", "real_world", "all"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-cache", action="store_true", help="re-run OCR instead of using cached page words")
    args = parser.parse_args()

    settings = get_settings()
    engine = None if args.no_cache else get_engine()
    if engine is not None:
        Base.metadata.create_all(engine)
    items = load_labels(args.set)[: args.limit]
    rng = random.Random(7)
    recall = defaultdict(lambda: [0, 0])  # (source, level) -> [found, total]
    recall_field = defaultdict(lambda: [0, 0])
    ious: list[float] = []
    faults = defaultdict(lambda: [0, 0])  # (field, kind) -> [caught, total]
    false_verifications: list[str] = []
    obscured = [0, 0]
    misses: list[str] = []
    rows = []
    started = time.time()

    for index, (path, label) in enumerate(items, start=1):
        data = path.read_bytes()
        pages: list[PageWords] = collect_page_words(data, guess_mime(path.name), settings, engine, file_hash(data))
        invoice = ground_truth_invoice(label)
        result = verify(invoice, pages, settings)
        level = degradation_level(label)
        page_source = {p.page: p.source for p in pages}
        for field in VERIFIED_FIELDS:
            printed = label["ground_truth"][field]["printed"]
            if printed is None:
                continue
            status = result.fields[field]
            if field in label["obscured_fields"]:
                obscured[1] += 1
                obscured[0] += status.status == "not_found"
                continue
            box = label["field_boxes"].get(field)
            source = page_source.get(box["page"], "unknown") if box else "unknown"
            found = status.status == "verified"
            recall[(source, level)][0] += found
            recall[(source, level)][1] += 1
            recall_field[(field, source)][0] += found
            recall_field[(field, source)][1] += 1
            if not found:
                misses.append(f"{label['invoice_id']} {field} ({source}, {level}): printed `{printed}`")
            occurrences = [b for k, b in label["field_boxes"].items()
                           if (k == field or k.startswith(field + "#")) and not b.get("approximate")]
            if found and occurrences:
                same_page = [b for b in occurrences if b["page"] == status.page]
                if same_page:
                    ious.append(max(iou(status.bbox, b["bbox"]) for b in same_page))
            rows.append({"invoice_id": label["invoice_id"], "field": field, "source": source, "level": level,
                         "status": status.status, "matched_text": status.matched_text or "", "printed": printed})
        for field, kind, wrong in faults_for(label, rng):
            if field in label["obscured_fields"]:
                continue
            check = verify(with_value(invoice, field, wrong), pages, settings).fields[field]
            caught = check.status in ("not_found", "unavailable")
            faults[(field, kind)][0] += caught
            faults[(field, kind)][1] += 1
            if not caught:
                false_verifications.append(f"{label['invoice_id']} {field} {kind}: wrong value `{wrong}` "
                                           f"matched `{check.matched_text}` ({check.source})")
        if index % 25 == 0:
            print(f"  {index}/{len(items)} files ({time.time() - started:.0f}s)")

    # ----- report
    def total(keys_filter) -> tuple[int, int]:
        f = sum(v[0] for k, v in recall.items() if keys_filter(k))
        t = sum(v[1] for k, v in recall.items() if keys_filter(k))
        return f, t

    text_layer = total(lambda k: k[0] == "text_layer")
    mild = total(lambda k: k[0] == "ocr" and k[1] == "mild")
    heavy = total(lambda k: k[0] == "ocr" and k[1] == "heavy")
    caught = sum(v[0] for v in faults.values()), sum(v[1] for v in faults.values())
    ious_sorted = sorted(ious)
    median_iou = ious_sorted[len(ious_sorted) // 2] if ious_sorted else 0.0
    summary = {
        "text_layer_recall": pct(*text_layer),
        "mild_recall": pct(*mild),
        "heavy_recall": pct(*heavy),
        "catch_rate": pct(*caught),
        "obscured_not_found": pct(*obscured),
        "mean_iou": round(sum(ious) / len(ious), 3) if ious else 0.0,
        "median_iou": round(median_iou, 3),
        "iou_over_0_5": pct(sum(i > 0.5 for i in ious), len(ious)),
    }
    lines = [
        f"# Verification evaluation ({args.set}, {len(items)} files)", "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M}. No AI calls: ground-truth values are verified against the page.", "",
        "| Metric | Result | Target |", "|---|---:|---:|",
        f"| Recall, text layer | {summary['text_layer_recall']}% ({text_layer[0]}/{text_layer[1]}) | 100% |",
        f"| Recall, OCR mild scans | {summary['mild_recall']}% ({mild[0]}/{mild[1]}) | ≥ 95% |",
        f"| Recall, OCR heavy scans (info) | {summary['heavy_recall']}% ({heavy[0]}/{heavy[1]}) | - |",
        f"| Fault-injection catch rate | {summary['catch_rate']}% ({caught[0]}/{caught[1]}) | ≥ 98% |",
        f"| Obscured fields reported not_found | {summary['obscured_not_found']}% ({obscured[0]}/{obscured[1]}) | 100% |",
        f"| Box IoU (exact boxes): mean / median / share > 0.5 | {summary['mean_iou']} / {summary['median_iou']} / "
        f"{summary['iou_over_0_5']}% | - |",
        "", "## Recall by field and source", "", "| Field | Source | Found | Total | Recall |", "|---|---|---:|---:|---:|",
    ]
    for (field, source), (f, t) in sorted(recall_field.items()):
        lines.append(f"| {field} | {source} | {f} | {t} | {pct(f, t)}% |")
    lines += ["", "## Fault injection by field", "", "| Field | Fault | Caught | Total | Rate |", "|---|---|---:|---:|---:|"]
    for (field, kind), (c, t) in sorted(faults.items()):
        lines.append(f"| {field} | {kind} | {c} | {t} | {pct(c, t)}% |")
    lines += ["", "## False verifications (wrong value accepted)", ""]
    lines += [f"- {x}" for x in false_verifications[:60]] or ["- none"]
    lines += ["", "## Missed true values", ""]
    lines += [f"- {x}" for x in misses[:80]] or ["- none"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORT_DIR / f"verification_eval_{args.set}_{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (REPORT_DIR / f"verification_eval_{args.set}_{stamp}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["invoice_id", "field", "source", "level", "status", "matched_text", "printed"])
        writer.writeheader()
        writer.writerows(rows)
    print("\n".join(lines[:12]))
    for name, target in TARGETS.items():
        print(f"  {name}: {summary[name]}% (target {target}%) -> {'OK' if summary[name] >= target else 'BELOW TARGET'}")
    print(f"Report: {md_path}  ({time.time() - started:.0f}s)")


if __name__ == "__main__":
    main()
