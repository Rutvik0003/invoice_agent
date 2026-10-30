# Verification evaluation (all, 283 files) - OCR_MIN_WORD_CONF=0 (experiment)

Generated 2026-10-30 23:15. No AI calls: ground-truth values are verified against the page.

| Metric | Result | Target |
|---|---:|---:|
| Recall, text layer | 100.0% (1930/1930) | 100% |
| Recall, OCR mild scans | 91.87% (723/787) | ≥ 95% |
| Recall, OCR heavy scans (info) | 2.44% (3/123) | - |
| Fault-injection catch rate | 99.93% (1370/1371) | ≥ 98% |
| Obscured fields reported not_found | 100.0% (23/23) | 100% |
| Box IoU (exact boxes): mean / median / share > 0.5 | 0.953 / 1.0 / 95.41% | - |

## Recall by field and source

| Field | Source | Found | Total | Recall |
|---|---|---:|---:|---:|
| bank_account | ocr | 74 | 91 | 81.32% |
| bank_account | text_layer | 192 | 192 | 100.0% |
| buyer_gstin | ocr | 67 | 91 | 73.63% |
| buyer_gstin | text_layer | 192 | 192 | 100.0% |
| cgst | ocr | 25 | 33 | 75.76% |
| cgst | text_layer | 43 | 43 | 100.0% |
| igst | ocr | 50 | 58 | 86.21% |
| igst | text_layer | 149 | 149 | 100.0% |
| invoice_date | ocr | 65 | 87 | 74.71% |
| invoice_date | text_layer | 192 | 192 | 100.0% |
| invoice_number | ocr | 61 | 79 | 77.22% |
| invoice_number | text_layer | 188 | 188 | 100.0% |
| po_reference | ocr | 69 | 83 | 83.13% |
| po_reference | text_layer | 163 | 163 | 100.0% |
| sgst | ocr | 25 | 33 | 75.76% |
| sgst | text_layer | 43 | 43 | 100.0% |
| subtotal | ocr | 73 | 91 | 80.22% |
| subtotal | text_layer | 192 | 192 | 100.0% |
| total_amount | ocr | 68 | 88 | 77.27% |
| total_amount | text_layer | 192 | 192 | 100.0% |
| vendor_gstin | ocr | 68 | 85 | 80.0% |
| vendor_gstin | text_layer | 192 | 192 | 100.0% |
| vendor_name | ocr | 81 | 91 | 89.01% |
| vendor_name | text_layer | 192 | 192 | 100.0% |

## Fault injection by field

| Field | Fault | Caught | Total | Rate |
|---|---|---:|---:|---:|
| invoice_number | digit_changed | 267 | 267 | 100.0% |
| invoice_number | digits_swapped | 267 | 267 | 100.0% |
| total_amount | digit_changed | 279 | 280 | 99.64% |
| total_amount | plus_minus_100 | 280 | 280 | 100.0% |
| vendor_gstin | other_valid_gstin | 277 | 277 | 100.0% |

## False verifications (wrong value accepted)

- S0168 total_amount digit_changed: wrong value `2964.0` matched `22,964.00` (ocr)

## Missed true values

- 08_F_blurry_scan vendor_gstin (ocr, heavy): printed `27EJOFR5535F1ZA`
- 08_F_blurry_scan vendor_name (ocr, heavy): printed `Ramesh Packaging`
- 08_F_blurry_scan invoice_number (ocr, heavy): printed `2026-27/767`
- 08_F_blurry_scan invoice_date (ocr, heavy): printed `25/10/2026`
- 08_F_blurry_scan po_reference (ocr, heavy): printed `PO-2026-1063`
- 08_F_blurry_scan subtotal (ocr, heavy): printed `13,635`
- 08_F_blurry_scan cgst (ocr, heavy): printed `1,227.15`
- 08_F_blurry_scan sgst (ocr, heavy): printed `1,227.15`
- 08_F_blurry_scan bank_account (ocr, heavy): printed `54611242954`
- 08_F_blurry_scan buyer_gstin (ocr, heavy): printed `27RHRCZ5469N1Z7`
- S0006 vendor_gstin (ocr, heavy): printed `07ZHNCP5749Q1ZA`
- S0006 vendor_name (ocr, heavy): printed `Patil Textiles Private Limited`
- S0006 invoice_date (ocr, heavy): printed `October 6, 2026`
- S0006 total_amount (ocr, heavy): printed `₹96,319.86`
- S0006 po_reference (ocr, heavy): printed `PO-2026-1281`
- S0006 subtotal (ocr, heavy): printed `₹81,627.00`
- S0006 igst (ocr, heavy): printed `₹14,692.86`
- S0006 bank_account (ocr, heavy): printed `83323960986`
- S0006 buyer_gstin (ocr, heavy): printed `27RHRCZ5469N1Z7`
- S0010 invoice_number (ocr, mild): printed `vcw0914`
- S0028 total_amount (ocr, mild): printed `₹86,966.00`
- S0028 po_reference (ocr, mild): printed `PO-2026-1188`
- S0028 subtotal (ocr, mild): printed `₹71,900.00`
- S0028 bank_account (ocr, mild): printed `864701210278`
- S0028 buyer_gstin (ocr, mild): printed `27RHRCZ5469N1Z7`
- S0043 invoice_date (ocr, mild): printed `29/10/2026`
- S0043 total_amount (ocr, mild): printed `7,699`
- S0043 subtotal (ocr, mild): printed `7,265.35`
- S0043 buyer_gstin (ocr, mild): printed `27RHRCZ5469N1Z7`
- S0044 vendor_gstin (ocr, mild): printed `06SKFPB6835W1ZY`
- S0049 vendor_name (ocr, heavy): printed `Orbit Electric Works Pvt. Ltd.`
- S0049 invoice_number (ocr, heavy): printed `OEW0429`
- S0049 invoice_date (ocr, heavy): printed `13-Oct-26`
- S0049 total_amount (ocr, heavy): printed `Rs. 4,248/-`
- S0049 po_reference (ocr, heavy): printed `PO-2026-1288`
- S0049 subtotal (ocr, heavy): printed `Rs. 3,600/-`
- S0049 igst (ocr, heavy): printed `Rs. 648/-`
- S0049 bank_account (ocr, heavy): printed `738834837327`
- S0049 buyer_gstin (ocr, heavy): printed `27RHRCZ5469N1Z7`
- S0058 vendor_gstin (ocr, heavy): printed `23EUACV4693J1ZU`
- S0058 vendor_name (ocr, heavy): printed `Vig Paper Products Pvt. Ltd.`
- S0058 invoice_date (ocr, heavy): printed `19/10/2026`
- S0058 total_amount (ocr, heavy): printed `Rs. 1,17,041/-`
- S0058 po_reference (ocr, heavy): printed `PO-2026-1278`
- S0058 subtotal (ocr, heavy): printed `Rs. 1,11,468/-`
- S0058 igst (ocr, heavy): printed `Rs. 5,573.40`
- S0058 bank_account (ocr, heavy): printed `670314483232611348`
- S0058 buyer_gstin (ocr, heavy): printed `27RHRCZ5469N1Z7`
- S0066 total_amount (ocr, mild): printed `₹1,11,829.00`
- S0081 vendor_gstin (ocr, mild): printed `03RWRPS3905Y2ZU`
- S0086 invoice_date (ocr, mild): printed `6 Oct 2026`
- S0086 total_amount (ocr, mild): printed `₹6,91,725.00`
- S0086 buyer_gstin (ocr, mild): printed `27RHRCZ5469N1Z7`
- S0094 vendor_gstin (ocr, heavy): printed `27IKYCN9490Z1ZL`
- S0094 invoice_number (ocr, heavy): printed `NS/882/26`
- S0094 invoice_date (ocr, heavy): printed `29-Oct-26`
- S0094 po_reference (ocr, heavy): printed `PO-2026-1279`
- S0094 subtotal (ocr, heavy): printed `INR 96450.00`
- S0094 cgst (ocr, heavy): printed `INR 8680.50`
- S0094 sgst (ocr, heavy): printed `INR 8680.50`
- S0094 bank_account (ocr, heavy): printed `928712592876178`
- S0094 buyer_gstin (ocr, heavy): printed `27RHRCZ5469N1Z7`
- S0103 invoice_date (ocr, mild): printed `21/10/2026`
- S0106 invoice_number (ocr, mild): printed `2026/PS/481`
- S0118 vendor_gstin (ocr, heavy): printed `27CNUCN5911H2Z7`
- S0118 invoice_number (ocr, heavy): printed `NI/898/26`
- S0118 total_amount (ocr, heavy): printed `INR 105.00`
- S0118 po_reference (ocr, heavy): printed `PO-2026-1287`
- S0118 subtotal (ocr, heavy): printed `INR 88.80`
- S0118 cgst (ocr, heavy): printed `INR 7.99`
- S0118 sgst (ocr, heavy): printed `INR 7.99`
- S0118 bank_account (ocr, heavy): printed `691684955076`
- S0118 buyer_gstin (ocr, heavy): printed `27RHRCZ5469N1Z7`
- S0124 vendor_gstin (ocr, mild): printed `27CMNCV0456S2ZN`
- S0124 invoice_date (ocr, mild): printed `2026-10-26`
- S0126 vendor_gstin (ocr, heavy): printed `09DJPCN6919I1Z5`
- S0126 vendor_name (ocr, heavy): printed `Nirmaan Office Mart Pvt. Ltd.`
- S0126 invoice_number (ocr, heavy): printed `2026/NOM/1514`
- S0126 invoice_date (ocr, heavy): printed `26-Oct-26`
- S0126 po_reference (ocr, heavy): printed `PO-2026-1282`
