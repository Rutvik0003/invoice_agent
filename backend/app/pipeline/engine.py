"""Stages 4-8 as one pure function: extracted invoice + verification + master data -> checks and a decision."""

from __future__ import annotations

import time
from typing import Callable

from pydantic import BaseModel

from app.config import Settings
from app.pipeline.amount_match import LineMatch, run_amount_match
from app.pipeline.decision import decide
from app.pipeline.duplicate_check import run_duplicate_check
from app.pipeline.po_match import run_po_match
from app.pipeline.reason_codes import passed
from app.pipeline.repository import MasterRepository
from app.pipeline.self_check import run_self_check
from app.pipeline.vendor_check import run_vendor_check
from app.schemas import CheckResult, Decision, ExtractedInvoice, VerificationResult

STAGES = (
    ("self_check", "Clean up & self-check"),
    ("vendor_duplicate", "Vendor & duplicate check"),
    ("po_match", "Find the PO"),
    ("amount_match", "Match amounts"),
    ("decision", "Decision"),
)
TITLES = dict(STAGES)


class StageResult(BaseModel):
    stage: str
    title: str
    checks: list[CheckResult]
    duration_ms: int = 0


class RulesResult(BaseModel):
    stages: list[StageResult]
    decision: Decision
    vendor_id: str | None
    po_number: str | None
    po_inferred: bool
    po_candidates: list[dict] = []

    @property
    def codes(self) -> list[str]:
        return [c.code for c in self.decision.reasons]


def run_rules(inv: ExtractedInvoice, ver: VerificationResult, repo: MasterRepository, settings: Settings,
              file_hash: str | None = None, on_stage: Callable[[StageResult], None] | None = None) -> RulesResult:
    """Run stages 4-8 in order. Every stage always runs where it can, so every reason is listed.

    on_stage (optional) is called as each stage finishes, so a live view can show progress.
    """
    stages: list[StageResult] = []
    clock = time.monotonic()

    def finish(key: str, checks: list[CheckResult]) -> None:
        nonlocal clock
        now = time.monotonic()
        stage = StageResult(stage=key, title=TITLES[key], checks=checks, duration_ms=int((now - clock) * 1000))
        clock = now
        stages.append(stage)
        if on_stage:
            on_stage(stage)

    self_checks = run_self_check(inv, ver, repo.buyer, settings)
    finish("self_check", self_checks)
    vendor, vendor_checks = run_vendor_check(inv, repo)
    vendor_checks += run_duplicate_check(inv, vendor, repo, ver, settings, file_hash)
    finish("vendor_duplicate", vendor_checks)
    po, inferred, po_checks, ranked = run_po_match(inv, vendor, repo, settings)
    finish("po_match", po_checks)
    matches: list[LineMatch] = []
    if po is not None:
        matches, amount_checks = run_amount_match(inv, po, settings)
    else:
        amount_checks = [passed("amount_match", "skipped", "Amounts not matched: there is no PO to match against.")]
    finish("amount_match", amount_checks)
    decision = decide(self_checks + vendor_checks + po_checks + amount_checks, inv, repo.buyer, vendor, po, matches)
    finish("decision", [])
    return RulesResult(
        stages=stages, decision=decision, vendor_id=vendor.vendor_id if vendor else None,
        po_number=po.po_number if po else None, po_inferred=inferred,
        po_candidates=[{"po_number": c.po.po_number, "score": c.score, "item_similarity": c.item_similarity,
                        "amount_closeness": c.amount_closeness, "qty_match": c.qty_match} for c in ranked[:3]],
    )
