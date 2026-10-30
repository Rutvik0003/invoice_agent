"""Single entry point that writes all master data (and, from Phase 2, invoices) in one consistent run.

Usage: python -m datagen.generate_all [--master-only] [--seed N]
"""

import argparse
from collections import Counter
from pathlib import Path

from datagen.master_data import DEFAULT_SEED, MasterData, build_master, write_master

REPO_ROOT = Path(__file__).resolve().parents[1]
MASTER_DIR = REPO_ROOT / "data" / "master"


def generate(seed: int = DEFAULT_SEED, master_only: bool = True, out_dir: Path = MASTER_DIR) -> MasterData:
    """Build master data, let scenarios add what they need (Phase 2), then write everything."""
    md = build_master(seed)
    if not master_only:
        print("Invoice generation arrives in Phase 2; writing master data only.")
    write_master(md, out_dir)
    return md


def _summary(md: MasterData) -> str:
    vendor_status = Counter(v.status for v in md.vendors)
    po_status = Counter(p.status for p in md.pos)
    intra = sum(v.is_intra_state for v in md.vendors)
    return "\n".join([
        f"Vendors: {len(md.vendors)} ({dict(vendor_status)}), {intra} in Maharashtra, "
        f"{len({v.state_code for v in md.vendors})} states",
        f"POs: {len(md.pos)} ({dict(po_status)}), {sum(len(p.lines) for p in md.pos)} lines",
        f"Invoice history: {len(md.history)} rows",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-only", action="store_true", help="write only data/master (no invoices)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    md = generate(args.seed, args.master_only)
    print(_summary(md))
    print(f"Written to {MASTER_DIR}")


if __name__ == "__main__":
    main()
