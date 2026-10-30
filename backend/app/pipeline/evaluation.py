"""Judging a decision against a generated invoice's label (shared by eval_rules.py and the in-app Test Suite)."""

from __future__ import annotations


def judge(label: dict, outcome: str | None, codes: list[str]) -> tuple[bool, list[str]]:
    """Pass = decision acceptable AND every must-include code present AND each any-of group satisfied."""
    problems = []
    present = set(codes)
    if outcome not in label["acceptable_decisions"]:
        problems.append(f"decision {outcome}, expected {label['expected_decision']}")
    missing = [c for c in label["expected_reason_codes"] if c not in present]
    if missing:
        problems.append(f"missing codes {missing}")
    for group in label.get("expected_reason_codes_any_of", []):
        if not present & set(group):
            problems.append(f"none of {group}")
    return not problems, problems
