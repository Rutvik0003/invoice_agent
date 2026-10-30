# Extraction evaluation (golden, 12 files, gemini)

Generated 2026-10-30 21:58. Model names: gemini = gemini-2.5-flash

- **gemini**: field accuracy 96.8% (151/156), median latency 21.0 s over 2 live calls

## Accuracy by field

| Field | gemini |
|---|---:|
| document_type | 100.0% |
| invoice_number | 100.0% |
| invoice_date | 91.7% |
| vendor_gstin | 91.7% |
| buyer_gstin | 91.7% |
| po_reference | 100.0% |
| total_amount | 91.7% |
| subtotal | 91.7% |
| cgst | 100.0% |
| sgst | 100.0% |
| igst | 100.0% |
| line_count | 100.0% |
| line_amounts | 100.0% |

## By degradation (all fields)

| Group | gemini |
|---|---:|
| heavy | 61.5% |
| none | 100.0% |

## By template (all fields)

| Group | gemini |
|---|---:|
| classic | 100.0% |
| compact | 100.0% |
| landscape | 100.0% |
| modern | 80.8% |
| multipage | 100.0% |
| services | 100.0% |
| small_vendor | 100.0% |
| tally | 100.0% |

## Worst files

| Model | Invoice | Template | Level | Correct | Wrong fields |
|---|---|---|---|---:|---|
| gemini | 08_F_blurry_scan | modern | heavy | 8/13 | invoice_date vendor_gstin buyer_gstin total_amount subtotal |
| gemini | 01_happy_clean | classic | none | 13/13 |  |
| gemini | 02_happy_tolerance | modern | none | 13/13 |  |
| gemini | 03_A_split_overrun | tally | none | 13/13 |  |
| gemini | 04_B_duplicate | compact | none | 13/13 |  |
| gemini | 05_C_no_po | landscape | none | 13/13 |  |
| gemini | 06_D_bank_change | small_vendor | none | 13/13 |  |
| gemini | 07_E_wrong_gst | classic | none | 13/13 |  |
| gemini | 09_G_price_variance | services | none | 13/13 |  |
| gemini | 10_H_bad_maths | multipage | none | 13/13 |  |
| gemini | 11_I_quotation | compact | none | 13/13 |  |
| gemini | 12_J_unapproved_vendor | tally | none | 13/13 |  |

## Errors

- none
