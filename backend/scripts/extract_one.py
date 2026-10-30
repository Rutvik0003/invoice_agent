"""Extract one invoice with a chosen model and print every field with its confidence.

Usage: python backend/scripts/extract_one.py <file> --model gemini|groq [--no-cache]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eval_common import BACKEND_DIR  # noqa: F401  (sets up sys.path)

from app.config import get_settings
from app.db import get_engine
from app.extraction import extract_document
from app.extraction.pdf_utils import guess_mime
from app.models import Base
from app.schemas import ExtractedInvoice, ExtractionResult


def print_result(result: ExtractionResult) -> None:
    flags = [f for f, on in (("cached extraction", result.cached), ("repaired once", result.repaired)) if on]
    print(f"Model: {result.provider} / {result.model_name}   latency {result.latency_ms} ms   {'  '.join(flags)}")
    if result.error:
        print(f"\nEXTRACTION FAILED [{result.error.type}]: {result.error.message}")
        if result.error.detail:
            print(f"  detail: {result.error.detail}")
        return
    print_invoice(result.invoice)


def print_invoice(invoice: ExtractedInvoice) -> None:
    print(f"\n{'Field':16} {'Value':34} {'Conf':>5}  Evidence")
    print("-" * 100)
    for name in ExtractedInvoice.model_fields:
        if name == "line_items":
            continue
        field = getattr(invoice, name)
        value = "-" if field.value is None else str(field.value)
        flag = " !" if field.value is not None and field.confidence < get_settings().confidence_threshold else ""
        print(f"{name:16} {value[:34]:34} {field.confidence:5.2f}{flag:2} {(field.evidence or '')[:40]}")
    print(f"\nLine items ({len(invoice.line_items)}):")
    for i, line in enumerate(invoice.line_items, start=1):
        print(f"  {i}. {(line.description or '')[:40]:40} qty {line.quantity} x {line.unit_price} = {line.amount}"
              f"  GST {line.tax_rate}%  conf {line.confidence:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--model", choices=["gemini", "groq"], default=None)
    parser.add_argument("--no-cache", action="store_true", help="always call the model (default: reuse a cached result)")
    args = parser.parse_args()
    settings = get_settings()
    mime = guess_mime(args.file.name)
    if mime is None:
        sys.exit("Unsupported file type: use PDF, PNG or JPG.")
    engine = get_engine()
    Base.metadata.create_all(engine)
    result = extract_document(args.file.read_bytes(), mime, args.model or settings.default_model, settings, engine,
                              use_cache=not args.no_cache)
    print(f"File: {args.file}")
    print_result(result)


if __name__ == "__main__":
    main()
