"""Download real receipt photos from CORD v2 (test split) into data/invoices/real_world/ with labels.

CORD v2: real phone photos of Indonesian shop/restaurant receipts, (c) NAVER Clova, licensed CC BY 4.0
(https://huggingface.co/datasets/naver-clova-ix/cord-v2). They are not Indian GST invoices; they test how OCR and
extraction cope with real, unseen photos. Only the subtotal and total are labelled (no GSTIN, no PO, no CGST/SGST).
Files are git-ignored: run this script to fetch them again.

Amounts on these receipts use '.' or ',' to group thousands ("60.000" = sixty thousand rupiah). The labels keep the
printed text and the real value; our matcher reads "60.000" the Indian way (60.00), so such values are expected to
show as not found - a known limit of an INR-only system, reported separately by the evaluation.

Usage: python backend/scripts/fetch_cord.py [--count 20]
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from urllib.parse import quote

from eval_common import SETS

ROWS_URL = ("https://datasets-server.huggingface.co/rows?dataset=" + quote("naver-clova-ix/cord-v2", safe="")
            + "&config=default&split=test&offset=0&length={count}")
OUT = SETS["real_world"]


def idr_value(printed: object) -> float | None:
    """'Rp. 111,000' / '60.000' / '91000' -> 111000.0 / 60000.0 / 91000.0 (rupiah have no decimals)."""
    if isinstance(printed, list):
        printed = printed[0]
    digits = re.sub(r"\D", "", str(printed or ""))
    return float(digits) if digits else None


def label_for(row_idx: int, gt: dict) -> dict:
    sub, total = gt.get("sub_total") or {}, gt.get("total") or {}
    if isinstance(sub, list):
        sub = sub[0]
    if isinstance(total, list):
        total = total[0]

    def field(printed: object) -> dict:
        printed = printed[0] if isinstance(printed, list) else printed
        return {"value": idr_value(printed), "printed": None if printed is None else str(printed)}

    return {
        "invoice_id": f"cord_test_{row_idx:03d}",
        "ground_truth": {
            "document_type": "tax_invoice",
            "subtotal": field(sub.get("subtotal_price")),
            "total_amount": field(total.get("total_price")),
        },
        "source": "CORD v2 test split (naver-clova-ix/cord-v2), CC BY 4.0",
        "notes": "Indonesian receipt photo: no GSTIN/PO, so the sensible decision is HOLD or REJECT, never APPROVE.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    (OUT / "labels").mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(ROWS_URL.format(count=args.count), timeout=60) as response:
        rows = json.load(response)["rows"]
    for row in rows:
        name = f"cord_test_{row['row_idx']:03d}"
        with urllib.request.urlopen(row["row"]["image"]["src"], timeout=60) as response:
            data = response.read()
        if data[:3] != b"\xff\xd8\xff":
            raise SystemExit(f"{name}: not a JPEG, stopping")
        (OUT / f"{name}.jpg").write_bytes(data)
        label = label_for(row["row_idx"], json.loads(row["row"]["ground_truth"])["gt_parse"])
        (OUT / "labels" / f"{name}.json").write_text(json.dumps(label, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {name}.jpg  {len(data) // 1024} KB")
    print(f"{len(rows)} CORD receipts in {OUT}")


if __name__ == "__main__":
    main()
