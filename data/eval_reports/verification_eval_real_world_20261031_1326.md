# Verification evaluation (real_world, 20 files)

Generated 2026-10-31 13:26. No AI calls: ground-truth values are verified against the page.

| Metric | Result | Target |
|---|---:|---:|
| Recall, text layer | 0.0% (0/0) | 100% |
| Recall, OCR mild scans | 0.0% (0/0) | ≥ 95% |
| Recall, OCR heavy scans (info) | 0.0% (0/0) | - |
| Fault-injection catch rate | 100.0% (38/38) | ≥ 98% |
| Obscured fields reported not_found | 0.0% (0/0) | 100% |
| Box IoU (exact boxes): mean / median / share > 0.5 | 0.0 / 0.0 / 0.0% | - |

## Recall by field and source

| Field | Source | Found | Total | Recall |
|---|---|---:|---:|---:|
| subtotal | unknown | 9 | 14 | 64.29% |
| total_amount | unknown | 9 | 19 | 47.37% |

## Fault injection by field

| Field | Fault | Caught | Total | Rate |
|---|---|---:|---:|---:|
| total_amount | digit_changed | 19 | 19 | 100.0% |
| total_amount | plus_minus_100 | 19 | 19 | 100.0% |

## False verifications (wrong value accepted)

- none

## Missed true values

- cord_test_004 total_amount (unknown, real_scan): printed `174,600`
- cord_test_004 subtotal (unknown, real_scan): printed `194,000`
- cord_test_005 total_amount (unknown, real_scan): printed `31.000`
- cord_test_005 subtotal (unknown, real_scan): printed `28.182`
- cord_test_007 total_amount (unknown, real_scan): printed `111,000`
- cord_test_007 subtotal (unknown, real_scan): printed `100,909`
- cord_test_008 total_amount (unknown, real_scan): printed `50,000`
- cord_test_011 total_amount (unknown, real_scan): printed `230,000`
- cord_test_012 total_amount (unknown, real_scan): printed `120,000`
- cord_test_013 total_amount (unknown, real_scan): printed `51.300`
- cord_test_013 subtotal (unknown, real_scan): printed `46.636`
- cord_test_014 total_amount (unknown, real_scan): printed `281,435`
- cord_test_015 total_amount (unknown, real_scan): printed `63.000`
- cord_test_019 total_amount (unknown, real_scan): printed `176000`
- cord_test_019 subtotal (unknown, real_scan): printed `160000`
