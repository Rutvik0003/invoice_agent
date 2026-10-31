"""Evaluate the rules engine (stages 4-8) on every labelled invoice - no AI, no OCR, runs in seconds.

Each invoice uses its label's ground truth plus rules_eval_signals (the confidence / verification status the
rules should assume), and is judged independently against the seeded master data.

Usage: python backend/scripts/eval_rules.py --set golden|stress|holdout|all [--show S0042]
"""

from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from datetime import datetime

from eval_common import REPORT_DIR, ground_truth_invoice, load_labels

from app.config import REPO_ROOT, get_settings
from app.pipeline.engine import RulesResult, run_rules
from app.pipeline.evaluation import judge as judge_outcome
from app.pipeline.reason_codes import inr
from app.pipeline.repository import InMemoryRepository
from app.schemas import ExtractedInvoice, FieldVerification, VerificationResult

OUTCOMES = ("APPROVE", "HOLD", "REJECT")


def invoice_from_label(label: dict) -> ExtractedInvoice:
    """Ground truth, with each field's confidence taken from rules_eval_signals (default 0.95)."""
    invoice = ground_truth_invoice(label)
    updates = {}
    for name, signal in label["rules_eval_signals"].items():
        updates[name] = getattr(invoice, name).model_copy(update={"confidence": signal["confidence"]})
    lines = [line.model_copy(update={"confidence": 0.95}) for line in invoice.line_items]
    return invoice.model_copy(update={**updates, "line_items": lines})


def verification_from_label(label: dict) -> VerificationResult:
    fields = {name: FieldVerification(status=s["verification_status"]) for name, s in label["rules_eval_signals"].items()}
    statuses = {f.status for f in fields.values()}
    engine = "unavailable" if statuses <= {"unavailable", "not_applicable"} else ("ocr" if label["is_scanned"] else "text_layer")
    return VerificationResult(engine_used=engine, fields=fields)


def judge(label: dict, result: RulesResult) -> tuple[bool, list[str]]:
    """Pass = decision acceptable AND every must-include code present AND each any-of group satisfied."""
    return judge_outcome(label, result.decision.outcome, result.codes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", default="all", choices=["golden", "stress", "holdout", "all"])
    parser.add_argument("--show", help="print every check for one invoice id")
    args = parser.parse_args()

    settings = get_settings()
    repo = InMemoryRepository.from_master_dir(REPO_ROOT / "data" / "master")
    started = time.time()
    results = []
    for _, label in load_labels(args.set):
        result = run_rules(invoice_from_label(label), verification_from_label(label), repo, settings)
        ok, problems = judge(label, result)
        results.append((label, result, ok, problems))
        if args.show == label["invoice_id"]:
            print(f"\n{label['invoice_id']} {label['scenario']}: expected {label['expected_decision']} "
                  f"{label['expected_reason_codes']}\n{result.decision.summary}")
            for stage in result.stages:
                for c in stage.checks:
                    print(f"  [{stage.stage:16}] {'ok ' if c.passed and not c.code else (c.code or '')[:30]:30} {c.message}")

    by_set = defaultdict(lambda: [0, 0])
    by_scenario = defaultdict(lambda: [0, 0])
    confusion = Counter()
    for label, result, ok, _ in results:
        by_set[label["set_name"]][0] += ok
        by_set[label["set_name"]][1] += 1
        by_scenario[label["scenario"]][0] += ok
        by_scenario[label["scenario"]][1] += 1
        confusion[(label["expected_decision"], result.decision.outcome)] += 1
    total_ok = sum(ok for *_, ok, _ in results)

    lines = [f"# Rules evaluation ({args.set}, {len(results)} invoices)", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. Ground truth + rules_eval_signals, no AI, no OCR, "
             f"each invoice judged independently against the seeded master data.", "",
             f"**Overall: {total_ok}/{len(results)} = {100 * total_ok / len(results):.1f}%**", ""]
    lines += [f"- {name}: {ok}/{n} = {100 * ok / n:.1f}%" for name, (ok, n) in sorted(by_set.items())]
    lines += ["", "## Confusion matrix (rows = expected, columns = actual)", "",
              "| Expected \\ Actual | " + " | ".join(OUTCOMES) + " |", "|---|" + "---:|" * len(OUTCOMES)]
    for expected in OUTCOMES:
        lines.append(f"| {expected} | " + " | ".join(str(confusion[(expected, actual)]) for actual in OUTCOMES) + " |")
    lines += ["", "## Pass rate by scenario", "", "| Scenario | Passed | Total |", "|---|---:|---:|"]
    lines += [f"| {s} | {ok} | {n} |" for s, (ok, n) in sorted(by_scenario.items())]
    failures = [(l, r, p) for l, r, ok, p in results if not ok]
    lines += ["", f"## Failures ({len(failures)})", ""]
    for label, result, problems in failures:
        lines += [f"### {label['invoice_id']} - {label['scenario']}", f"- Problems: {'; '.join(problems)}",
                  f"- Expected: {label['expected_decision']} {label['expected_reason_codes']}",
                  f"- Actual: {result.decision.outcome} {sorted(set(result.codes))}",
                  f"- Scenario notes: {label['notes']}", ""]
    if not failures:
        lines.append("- none")
    lines += ["", "## Sample outputs", ""]
    for label, result, *_ in results:
        if label["set_name"] == "golden":
            d = result.decision
            lines += [f"### {label['invoice_id']} -> {d.outcome}", "", d.summary, ""]
            for q in d.routed_questions:
                lines += [f"**Routed to {q.role}:**", "", "```", q.question, "```", ""]
            if d.vendor_note:
                lines += ["**Draft vendor note:**", "", "```", d.vendor_note, "```", ""]
            if d.ledger_update:
                lines += [f"**Ledger update:** {d.ledger_update.po_number}: "
                          + ", ".join(f"line {l.po_line_no} +{l.quantity:g}" for l in d.ledger_update.lines)
                          + f"; history += {d.ledger_update.history_row['invoice_number']} "
                            f"(₹{inr(d.ledger_update.total_amount)})", ""]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"rules_eval_{args.set}_{stamp}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:20]))
    for label, result, problems in failures[:40]:
        print(f"  FAIL {label['invoice_id']} {label['scenario']}: {'; '.join(problems)} | actual {sorted(set(result.codes))}")
    print(f"Report: {path}  ({time.time() - started:.1f}s)")


if __name__ == "__main__":
    main()
