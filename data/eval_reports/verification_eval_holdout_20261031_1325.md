# Verification evaluation (holdout, 42 files)

Generated 2026-10-31 13:25. No AI calls: ground-truth values are verified against the page.

| Metric | Result | Target |
|---|---:|---:|
| Recall, text layer | 100.0% (103/103) | 100% |
| Recall, OCR mild scans | 93.64% (103/110) | ≥ 95% |
| Recall, OCR heavy scans (info) | 0.0% (0/0) | - |
| Fault-injection catch rate | 100.0% (210/210) | ≥ 98% |
| Obscured fields reported not_found | 0.0% (0/0) | 100% |
| Box IoU (exact boxes): mean / median / share > 0.5 | 0.86 / 0.972 / 93.69% | - |

## Recall by field and source

| Field | Source | Found | Total | Recall |
|---|---|---:|---:|---:|
| bank_account | ocr | 21 | 21 | 100.0% |
| bank_account | text_layer | 10 | 10 | 100.0% |
| bank_account | unknown | 11 | 11 | 100.0% |
| buyer_gstin | ocr | 21 | 21 | 100.0% |
| buyer_gstin | text_layer | 10 | 10 | 100.0% |
| buyer_gstin | unknown | 11 | 11 | 100.0% |
| cgst | ocr | 7 | 7 | 100.0% |
| cgst | text_layer | 4 | 4 | 100.0% |
| cgst | unknown | 6 | 6 | 100.0% |
| igst | ocr | 13 | 14 | 92.86% |
| igst | text_layer | 6 | 6 | 100.0% |
| igst | unknown | 5 | 5 | 100.0% |
| invoice_date | ocr | 19 | 21 | 90.48% |
| invoice_date | text_layer | 10 | 10 | 100.0% |
| invoice_date | unknown | 11 | 11 | 100.0% |
| invoice_number | ocr | 20 | 21 | 95.24% |
| invoice_number | text_layer | 10 | 10 | 100.0% |
| invoice_number | unknown | 11 | 11 | 100.0% |
| po_reference | ocr | 17 | 18 | 94.44% |
| po_reference | text_layer | 9 | 9 | 100.0% |
| po_reference | unknown | 10 | 10 | 100.0% |
| sgst | ocr | 7 | 7 | 100.0% |
| sgst | text_layer | 4 | 4 | 100.0% |
| sgst | unknown | 6 | 6 | 100.0% |
| subtotal | ocr | 20 | 21 | 95.24% |
| subtotal | text_layer | 10 | 10 | 100.0% |
| subtotal | unknown | 9 | 11 | 81.82% |
| total_amount | ocr | 21 | 21 | 100.0% |
| total_amount | text_layer | 10 | 10 | 100.0% |
| total_amount | unknown | 11 | 11 | 100.0% |
| vendor_gstin | ocr | 19 | 21 | 90.48% |
| vendor_gstin | text_layer | 10 | 10 | 100.0% |
| vendor_gstin | unknown | 10 | 11 | 90.91% |
| vendor_name | ocr | 21 | 21 | 100.0% |
| vendor_name | text_layer | 10 | 10 | 100.0% |
| vendor_name | unknown | 11 | 11 | 100.0% |

## Fault injection by field

| Field | Fault | Caught | Total | Rate |
|---|---|---:|---:|---:|
| invoice_number | digit_changed | 42 | 42 | 100.0% |
| invoice_number | digits_swapped | 42 | 42 | 100.0% |
| total_amount | digit_changed | 42 | 42 | 100.0% |
| total_amount | plus_minus_100 | 42 | 42 | 100.0% |
| vendor_gstin | other_valid_gstin | 42 | 42 | 100.0% |

## False verifications (wrong value accepted)

- none

## Missed true values

- H001 igst (ocr, mild): printed `₹23,886.00`
- H009 invoice_number (ocr, mild): printed `1109`
- H009 invoice_date (ocr, mild): printed `24-Oct-26`
- H010 subtotal (unknown, photo): printed `₹75,800.00`
- H021 po_reference (ocr, mild): printed `PO-2026-1420`
- H023 vendor_gstin (ocr, web): printed `06VYDCV0800N1ZH`
- H025 subtotal (ocr, mild): printed `1,96,400`
- H030 vendor_gstin (unknown, photo): printed `09DJPCN6919I1Z5`
- H030 subtotal (unknown, photo): printed `₹74,335.00`
- H037 vendor_gstin (ocr, mild): printed `19JXOCP0232P1ZD`
- H037 invoice_date (ocr, mild): printed `09-10-2026`
