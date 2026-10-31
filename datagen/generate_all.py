"""Single entry point: master data + golden and stress invoices, written in one consistent run.

Usage: python -m datagen.generate_all [--master-only] [--seed N]

Scenarios are always planned (they add the POs and history they need), so the master CSVs are the
same whether or not invoice files are rendered.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter
from pathlib import Path

from datagen.contact_sheet import box_check, contact_sheet
from datagen.holdout import plan_holdout
from datagen.labels import Label
from datagen.master_data import DEFAULT_SEED, MasterData, build_master, write_master
from datagen.render import render_planned, write_label
from datagen.scenarios import PlannedInvoice, Planner, plan_golden, plan_stress
from datagen.self_verify import FieldCheck, verify_digital
from datagen.validate_master import load_master, run_checks

REPO_ROOT = Path(__file__).resolve().parents[1]
MASTER_DIR = REPO_ROOT / "data" / "master"
INVOICE_DIR = REPO_ROOT / "data" / "invoices"
STRESS_SHEET_SIZE = 48


def plan(seed: int = DEFAULT_SEED) -> tuple[MasterData, list[PlannedInvoice], list[PlannedInvoice]]:
    md = build_master(seed)
    planner = Planner(md, seed)
    golden, stress = plan_golden(planner), plan_stress(planner)
    plan_holdout(planner)  # adds the held-out set's POs to the master data (rendered by datagen.holdout)
    return md, golden, stress


def _clear(folder: Path) -> None:
    """Remove previously generated files (only invoice files and labels, never anything else)."""
    for pattern in ("*.pdf", "*.png", "*.jpg", "labels/*.json"):
        for path in folder.glob(pattern):
            path.unlink()


def render_all(planned: list[PlannedInvoice], seed: int, invoice_dir: Path) -> list[Label]:
    labels = []
    for set_name in ("golden", "stress"):
        folder = invoice_dir / set_name
        (folder / "labels").mkdir(parents=True, exist_ok=True)
        _clear(folder)
    for index, item in enumerate(planned, start=1):
        folder = invoice_dir / item.set_name
        label = render_planned(item, folder, seed)
        write_label(label, folder / "labels")
        labels.append(label)
        if index % 25 == 0:
            print(f"  rendered {index}/{len(planned)}")
    return labels


def _table(counter: Counter, title: str) -> list[str]:
    lines = [f"| {title} | Count |", "|---|---:|"]
    lines += [f"| {key} | {count} |" for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))]
    return lines + [""]


def write_report(labels: list[Label], checks: list[FieldCheck], master_ok: bool, out_path: Path) -> str:
    golden = [l for l in labels if l.set_name == "golden"]
    stress = [l for l in labels if l.set_name == "stress"]
    passed = sum(c.passed for c in checks)
    lines = [
        "# Invoice generation report",
        "",
        f"- Golden invoices: **{len(golden)}**, stress invoices: **{len(stress)}**",
        f"- Master data consistency after scenarios: **{'all checks passed' if master_ok else 'FAILED'}**",
        f"- Self-verification (digital PDFs, value in text layer and inside its box, IoU > 0.5): "
        f"**{passed}/{len(checks)} = {100 * passed / max(len(checks), 1):.1f}%**",
        "",
        "## Golden set",
        "",
        "| Invoice | Scenario | Template | Scan | Expected | Must-include codes |",
        "|---|---|---|---|---|---|",
    ]
    for l in golden:
        codes = ", ".join(l.expected_reason_codes) or (
            " or ".join(l.expected_reason_codes_any_of[0]) if l.expected_reason_codes_any_of else "-")
        lines.append(f"| {l.invoice_id} | {l.scenario} | {l.template} | {l.scan_level} | {l.expected_decision} | {codes} |")
    lines += ["", "## Stress set", ""]
    lines += _table(Counter(l.scenario for l in stress), "Scenario")
    lines += _table(Counter(l.expected_decision for l in stress), "Expected decision")
    lines += _table(Counter(l.template for l in stress), "Template")
    lines += _table(Counter(f"{l.scan_level} ({l.file_format})" if l.is_scanned else "digital (pdf)" for l in stress), "Scan / format")
    lines += _table(Counter(l.ground_truth["page_count"]["value"] for l in stress), "Pages")
    decisions = Counter(l.expected_decision for l in labels)
    lines += ["## Overall expected decisions (golden + stress)", ""]
    lines += [f"- {d}: {n} ({100 * n / len(labels):.0f}%)" for d, n in sorted(decisions.items())]
    failures = [c for c in checks if not c.passed]
    if failures:
        lines += ["", "## Self-verification failures", ""]
        lines += [f"- {c.invoice_id} {c.field}: expected `{c.expected}`, found `{c.found}` (IoU {c.iou:.2f})" for c in failures[:50]]
    text = "\n".join(lines) + "\n"
    out_path.write_text(text, encoding="utf-8")
    return text


def generate(seed: int = DEFAULT_SEED, master_only: bool = False) -> int:
    started = time.time()
    md, golden, stress = plan(seed)
    write_master(md, MASTER_DIR)
    master_ok = all(o.passed for o in run_checks(load_master(MASTER_DIR)))
    print(f"Master data: {len(md.vendors)} vendors, {len(md.pos)} POs, {len(md.history)} history rows "
          f"-> consistency {'OK' if master_ok else 'FAILED (run python -m datagen.validate_master)'}")
    if master_only:
        return 0 if master_ok else 1
    print(f"Rendering {len(golden)} golden + {len(stress)} stress invoices ...")
    labels = render_all(golden + stress, seed, INVOICE_DIR)
    checks = verify_digital(labels, {"golden": INVOICE_DIR / "golden", "stress": INVOICE_DIR / "stress"})
    folders = {"golden": INVOICE_DIR / "golden", "stress": INVOICE_DIR / "stress"}
    items = [(folders[l.set_name] / l.file_name, l) for l in labels]
    contact_sheet([i for i in items if i[1].set_name == "golden"], INVOICE_DIR / "contact_sheet_golden.png", columns=4)
    stress_items = [i for i in items if i[1].set_name == "stress"]
    for old in INVOICE_DIR.glob("contact_sheet_stress_*.png"):
        old.unlink()
    for n, start in enumerate(range(0, len(stress_items), STRESS_SHEET_SIZE), start=1):
        contact_sheet(stress_items[start:start + STRESS_SHEET_SIZE], INVOICE_DIR / f"contact_sheet_stress_{n}.png")
    for old in INVOICE_DIR.glob("box_check_*.png"):
        old.unlink()
    rng = random.Random(seed)
    picks = rng.sample([i for i in items if not i[1].is_scanned], 3) + rng.sample([i for i in items if i[1].is_scanned], 2)
    for path, label in picks:
        box_check(path, label, INVOICE_DIR / f"box_check_{label.invoice_id}.png")
    report = write_report(labels, checks, master_ok, INVOICE_DIR / "generation_report.md")
    print(report.split("## Golden set")[0])
    print(f"Done in {time.time() - started:.0f}s. Report: {INVOICE_DIR / 'generation_report.md'}")
    all_verified = all(c.passed for c in checks)
    return 0 if master_ok and all_verified else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-only", action="store_true", help="write only data/master (no invoice files)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    sys.exit(generate(args.seed, args.master_only))


if __name__ == "__main__":
    main()
