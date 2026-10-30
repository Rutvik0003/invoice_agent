"""Extract one invoice, verify every key field on the page, print the result and draw it.

Usage: python backend/scripts/verify_one.py <file> --model gemini|groq [--no-cache]
Saves data/eval_reports/verify/<file>_verify.png: green box = found on the page, red = AI value not found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eval_common import REPORT_DIR

from PIL import Image, ImageDraw

from app.config import get_settings
from app.db import get_engine
from app.extraction import extract_document, file_hash
from app.extraction.pdf_utils import guess_mime, render_page_images
from app.models import Base
from app.schemas import VerificationResult
from app.verification.verify import VERIFIED_FIELDS, collect_page_words, field_trust, verify

GREEN, RED = (20, 160, 60), (220, 30, 30)
LABEL = {"verified": "✓ verified ({source})", "not_found": "✗ not found on page", "not_applicable": "- not printed",
         "unavailable": "— not verified (OCR unavailable)"}


def draw(file_bytes: bytes, mime: str, result: VerificationResult, out_path: Path) -> None:
    """Page images with green boxes on verified values (red frame = something was not found)."""
    pages = render_page_images(file_bytes, mime, dpi=110)
    missing = [n for n, f in result.fields.items() if f.status == "not_found"]
    for index, page in enumerate(pages, start=1):
        canvas = ImageDraw.Draw(page)
        for name, field in result.fields.items():
            if field.status == "verified" and field.page == index and field.bbox:
                x0, y0, x1, y1 = (field.bbox[0] * page.width, field.bbox[1] * page.height,
                                  field.bbox[2] * page.width, field.bbox[3] * page.height)
                canvas.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=GREEN, width=2)
                canvas.text((x0, max(0, y0 - 12)), name, fill=GREEN)
        if missing and index == 1:
            canvas.rectangle([2, 2, page.width - 3, page.height - 3], outline=RED, width=4)
            canvas.text((12, 8), "NOT FOUND ON PAGE: " + ", ".join(missing), fill=RED)
    sheet = Image.new("RGB", (max(p.width for p in pages), sum(p.height for p in pages)), "white")
    y = 0
    for page in pages:
        sheet.paste(page, (0, y))
        y += page.height
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


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
    data = args.file.read_bytes()
    engine = get_engine()
    Base.metadata.create_all(engine)
    extraction = extract_document(data, mime, args.model or settings.default_model, settings, engine,
                                  use_cache=not args.no_cache)
    print(f"File: {args.file}\nModel: {extraction.provider} / {extraction.model_name}"
          f"{'  (cached extraction)' if extraction.cached else ''}")
    if extraction.error:
        sys.exit(f"EXTRACTION FAILED [{extraction.error.type}]: {extraction.error.message}")
    invoice = extraction.invoice
    pages = collect_page_words(data, mime, settings, engine, file_hash(data))
    result = verify(invoice, pages, settings)
    print(f"Verification engine: {result.engine_used}   pages: "
          + ", ".join(f"p{p.page} {p.source} ({p.word_count} words"
                      + (f", OCR conf {p.mean_ocr_conf}" if p.mean_ocr_conf else "") + ")" for p in result.pages))
    print(f"\n{'Field':14} {'AI value':28} {'Conf':>5}  {'Verification':32} {'Matched text':24} Trust")
    print("-" * 120)
    for name in VERIFIED_FIELDS:
        value = getattr(invoice, name).value
        field = result.fields[name]
        status = LABEL[field.status].format(source="text layer" if field.source == "text_layer" else "OCR")
        trust = ", ".join(field_trust(name, invoice, result, settings.confidence_threshold))
        print(f"{name:14} {str(value if value is not None else '-')[:28]:28} {getattr(invoice, name).confidence:5.2f}  "
              f"{status:32} {(field.matched_text or '')[:24]:24} {trust}")
    out = REPORT_DIR / "verify" / f"{args.file.stem}_verify.png"
    draw(data, mime, result, out)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
