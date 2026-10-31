# Rules evaluation (holdout, 42 invoices)

Generated 2026-10-31 11:24. Ground truth + rules_eval_signals, no AI, no OCR, each invoice judged independently against the seeded master data.

**Overall: 42/42 = 100.0%**

- holdout: 42/42 = 100.0%

## Confusion matrix (rows = expected, columns = actual)

| Expected \ Actual | APPROVE | HOLD | REJECT |
|---|---:|---:|---:|
| APPROVE | 14 | 0 | 0 |
| HOLD | 0 | 17 | 0 |
| REJECT | 0 | 0 | 11 |

## Pass rate by scenario

| Scenario | Passed | Total |
|---|---:|---:|
| ARITHMETIC_ERROR | 4 | 4 |
| BANK_CHANGE | 4 | 4 |
| BUYER_MISMATCH | 3 | 3 |
| CLEAN_EXACT | 10 | 10 |
| CLEAN_WITHIN_TOLERANCE | 4 | 4 |
| GST_WRONG_TYPE | 4 | 4 |
| NOT_AN_INVOICE | 3 | 3 |
| PRICE_OVER_TOLERANCE | 4 | 4 |
| QTY_EXCEEDS_PO | 3 | 3 |
| VENDOR_UNKNOWN | 3 | 3 |

## Failures (0)

- none

## Sample outputs

