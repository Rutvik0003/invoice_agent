"""The rules engine on the real generated data: database vs in-memory parity, and the Phase 4 targets."""

import sys

import pytest
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.db import make_engine
from app.pipeline.repository import DbRepository, InMemoryRepository
from app.seed import seed_master
from tests.rules_fixtures import SETTINGS

sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))
from eval_common import load_labels  # noqa: E402
from eval_rules import judge, rules_for_label  # noqa: E402

MASTER = REPO_ROOT / "data" / "master"


@pytest.fixture(scope="module")
def memory_repo():
    return InMemoryRepository.from_master_dir(MASTER)


@pytest.fixture(scope="module")
def labels():
    return load_labels("all")


def test_database_and_memory_repositories_agree(tmp_path, memory_repo, labels):
    engine = make_engine(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    seed_master(engine, MASTER)
    with Session(engine) as session:
        db_repo = DbRepository(session, memory_repo.buyer)
        for _, label in labels[:40]:
            a = rules_for_label(label, memory_repo, SETTINGS)
            b = rules_for_label(label, db_repo, SETTINGS)
            assert a.decision.outcome == b.decision.outcome, label["invoice_id"]
            assert sorted(a.codes) == sorted(b.codes), label["invoice_id"]
    engine.dispose()


def test_golden_set_is_twelve_out_of_twelve(memory_repo, labels):
    failures = []
    for _, label in labels:
        if label["set_name"] != "golden":
            continue
        ok, problems = judge(label, rules_for_label(label, memory_repo, SETTINGS))
        if not ok:
            failures.append((label["invoice_id"], problems))
    assert failures == []


def test_stress_set_meets_the_98_percent_target(memory_repo, labels):
    stress = [label for _, label in labels if label["set_name"] == "stress"]
    passed = sum(judge(l, rules_for_label(l, memory_repo, SETTINGS))[0]
                 for l in stress)
    assert passed / len(stress) >= 0.98
