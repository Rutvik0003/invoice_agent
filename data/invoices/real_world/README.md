# Real-world invoices

Real invoices show whether the agent works outside our generated data. Examples: your own purchase invoices (online shopping, a restaurant bill with GST, a utility bill) or sample GST invoices published by accounting software vendors. Nothing in this folder is needed to run the app; it is only used by the evaluation scripts.

## Included: 20 real receipt photos (CORD v2)

`backend/scripts/fetch_cord.py` downloads 20 receipt photos and writes their labels (`cord_test_*.jpg`). They are
git-ignored, so run the script once after cloning:

```bash
.venv/Scripts/python backend/scripts/fetch_cord.py
```

- **Source:** the test split of CORD v2, (c) NAVER Clova, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), from
  [huggingface.co/datasets/naver-clova-ix/cord-v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2).
- **What they are:** real phone photos of Indonesian shop and restaurant receipts. They are not GST invoices.
  - They test OCR and extraction on genuinely unseen, imperfect photos: faded thermal print, creases, small images.
  - Only the subtotal and total are labelled.
  - The sensible decision is HOLD or REJECT, never APPROVE: there is no GSTIN or PO, and they are not addressed to
    Zenith.
- **Amount format:** rupiah amounts group thousands with a dot ("60.000" = sixty thousand). An INR-only system reads
  that as 60.00, so those values are expected to show as "not found". The evaluation reports them separately.

## Adding an invoice

1. Put the file in this folder: PDF, PNG or JPG, at most 10 MB and 20 pages.
   - Use a short name without spaces, for example `amazon_2026_10.pdf`.
   - **Privacy:** these files are committed to git like everything else. Blur or crop anything you don't want to share, such as your home address or phone number, before adding a file. A file you don't want in git can be listed in `.gitignore`.
2. Write a label: `labels/<same name>.json`, for example `labels/amazon_2026_10.json`. Copy exactly what is printed:

```json
{
  "ground_truth": {
    "document_type": "tax_invoice",
    "vendor_name": "Clicktail Retail Private Limited",
    "vendor_gstin": "29AAJCC1234F1Z5",
    "buyer_name": "Rutvik Kachhadiya",
    "buyer_gstin": null,
    "invoice_number": "BLR7-1234567",
    "invoice_date": "2026-10-12",
    "po_reference": null,
    "subtotal": 2541.53,
    "cgst": null,
    "sgst": null,
    "igst": 457.47,
    "round_off": null,
    "total_amount": 2999.00,
    "bank_account": null,
    "line_items": [
      {"description": "Wireless mouse", "quantity": 1, "unit_price": 2541.53, "amount": 2541.53, "tax_rate": 18}
    ]
  },
  "expected_decision": "HOLD",
  "notes": "Online purchase: not addressed to Zenith, unknown vendor, no PO."
}
```

Rules for labels:

- **Copy what is printed, not what is right.** If the invoice has a typo or bad maths, the label keeps it.
- **Use `null` for anything not printed.** A field you leave out counts as `null`.
- **Dates** use `YYYY-MM-DD`. **Amounts** are plain numbers, with no ₹ and no commas.
- **`document_type`** is one of `tax_invoice`, `quotation`, `proforma`, `credit_note`, `delivery_challan`, `purchase_order`, `other`.
- `expected_decision` and `notes` are optional.
  - A real invoice from your own shopping is not addressed to Zenith Retail and its vendor is not in our master data. The sensible decision is **HOLD**, with `VENDOR_UNKNOWN`, `BUYER_MISMATCH` and `PO_NOT_FOUND`. It must never be a wrong Reject.
  - Ids, template, scan level and so on are filled in automatically. Scan level comes from the file itself: does every page have a text layer?

## Evaluating

Run from the repository root.

Extraction uses the AI and spends free-tier quota. Readings are cached, so a second run is free:

```bash
.venv/Scripts/python backend/scripts/eval_extraction.py --set real_world --model gemini
```

Verification uses no AI. It checks whether each labelled value can be found on the page:

```bash
.venv/Scripts/python backend/scripts/eval_verification.py --set real_world
```

Reports are written to `data/eval_reports/`.

The full pipeline can be run on one file. You can also upload it on the New Run screen and look at the boxes on the page:

```bash
.venv/Scripts/python backend/scripts/run_pipeline.py data/invoices/real_world/amazon_2026_10.pdf --model gemini
```

## What to expect

- **Digital PDFs** (most e-commerce invoices): values are verified against the text layer, so the boxes should sit exactly on the printed values.
- **Phone photos and scans:** Tesseract finds fewer values. Expect more `FIELD_NOT_VERIFIED` holds, each naming the field to confirm. A value OCR cannot find is never trusted silently.
- **Tax-inclusive prices** (common in retail):
  - When the line amounts add up to the subtotal plus GST, the arithmetic check passes, saying so.
  - Prices are compared with a PO without their GST.
- **Discount lines with negative amounts** are kept out of PO item matching.
- **Totals printed only in words:** a total like "Rupees Two Thousand Nine Hundred Ninety Nine Only" can be verified from the words.
- **Hindi or bilingual labels:** values printed with Devanagari digits or "रु." are understood.
  - OCR only has the English language pack. Hindi text is not read on scans, but numbers, GSTINs and dates are.
