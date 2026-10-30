# Extraction evaluation (golden, 12 files, groq)

Generated 2026-10-30 22:34. Model names: groq = qwen/qwen3.8-27b

- **groq**: field accuracy 85.4% (111/130), median latency 3.4 s over 10 live calls

## Accuracy by field

| Field | groq |
|---|---:|
| document_type | 100.0% |
| invoice_number | 100.0% |
| invoice_date | 100.0% |
| vendor_gstin | 50.0% |
| buyer_gstin | 60.0% |
| po_reference | 90.0% |
| total_amount | 90.0% |
| subtotal | 90.0% |
| cgst | 100.0% |
| sgst | 100.0% |
| igst | 100.0% |
| line_count | 70.0% |
| line_amounts | 60.0% |

## By degradation (all fields)

| Group | groq |
|---|---:|
| heavy | 53.8% |
| none | 88.9% |

## By template (all fields)

| Group | groq |
|---|---:|
| classic | 69.2% |
| compact | 96.2% |
| landscape | 100.0% |
| modern | 73.1% |
| services | 100.0% |
| small_vendor | 69.2% |
| tally | 88.5% |

## Worst files

| Model | Invoice | Template | Level | Correct | Wrong fields |
|---|---|---|---|---:|---|
| groq | 08_F_blurry_scan | modern | heavy | 7/13 | vendor_gstin buyer_gstin po_reference total_amount subtotal line_amounts |
| groq | 06_D_bank_change | small_vendor | none | 9/13 | vendor_gstin buyer_gstin line_count line_amounts |
| groq | 07_E_wrong_gst | classic | none | 9/13 | vendor_gstin buyer_gstin line_count line_amounts |
| groq | 12_J_unapproved_vendor | tally | none | 10/13 | vendor_gstin line_count line_amounts |
| groq | 02_happy_tolerance | modern | none | 12/13 | vendor_gstin |
| groq | 11_I_quotation | compact | none | 12/13 | buyer_gstin |
| groq | 03_A_split_overrun | tally | none | 13/13 |  |
| groq | 04_B_duplicate | compact | none | 13/13 |  |
| groq | 05_C_no_po | landscape | none | 13/13 |  |
| groq | 09_G_price_variance | services | none | 13/13 |  |

## Errors

- groq 01_happy_clean: rate_limited - Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `...` service tier `on_demand` on input tokens per minute (ITPM): Limit 7000, Used 5380, Requested 5105. Please try again in 29.8714285
- groq 10_H_bad_maths: provider_error - Error code: 413 - {'error': {'message': 'Request too large for model `qwen/qwen3.8-27b` in organization `...` service tier `on_demand` on input tokens per minute (ITPM): Limit 7000, Requested 8038, please reduce your message size and try ag
