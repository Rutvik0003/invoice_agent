"""Evaluate AI extraction against label ground truth.

Usage: python backend/scripts/eval_extraction.py --set golden|stress|holdout|real_world --model gemini|groq|both
           [--sample N] [--delay 13] [--no-cache]

Resumable: results are cached by (file hash, model), so a re-run only calls the model for files not done yet.
Free-tier friendly: waits --delay seconds after every real model call.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from collections import defaultdict
from datetime import datetime

from eval_common import REPORT_DIR, degradation_level, load_labels

from app.config import get_settings
from app.db import get_engine
from app.extraction import extract_document
from app.extraction.pdf_utils import guess_mime
from app.models import Base
from app.schemas import ExtractedInvoice
from app.verification.matchers import normalise_code, normalise_identifier, parse_date

FIELDS = ["document_type", "invoice_number", "invoice_date", "vendor_gstin", "buyer_gstin", "po_reference",
          "total_amount", "subtotal", "cgst", "sgst", "igst", "line_count", "line_amounts"]


def _amount_equal(truth: float | None, got: float | None, zero_is_absent: bool = False) -> bool:
    if zero_is_absent:
        truth = truth or None
        got = got or None
    if truth is None or got is None:
        return truth is None and got is None
    return abs(truth - got) <= 1.0


def _date_iso(value: str | None) -> str | None:
    if not value:
        return None
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else value


def score(label: dict, invoice: ExtractedInvoice) -> dict[str, bool]:
    """Per-field correctness after normalisation (the same rules the pipeline uses)."""
    gt = label["ground_truth"]

    def ident(name: str) -> bool:
        truth, got = gt[name]["value"], getattr(invoice, name).value
        if not truth or not got:
            return not truth and not got
        return normalise_identifier(truth) == normalise_identifier(got)

    def code(name: str) -> bool:
        truth, got = gt[name]["value"], getattr(invoice, name).value
        if not truth or not got:
            return not truth and not got
        return normalise_code(truth) == normalise_code(got)

    truth_lines = sorted(round(l["amount"], 2) for l in gt["line_items"])
    got_lines = sorted(round(l.amount or 0, 2) for l in invoice.line_items)
    return {
        "document_type": gt["document_type"]["value"] == invoice.document_type.value,
        "invoice_number": ident("invoice_number"),
        "invoice_date": _date_iso(gt["invoice_date"]["value"]) == _date_iso(invoice.invoice_date.value),
        "vendor_gstin": code("vendor_gstin"),
        "buyer_gstin": code("buyer_gstin"),
        "po_reference": ident("po_reference"),
        "total_amount": _amount_equal(gt["total_amount"]["value"], invoice.total_amount.value),
        "subtotal": _amount_equal(gt["subtotal"]["value"], invoice.subtotal.value),
        "cgst": _amount_equal(gt["cgst"]["value"], invoice.cgst.value, zero_is_absent=True),
        "sgst": _amount_equal(gt["sgst"]["value"], invoice.sgst.value, zero_is_absent=True),
        "igst": _amount_equal(gt["igst"]["value"], invoice.igst.value, zero_is_absent=True),
        "line_count": len(truth_lines) == len(got_lines),
        "line_amounts": len(truth_lines) == len(got_lines) and all(abs(a - b) <= 1 for a, b in zip(truth_lines, got_lines)),
    }


def stratified_sample(items: list, n: int | None) -> list:
    """Round-robin over (template, degradation, scenario) groups so a small sample still covers the variety."""
    if not n or n >= len(items):
        return items
    groups: dict[tuple, list] = defaultdict(list)
    for item in items:
        label = item[1]
        groups[(label.get("template"), degradation_level(label), label.get("scenario"))].append(item)
    queues = [list(g) for _, g in sorted(groups.items(), key=lambda kv: str(kv[0]))]
    picked = []
    while len(picked) < n and any(queues):
        for queue in queues:
            if queue and len(picked) < n:
                picked.append(queue.pop(0))
    return picked


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", default="golden", choices=["golden", "stress", "holdout", "real_world"])
    parser.add_argument("--model", default="both", choices=["gemini", "groq", "both"])
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--delay", type=float, default=13.0, help="seconds to wait after each real model call")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    engine = get_engine()
    Base.metadata.create_all(engine)
    items = stratified_sample(load_labels(args.set), args.sample)
    models = ["gemini", "groq"] if args.model == "both" else [args.model]
    rows, errors = [], []
    correct = defaultdict(lambda: [0, 0])  # (model, group, field) -> [right, total]
    latencies = defaultdict(list)
    started = time.time()
    for model in models:
        for index, (path, label) in enumerate(items, start=1):
            result = extract_document(path.read_bytes(), guess_mime(path.name), model, settings, engine,
                                      use_cache=not args.no_cache)
            status = "cached" if result.cached else f"{result.latency_ms} ms"
            if result.error:
                detail = re.sub(r"organization `[^`]+`", "organization `...`", result.error.detail or result.error.message)
                errors.append(f"{model} {label['invoice_id']}: {result.error.type} - {detail[:240]}")
                print(f"  [{model}] {index}/{len(items)} {label['invoice_id']}: ERROR {result.error.type}")
            else:
                scores = score(label, result.invoice)
                wrong = [f for f, ok in scores.items() if not ok]
                level = degradation_level(label)
                for field, ok in scores.items():
                    for group in ("overall", f"template:{label['template']}", f"level:{level}"):
                        correct[(model, group, field)][0] += ok
                        correct[(model, group, field)][1] += 1
                if not result.cached:
                    latencies[model].append(result.latency_ms)
                rows.append({"model": model, "invoice_id": label["invoice_id"], "template": label["template"],
                             "level": level, "scenario": label["scenario"], "correct": len(scores) - len(wrong),
                             "total": len(scores), "wrong_fields": " ".join(wrong), "cached": result.cached,
                             "latency_ms": result.latency_ms})
                print(f"  [{model}] {index}/{len(items)} {label['invoice_id']} ({status}): "
                      f"{len(scores) - len(wrong)}/{len(scores)}{'  wrong: ' + ', '.join(wrong) if wrong else ''}")
            if not result.cached and index < len(items):
                time.sleep(args.delay)

    groups = sorted({g for (_, g, _) in correct})
    lines = [f"# Extraction evaluation ({args.set}, {len(items)} files, {', '.join(models)})", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. Model names: "
             + ", ".join(f"{m} = {settings.gemini_model if m == 'gemini' else settings.groq_model}" for m in models), ""]
    for model in models:
        right = sum(v[0] for (m, g, _), v in correct.items() if m == model and g == "overall")
        total = sum(v[1] for (m, g, _), v in correct.items() if m == model and g == "overall")
        lat = latencies[model]
        lines.append(f"- **{model}**: field accuracy {pct(right, total)} ({right}/{total})"
                     + (f", median latency {sorted(lat)[len(lat) // 2] / 1000:.1f} s over {len(lat)} live calls" if lat else ""))
    lines += ["", "## Accuracy by field", "", "| Field | " + " | ".join(models) + " |", "|---|" + "---:|" * len(models)]
    for field in FIELDS:
        lines.append(f"| {field} | " + " | ".join(pct(*correct[(m, "overall", field)]) for m in models) + " |")
    for prefix, title in (("level:", "By degradation"), ("template:", "By template")):
        lines += ["", f"## {title} (all fields)", "", "| Group | " + " | ".join(models) + " |", "|---|" + "---:|" * len(models)]
        for group in [g for g in groups if g.startswith(prefix)]:
            cells = []
            for m in models:
                right = sum(v[0] for (mm, g, _), v in correct.items() if mm == m and g == group)
                total = sum(v[1] for (mm, g, _), v in correct.items() if mm == m and g == group)
                cells.append(pct(right, total))
            lines.append(f"| {group.removeprefix(prefix)} | " + " | ".join(cells) + " |")
    worst = sorted(rows, key=lambda r: r["correct"] - r["total"])[:15]
    lines += ["", "## Worst files", "", "| Model | Invoice | Template | Level | Correct | Wrong fields |", "|---|---|---|---|---:|---|"]
    lines += [f"| {r['model']} | {r['invoice_id']} | {r['template']} | {r['level']} | {r['correct']}/{r['total']} | {r['wrong_fields']} |"
              for r in worst]
    lines += ["", "## Errors", ""] + ([f"- {e}" for e in errors] or ["- none"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md = REPORT_DIR / f"extraction_eval_{args.set}_{args.model}_{stamp}.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if rows:
        with (REPORT_DIR / f"extraction_eval_{args.set}_{args.model}_{stamp}.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print("\n".join(lines[: 6 + len(models)]))
    print(f"Report: {md}  ({time.time() - started:.0f}s)")


if __name__ == "__main__":
    main()
