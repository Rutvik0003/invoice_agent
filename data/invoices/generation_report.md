# Invoice generation report

- Golden invoices: **12**, stress invoices: **271**
- Master data consistency after scenarios: **all checks passed**
- Self-verification (digital PDFs, value in text layer and inside its box, IoU > 0.5): **1930/1930 = 100.0%**

## Golden set

| Invoice | Scenario | Template | Scan | Expected | Must-include codes |
|---|---|---|---|---|---|
| 01_happy_clean | CLEAN_EXACT | classic | none | APPROVE | - |
| 02_happy_tolerance | CLEAN_WITHIN_TOLERANCE | modern | none | APPROVE | PRICE_VARIANCE_WITHIN_TOLERANCE |
| 03_A_split_overrun | PO_OVERRUN | tally | none | HOLD | PO_OVERRUN, QTY_EXCEEDS_PO |
| 04_B_duplicate | DUPLICATE_DISGUISED_NUMBER | compact | none | REJECT | DUPLICATE_INVOICE_NUMBER |
| 05_C_no_po | NO_PO_CLEAR_MATCH | landscape | none | HOLD | PO_INFERRED |
| 06_D_bank_change | BANK_CHANGE | small_vendor | none | HOLD | BANK_DETAILS_MISMATCH |
| 07_E_wrong_gst | GST_WRONG_TYPE | classic | none | REJECT | GST_TYPE_INVALID |
| 08_F_blurry_scan | HEAVY_SCAN_LOW_CONFIDENCE | modern | heavy | HOLD | FIELD_NOT_VERIFIED or LOW_CONFIDENCE_FIELD |
| 09_G_price_variance | PRICE_OVER_TOLERANCE | services | none | HOLD | PRICE_VARIANCE_OVER_TOLERANCE |
| 10_H_bad_maths | ARITHMETIC_ERROR | multipage | none | REJECT | ARITHMETIC_MISMATCH |
| 11_I_quotation | NOT_AN_INVOICE | compact | none | REJECT | NOT_A_TAX_INVOICE |
| 12_J_unapproved_vendor | VENDOR_NOT_APPROVED | tally | none | HOLD | VENDOR_NOT_APPROVED |

## Stress set

| Scenario | Count |
|---|---:|
| CLEAN_EXACT | 40 |
| CLEAN_WITHIN_TOLERANCE | 15 |
| MULTI_ISSUE | 15 |
| PO_OVERRUN | 15 |
| ARITHMETIC_ERROR | 12 |
| BANK_CHANGE | 12 |
| DUPLICATE_DISGUISED_NUMBER | 12 |
| GST_WRONG_TYPE | 12 |
| HEAVY_SCAN_LOW_CONFIDENCE | 12 |
| NOT_AN_INVOICE | 12 |
| NO_PO_CLEAR_MATCH | 12 |
| PRICE_OVER_TOLERANCE | 12 |
| DUPLICATE_EXACT_NUMBER | 8 |
| NO_PO_AMBIGUOUS | 8 |
| POSSIBLE_DUPLICATE | 8 |
| QTY_EXCEEDS_PO | 8 |
| VENDOR_UNKNOWN | 8 |
| BUYER_MISMATCH | 6 |
| GST_RATE_UNUSUAL | 6 |
| ITEM_NOT_ON_PO | 6 |
| MISSING_INVOICE_NUMBER | 6 |
| OBSCURED_INVOICE_NUMBER | 6 |
| PO_CLOSED | 6 |
| VENDOR_NOT_APPROVED | 6 |
| OBSCURED_GSTIN | 4 |
| VENDOR_BLOCKED | 4 |

| Expected decision | Count |
|---|---:|
| HOLD | 137 |
| REJECT | 71 |
| APPROVE | 63 |

| Template | Count |
|---|---:|
| landscape | 45 |
| small_vendor | 45 |
| compact | 42 |
| tally | 38 |
| classic | 34 |
| services | 31 |
| modern | 26 |
| multipage | 10 |

| Scan / format | Count |
|---|---:|
| digital (pdf) | 181 |
| mild (pdf) | 55 |
| mild (jpg) | 14 |
| heavy (pdf) | 12 |
| mild (png) | 9 |

| Pages | Count |
|---|---:|
| 1 | 261 |
| 2 | 5 |
| 3 | 5 |

## Overall expected decisions (golden + stress)

- APPROVE: 65 (23%)
- HOLD: 143 (51%)
- REJECT: 75 (27%)
