# PHASE_PROMPTS.md — Copy-paste prompts for Claude Code

> **Version 2:** adds Stage 3 "Verify on page" (OCR / PDF text layer checks the AI's values), Docker deployment (Phase 0.5), verification evaluation, and highlight boxes in the UI. Pipeline is now 8 stages.

**How to use this file**
1. Keep `CLAUDE.md` and this file in the root of `invoice-agent/`, open Claude Code there.
2. Paste **one phase prompt at a time**. Wait for the Phase Report.
3. Do the **"You test"** checklist yourself. Only move on when every box is ticked.
4. If something fails, paste the error and say: *"Fix this within Phase N only. Do not start the next phase."*
5. Start each new Claude Code session with: *"Read CLAUDE.md and PHASE_PROMPTS.md. We are on Phase N."*

| Phase | What | Day |
|---|---|---|
| 0 | Skeleton + hello-world deploy | 1 ✅ done |
| 0.5 | Switch deployment to Docker + Tesseract | 1 |
| 1 | Master data (vendors, POs, history) | 2 |
| 2 | Invoice generator: 12 golden + ~250 stress invoices with labels | 2 |
| 3 | AI extraction (Gemini + Groq) + page verification (text layer / OCR) + evaluations | 3 |
| 4 | Rules engine (stages 4–8) + rules evaluation on all invoices | 3–4 |
| 5 | Pipeline orchestration, run storage, API, live event stream | 4 |
| 6 | Frontend: New Run + Live Run View (with highlight boxes) | 5 |
| 7 | Frontend: Dashboard, Run Detail, Hold Queue, Test Suite, Data, Settings | 5 |
| 8 | Hardening + real-world robustness | 6 |
| 10 | Demo mode vs real mode: start screen, demo inbox, per-visitor sandbox, demo Gemini key | 7 |
| 11 | Real mode: Gmail sign-in (read-only), inbox, owner-only access | 7–8 |
| 9 | Production DB, smoke test, README, demo script (done last, after 10 and 11) | 8 |

---

## PHASE 0 — Skeleton and hello-world deploy ✅ DONE

(Already completed under v1: FastAPI `/api/health`, React page, `.env.example`, Makefile, render.yaml with native Python runtime, first live link.)

---

## PHASE 0.5 — Switch deployment to Docker + Tesseract

**Before pasting, you do:** replace `CLAUDE.md` and `PHASE_PROMPTS.md` in the repo with these v2 files. Install Tesseract on your laptop (Windows: UB-Mannheim installer, tick "Add to PATH"; macOS: `brew install tesseract`; Linux: `sudo apt install tesseract-ocr`). Install Docker Desktop if you want to test the container locally (optional but recommended).

```
CLAUDE.md and PHASE_PROMPTS.md have been updated to version 2 (see the changelog at the top of CLAUDE.md). Read both fully. Phase 0 is done under v1. We are doing PHASE 0.5 only: move deployment to Docker so Tesseract OCR is available in production. No business logic.

Tasks:
1. Dockerfile (multi-stage):
   - Stage 1: node (LTS) image → install frontend deps → build frontend/dist.
   - Stage 2: python:3.11-slim → apt-get install tesseract-ocr tesseract-ocr-eng (no recommends; clean apt lists) → install backend requirements → copy backend + built dist → run uvicorn on $PORT (default 8000) as a non-root user.
   - Keep the image small; add .dockerignore (node_modules, .env, local.db, data/eval_reports, __pycache__, .git).
2. Update render.yaml to use the Docker runtime (runtime: docker / env: docker, dockerfilePath, healthCheckPath /api/health), keeping env var declarations without values.
3. Extend GET /api/health with "ocr": {"available": bool, "version": str|null} using pytesseract.get_tesseract_version() inside try/except (never crash). Respect TESSERACT_CMD if set.
4. Add pytesseract to requirements; add VERIFY_ENABLED, OCR_DPI, OCR_MIN_WORD_CONF, VERIFY_FUZZY_MIN, TESSERACT_CMD to config.py and .env.example (CLAUDE.md §5).
5. Frontend health page also shows OCR status.
6. Makefile: `make docker-build`, `make docker-run` (reads .env).
7. README: local Tesseract install per OS, Docker commands, Render Docker deploy steps.
8. Tests: health endpoint returns ocr key whether or not Tesseract is installed (mock both cases).

Phase Report, commit "Phase 0.5: docker + tesseract".
```

**You test**
- [ ] `make dev` → health page shows both models ✓ and OCR ✓ (version number shown).
- [ ] (If Docker installed) `make docker-build && make docker-run` → open http://localhost:8000 → same page, OCR ✓.
- [ ] Push to GitHub. In Render, change the service to Docker (or create a new one from render.yaml — copy env vars across) → live link shows OCR ✓.
- [ ] Render dashboard → service "Metrics": memory well under the free limit.

---

## PHASE 1 — Master data

```
Read CLAUDE.md. We are doing PHASE 1 only: realistic master data + database.

Build in datagen/ (seeded random, reproducible; Faker en_IN; all names fictional):

1. gstin.py
   - make_pan(entity_type) → 5 letters + 4 digits + 1 letter; 4th char = entity type (C company, F firm, P proprietor).
   - make_gstin(state_code, pan, entity_no) → state code (2) + PAN (10) + entity number (1) + 'Z' + checksum char.
   - Checksum: standard GSTIN mod-36 algorithm (alphabet 0-9A-Z; for the first 14 chars multiply value by alternating factors 1,2 starting with 1; add (product // 36) + (product % 36); check = (36 - sum % 36) % 36). Implement validate_gstin() too.
   - Unit tests: round-trip generate→validate for 1,000 GSTINs; tampered GSTINs fail; verify against at least one publicly documented valid GSTIN example you can confirm.
   - IFSC generator (4 letters + '0' + 6 alphanumerics), bank account numbers (9–18 digits).
2. catalog.py — item catalogs per vendor category with HSN/SAC codes, units, realistic INR price ranges and GST rates valid under GST 2.0 (0/5/18/40 — mostly 18 and 5). Categories: IT hardware, IT services (SAC 99xx), office supplies, packaging, logistics/freight (services), facility management (services), raw materials, marketing/printing, furniture, electrical & maintenance. 10–25 items per category.
3. master_data.py generates into data/master/:
   - buyer.json — Zenith Retail Pvt Ltd, Maharashtra (27), valid GSTIN, address.
   - vendors.csv — 40 vendors across ≥ 12 states (≈ 30% Maharashtra so both CGST+SGST and IGST cases are common). Columns: vendor_id, legal_name, trade_name, gstin, pan, state, state_code, address, email, phone, bank_name, bank_account, ifsc, status (approved 34 / pending 3 / blocked 3), category, payment_terms_days. Store legal_name and trade_name (e.g. "Pvt Ltd" vs "Private Limited" variants).
   - po_headers.csv + po_lines.csv — ~200 POs over the last 9 months, 1–8 lines each, items from the vendor's category, statuses open / partially_billed / closed. PO numbers in format PO-2026-NNNN.
   - invoice_history.csv — ~400 past invoices (approved/paid) against those POs, with realistic invoice-number styles per vendor (e.g. "SIT/26-27/0881", "INV-00457", "2026/KOS/57", "BW1234"), dates after PO dates, partial billing on some POs, and PO statuses consistent with history (closed = fully billed).
   - Expose functions so Phase 2 scenarios can reserve specific POs/vendors and append history rows. Final CSVs are written by a single entry point (datagen/generate_all.py) so master data and scenarios stay consistent.
4. backend: SQLAlchemy models for all tables in CLAUDE.md §7; scripts/seed_db.py loads data/master/* into the DB (idempotent: drops & recreates seeded tables). SQLite locally.
5. datagen/validate_master.py: every GSTIN valid; vendor state matches GSTIN state code; every PO line belongs to an existing PO and vendor; billed totals per PO ≤ PO value; closed POs are fully billed; no duplicate invoice numbers per vendor in history; all GST rates valid for their dates. Prints a summary table.

Tests for all of the above. Phase Report, commit "Phase 1: master data".
```

**You test**
- [ ] `python -m datagen.generate_all --master-only` then `python -m datagen.validate_master` → all checks green, ~40 vendors / ~200 POs / ~400 history rows.
- [ ] Open `vendors.csv` and `po_lines.csv` in Excel/Sheets — names, items and prices look believable?
- [ ] Check 2 GSTINs on any free online GSTIN *format/checksum* validator (they're fictional, so they won't exist on the government portal).
- [ ] `python backend/scripts/seed_db.py` runs twice without errors.

---

## PHASE 2 — Invoice generator (golden + stress sets with labels)

```
Read CLAUDE.md. We are doing PHASE 2 only: generate realistic invoice files with ground-truth labels.
Rule 6: expected outcomes come from scenario definitions, never from the decision engine or verifier.

A. Layout templates (datagen/templates/, ReportLab). At least 8 visually distinct layouts:
   1. Classic GST tax invoice (bordered table, HSN column, CGST/SGST columns per line)
   2. Modern minimal (no borders, big total, sans font)
   3. Services invoice (SAC codes, hours × rate)
   4. Compact two-column header with rate-wise tax summary table at bottom
   5. Multi-page invoice (2–3 pages, "continued on next page", totals only on last page)
   6. Landscape wide table with discount and freight columns
   7. "Tally-style" invoice (dense, small font, amount in words, declaration, signature block)
   8. Small-vendor invoice (simple, handwritten-style font for some values, stamp image)
   Every template: fictional logo drawn from shapes, vendor block, buyer block (Zenith), invoice meta, line table, totals, bank details, terms, authorised signatory.
   **The renderer must record the bounding box of every printed key value** (invoice number, date, vendor GSTIN, buyer GSTIN, PO ref, subtotal, each tax amount, total, bank account) into the label as field_boxes (page + normalised bbox).

B. Variation knobs (randomised per invoice, recorded in labels):
   - Title: "Tax Invoice", "TAX INVOICE", "GST Invoice", "Invoice", "Bill of Supply" (only for 0% items)
   - Label synonyms: Invoice No / Inv. No. / Bill No / Invoice #; PO No / P.O. Ref / Your Order No / Against PO / PO mentioned only in Notes; Date / Inv Date / Dated
   - Date formats: 05/03/2026, 05-03-2026, 5 Mar 2026, 05-Mar-26, March 5, 2026, 2026-03-05
   - Amount formats: ₹1,23,456.00 / Rs. 1,23,456/- / INR 123456.00 / 1,23,456 (no symbol)
   - Tax per line vs only in summary; CGST+SGST vs IGST per state rule; optional round-off, discount, freight/packing; amount in words
   - Vendor name as legal name OR trade name OR abbreviated ("Sharma IT Solns Pvt. Ltd."); GSTIN sometimes printed with spaces
   - Page count 1–3

C. Scan degradation (datagen/degrade.py) applied to rendered page images, saved back as image-only PDFs (some as PNG/JPG):
   - mild: 150–200 DPI, rotation ±1.5°, light noise, slight blur, JPEG quality 60–80 (should still be read and verified)
   - heavy: 100 DPI, rotation ±4°, strong blur/noise, shadow gradient, coffee-stain blotch
   - targeted obscuring: smudge / ink blot / stamp placed exactly over a chosen field_box (e.g. the total or invoice number) → record in obscured_fields
   - extras: rubber-stamp overlay, signature scribble, punch holes, fax-style black & white
   - Transform field_boxes with the same rotation/scale; mark approximate if not exact.

D. Scenarios (datagen/scenarios.py). Each scenario reserves the vendors/POs/history it needs, applies a mutation, and declares expected_decision, acceptable_decisions, expected_reason_codes (must-include) and rules_eval_signals (CLAUDE.md §7).

   GOLDEN SET (data/invoices/golden/, exactly these 12, clean digital unless stated):
   01_happy_clean — approved Maharashtra vendor, exact PO match → APPROVE
   02_happy_tolerance — different layout, ₹200 rounding difference within tolerance → APPROVE (PRICE_VARIANCE_WITHIN_TOLERANCE)
   03_A_split_overrun — 3rd partial invoice on a PO already billed ~88% → HOLD (PO_OVERRUN)
   04_B_duplicate — same invoice as a paid history row, number styled differently (KOS-0457 vs KOS/457) → REJECT (DUPLICATE_INVOICE_NUMBER)
   05_C_no_po — no PO reference; two open POs for this vendor, one clearly matches → HOLD (PO_INFERRED)
   06_D_bank_change — bank account/IFSC differ from vendor master → HOLD (BANK_DETAILS_MISMATCH)
   07_E_wrong_gst — inter-state vendor charges CGST+SGST → REJECT (GST_TYPE_INVALID)
   08_F_blurry_scan — heavy scan, total smudged (obscured_fields=[total_amount]) → HOLD; expected_reason_codes include one of LOW_CONFIDENCE_FIELD / FIELD_NOT_VERIFIED; acceptable_decisions = [HOLD]
   09_G_price_variance — unit price +3% vs PO → HOLD (PRICE_VARIANCE_OVER_TOLERANCE)
   10_H_bad_maths — line amounts don't sum to printed total → REJECT (ARITHMETIC_MISMATCH)
   11_I_quotation — document titled "Quotation" → REJECT (NOT_A_TAX_INVOICE)
   12_J_unapproved_vendor — vendor with status pending → HOLD (VENDOR_NOT_APPROVED)

   STRESS SET (data/invoices/stress/, ~260 files, randomised across all templates; ~30% mild scans; ids like S0001):
   CLEAN_EXACT 40 · CLEAN_WITHIN_TOLERANCE 15 · PO_OVERRUN 15 ·
   DUPLICATE_EXACT_NUMBER 8 · DUPLICATE_DISGUISED_NUMBER 12 · POSSIBLE_DUPLICATE (same vendor+amount, date ±2 days, different number) 8 ·
   NO_PO_CLEAR_MATCH 12 · NO_PO_AMBIGUOUS 8 · BANK_CHANGE 12 · GST_WRONG_TYPE 12 (both directions) ·
   HEAVY_SCAN_LOW_CONFIDENCE 12 (heavy degradation + one critical field obscured) · OBSCURED_INVOICE_NUMBER 6 · OBSCURED_GSTIN 4 ·
   PRICE_OVER_TOLERANCE 12 · QTY_EXCEEDS_PO 8 · ITEM_NOT_ON_PO 6 · ARITHMETIC_ERROR 12 ·
   NOT_AN_INVOICE 12 (quotation, proforma, credit note, delivery challan, purchase order copy) ·
   VENDOR_NOT_APPROVED 6 · VENDOR_BLOCKED 4 · VENDOR_UNKNOWN 8 · BUYER_MISMATCH 6 · PO_CLOSED 6 · GST_RATE_UNUSUAL 6 (e.g. 12% dated after 22 Sep 2025) ·
   MISSING_INVOICE_NUMBER 6 · MULTI_ISSUE 15 (2–3 problems at once; expected decision follows severity precedence; ALL codes must be listed).

E. Labels: one JSON per file in labels/ exactly as CLAUDE.md §7 (incl. field_boxes, obscured_fields, rules_eval_signals). ground_truth = what is PRINTED (e.g. "KOS/457", not normalised). For obscured fields, ground_truth still holds the true printed value and rules_eval_signals marks it {confidence ~0.4, not_found}.
F. History & master consistency: scenarios append the history rows they need (originals for duplicates, prior partial bills for overruns); generate_all.py writes final CSVs + files in one run; re-run validate_master.py at the end.
G. Contact sheets: data/invoices/contact_sheet_golden.png and contact_sheet_stress_<n>.png (grids of first-page thumbnails with ids). Also data/invoices/box_check_<id>.png for 5 random files: the page image with field_boxes drawn on it, so I can see the boxes land on the right values.
H. Self-verification (no AI, no OCR): for every DIGITAL file, read PyMuPDF words and assert each printed key value in ground_truth appears in the text AND inside its recorded field_box (IoU > 0.5). Report pass rate (must be 100%).
I. Summary report → data/invoices/generation_report.md: counts by scenario, template, scanned/digital, expected decision.

Tests for knobs, degrader, label schema validity. Phase Report, commit "Phase 2: invoice generator".
```

**You test**
- [ ] `python -m datagen.generate_all` finishes; `generation_report.md` shows 12 golden + ~260 stress, roughly 35–40% Approve, a mix of Hold/Reject.
- [ ] `contact_sheet_golden.png` → 12 different-looking invoices?
- [ ] Open the `box_check_*.png` images → boxes sit exactly on the invoice number, total, GSTIN, etc.
- [ ] Open 5 random stress PDFs — believable? Check one multi-page and one heavy scan with a smudged total.
- [ ] `04_B_duplicate` → find the original row in `invoice_history.csv`.
- [ ] `03_A_split_overrun` → its PO plus the 2 earlier invoices really exceed the PO value.
- [ ] Self-verification pass rate = 100%.

---

## PHASE 3 — AI extraction + page verification + evaluations

```
Read CLAUDE.md. We are doing PHASE 3 only: Stage 2 (extraction with two providers) and Stage 3 (verify on page), plus evaluation harnesses.

PART A — Extraction (Stage 2)
1. extraction/base.py — Extractor interface: extract(file_bytes, mime, page_images) -> ExtractionResult {invoice: ExtractedInvoice | None, error: ExtractionError | None, model_name, latency_ms, raw_response}. ExtractionError type ∈ rate_limited | timeout | invalid_response | provider_error | auth_error | unsupported_file, with a user-friendly message.
2. extraction/prompt.py — one shared extraction prompt + JSON schema for both providers. The prompt must: extract only what is printed; return null for anything absent; never compute or infer missing values; classify document_type; give per-field confidence (0–1) and a short evidence snippet; keep printed strings AND parsed numbers; handle Indian formats and multi-page invoices (totals usually on the last page). Temperature 0.
3. extraction/gemini.py — google-genai SDK; PDF bytes directly (or the image for PNG/JPG); structured JSON output with the schema; model from GEMINI_MODEL.
4. extraction/groq.py — groq SDK; render pages to PNG (PyMuPDF, max 5 pages, ~150 DPI, size-limited), send as images; JSON mode; model from GROQ_MODEL (must be vision-capable — check Groq's current model list; tell me which you chose and why).
5. Pydantic validation; ONE repair retry on invalid JSON; then invalid_response. Map provider errors (429 → rate_limited, etc.). Timeout 60 s.
6. extraction/cache.py — DB cache keyed by (file_hash, model); only when use_cache=True.
7. scripts/extract_one.py <file> --model gemini|groq [--no-cache].

PART B — Verification (Stage 3), exactly per CLAUDE.md §6 Stage 3
8. verification/page_text.py — words + boxes from text-layer pages (PyMuPDF get_text("words")), normalised coordinates.
9. verification/ocr.py — words + boxes + confidence via pytesseract.image_to_data on page images rendered at OCR_DPI (light preprocessing: grayscale, auto-contrast, deskew if cheap); drop words below OCR_MIN_WORD_CONF; cache by file_hash+page; any Tesseract error → status unavailable (rule 14).
10. verification/matchers.py — type-aware matchers (amount, identifier with OCR-confusion map, GSTIN/account, date, name) that search single words and adjacent-word runs (≤ 6 words, same line). Pure functions, heavily unit-tested with tricky inputs ("1,18,000.00", "Rs.118000/-", "INV / 0881", "27AAB CD1234 F1Z5", "05-Mar-26").
11. verification/verify.py — verify(extracted, page_words) → VerificationResult (CLAUDE.md §7) + the effective trust rule helper is_trusted(field) / doubtful_fields().
12. scripts/verify_one.py <file> --model … → prints each field: AI value, model confidence, verification status, source, matched text; and saves <file>_verify.png with green/red boxes drawn on the page image.

PART C — Evaluations
13. scripts/eval_extraction.py — compares extraction vs labels: --set golden|stress|real_world, --model gemini|groq|both, --sample N (stratified by template, scanned/digital, scenario), --delay seconds (default 13 s for free tier), resumable via cache. Field scores after normalisation (invoice_number, invoice_date, vendor_gstin, buyer_gstin, po_reference, total ± ₹1, subtotal, taxes, line count, line amounts, document_type). Report by template, digital vs mild vs heavy scan, per model, worst files. Save markdown + CSV in data/eval_reports/.
14. scripts/eval_verification.py — NO AI calls, runs on ALL generated invoices using ground_truth values:
    a) Recall: for each true printed value (not obscured), does the verifier find it? Report by source (text layer vs OCR) and degradation level.
    b) Box accuracy: IoU of found bbox vs label field_boxes (exact boxes only).
    c) Fault injection (catch rate): for each file, create wrong values the AI might hallucinate — change one digit of the total, swap two digits of the invoice number, total ±₹100, a different valid GSTIN — and check the verifier returns not_found. Report catch rate per field and false-verification cases.
    d) Obscured fields: verifier should return not_found for fields in obscured_fields.
    Targets: text-layer recall 100%, mild-scan recall ≥ 95%, fault-injection catch rate ≥ 98%. If OCR recall on mild scans is below target, tune preprocessing/DPI before lowering anything, and report what you tried.
15. Unit tests use recorded fake provider responses and fixture word lists (no network).

Phase Report (include: chosen model names, golden extraction accuracy for both models, verification recall / box IoU / catch-rate table), commit "Phase 3: extraction + verification".
```

**You test**
- [ ] `python backend/scripts/extract_one.py data/invoices/golden/01_happy_clean.pdf --model gemini` → fields correct. Same with `--model groq`.
- [ ] `python backend/scripts/verify_one.py data/invoices/golden/01_happy_clean.pdf --model gemini` → all key fields "verified (text layer)"; open the `_verify.png` → green boxes on the right values.
- [ ] Same on a **mild scan** from the stress set → "verified (OCR)".
- [ ] Same on `08_F_blurry_scan` → the total is "not found" or low-confidence (red box / no box), not a confident wrong number.
- [ ] `python backend/scripts/eval_verification.py --set all` → check recall, IoU and fault-injection catch rate meet the targets.
- [ ] Wrong GEMINI_API_KEY in `.env` → clean `auth_error`, no crash. Restore it.
- [ ] Optional (spread over days for free limits): `eval_extraction.py --set stress --sample 40 --model gemini`.

---

## PHASE 4 — Rules engine (stages 4–8) + rules evaluation

```
Read CLAUDE.md. We are doing PHASE 4 only: deterministic stages 4–8 as pure functions.

1. pipeline/reason_codes.py — ReasonCode enum exactly as CLAUDE.md §6, each with severity, routed role and message template with placeholders (e.g. "Unit price ₹{billed} is {pct}% above PO price ₹{po} (tolerance {tol}%)").
2. pipeline/normalise.py — dates, amounts, invoice numbers, GSTIN, names; thorough unit tests with messy inputs (all Phase 2 formats + extra real-world ones).
3. pipeline/self_check.py, vendor_check.py, duplicate_check.py, po_match.py, amount_match.py — exactly per CLAUDE.md §6 stages 4–7. Use the Stage 3 trust rule: doubtful critical fields → FIELD_NOT_VERIFIED or LOW_CONFIDENCE_FIELD; ARITHMETIC_MISMATCH only when all involved fields are trusted, else ARITHMETIC_UNCERTAIN; OCR unavailable → OCR_UNAVAILABLE info + fallback to model confidence. Each check returns CheckResult {code|None, passed, severity, message, evidence {invoice_field, invoice_value, verification_status, reference_source, reference_value}}. One-line business-rule docstring per check.
4. pipeline/decision.py — severity precedence, approve-with-note, routed question text for Hold, draft vendor note for Reject (polite, specific, lists exactly what to fix), ledger update instructions for Approve. Pure function: inputs → Decision; no DB writes.
5. Data access through a small repository interface so the engine runs on (a) the DB or (b) in-memory master data for tests/eval.
6. scripts/eval_rules.py — runs stages 4–8 on label ground_truth + rules_eval_signals (no AI, no OCR → covers ALL ~272 invoices instantly). Compare decision vs expected_decision/acceptable_decisions and check all expected_reason_codes are present. Each invoice evaluated independently against the seeded state. Output: overall accuracy, confusion matrix, per-scenario pass rate, failures with diffs → data/eval_reports/rules_eval_<timestamp>.md.
   Target: golden 12/12, stress ≥ 98%. For any failure, say whether the LOGIC or the SCENARIO is wrong — never silently change labels.
7. Unit tests for every check incl. boundaries (exactly at tolerance, ₹1 rounding, 0% GST, inter/intra-state, PO fully billed, inferred-PO gap just below 0.15, verified-but-low-confidence field = trusted, not_found field = FIELD_NOT_VERIFIED, OCR unavailable fallback).

Phase Report (paste the confusion matrix), commit "Phase 4: rules engine".
```

**You test**
- [ ] `python backend/scripts/eval_rules.py --set golden` → 12/12.
- [ ] `--set stress` → ≥ 98%, and you read the explanation for every failure.
- [ ] In the report: each Hold has a sensible routed question; each Reject has a vendor note you'd send.
- [ ] Case 03 (overrun): do the arithmetic by hand from the CSVs — matches the message?
- [ ] Case 08: reason says the total couldn't be verified/was low confidence → Hold.

---

## PHASE 5 — Orchestration, storage, API, live events

```
Read CLAUDE.md. We are doing PHASE 5 only: connect stages 1–8 into runs with a live event stream.

1. pipeline/orchestrator.py — runs stages 1→8 for a Run; emits RunEvents (stage_started / check_result / stage_completed / stage_failed / run_completed) with timestamps and durations; Stage 3 emits one check_result per verified field (status, source, bbox) so the UI can draw boxes live; persists events, extracted_json, verification_json and final result; on Approve applies ledger update + appends invoice_history (unless is_test_run); stops cleanly on EXTRACTION_FAILED with status "extraction_failed".
2. API (api/*.py):
   - POST /api/runs (multipart file OR sample_id, model, use_cache=false) → run_id; processing in a background task.
   - GET /api/runs/{id}/events — SSE (replays past events, then streams new; heartbeat every 15 s).
   - GET /api/runs/{id} — full run detail incl. verification (with boxes); GET /api/runs (filters: decision, status, vendor, model, date range, search; pagination).
   - GET /api/runs/{id}/pages/{n}.png — page images (same size/orientation the boxes refer to).
   - POST /api/runs/{id}/retry?model=groq — new run with same file, linked to the failed one.
   - GET /api/samples — golden + stress list (id, scenario, expected decision) for the sample picker.
   - GET /api/holds; POST /api/holds/{run_id}/action {action: approve|reject|assign_po|confirm_field, role, comment (required), payload} → logs hold_actions, marks decision "resolved_by_human", applies ledger update on approve.
   - GET /api/data/vendors, /api/data/pos (billed & remaining), /api/data/history.
   - GET /api/stats — counts by decision/status, avg duration, runs per model, top reason codes, % of fields verified, est. AP minutes saved (assume 8 min manual per invoice; show the assumption).
   - POST /api/admin/reset-demo — restore seeded state (CLAUDE.md §9).
   - POST /api/eval/golden — sandboxed Test Suite over the 12 golden invoices (is_test_run, ledger rollback), paced, use_cache configurable; GET /api/eval/latest returns expected vs actual.
3. scripts/run_pipeline.py <file|sample_id> --model … prints the event stream in the terminal with coloured stage lines.
4. Integration tests with a fake extractor (no network; OCR may be real or faked): every golden case end-to-end via API gives the expected decision; SSE delivers events in order; reset-demo restores ledger; approving the same invoice twice → second is DUPLICATE.

Phase Report, commit "Phase 5: orchestration + API".
```

**You test**
- [ ] `python backend/scripts/run_pipeline.py 01_happy_clean --model gemini` → 8 stages print, ends APPROVE.
- [ ] Run it again → REJECT as duplicate (correct!). `curl -X POST localhost:8000/api/admin/reset-demo` → run again → APPROVE.
- [ ] `http://localhost:8000/docs` → try POST /api/runs with a file.
- [ ] `curl -N localhost:8000/api/runs/<id>/events` → events stream, including per-field verification events.

---

## PHASE 6 — Frontend: New Run + Live Run View

```
Read CLAUDE.md (§10 UI requirements). We are doing PHASE 6 only.

App shell: left sidebar nav (New Run, Dashboard, Hold Queue, Test Suite, Data, Settings), product name "Invoice Agent", subtle "Demo data — Zenith Retail Pvt Ltd" badge.

1. New Run page:
   - Drag-and-drop upload (PDF/PNG/JPG, max 10 MB, clear validation errors) OR "Pick a sample" searchable list (golden first; scenario name; expected decision hidden behind a toggle).
   - Model selector (Gemini default / Groq) with one-line description and "configured" indicator; disabled if key missing.
   - "Use cached extraction" toggle, off by default (tooltip: saves free-tier quota).
   - Start → Live Run View.
2. Live Run View (centrepiece of the demo):
   - Left: page viewer (page images, page switcher, zoom) with an SVG/canvas overlay drawing verification boxes as Stage 3 events arrive: green solid = verified, red dashed label = "AI value not found on page". Hover shows field name + matched text.
   - Right: vertical stepper of the 8 stages; each shows pending / running (spinner) / passed / warning / failed, duration, and expands to its checks (✓/!/✗, plain-English message, invoice value vs reference value).
   - Stage 2: extracted fields table with confidence bars (red below threshold), model badge (+ "cached" badge if used).
   - Stage 3: same fields with verification badges ("✓ text layer", "✓ OCR", "✗ not found", "— OCR unavailable"); clicking a field jumps to and pulses its box on the correct page.
   - Final decision card: big APPROVE / HOLD / REJECT, every reason listed, and the action output: routed question + role (Hold), vendor note with copy button (Reject), ledger change before→after (Approve).
   - Extraction failure state: friendly explanation of the error type + "Retry with Groq/Gemini" (one click, same file).
   - Driven by SSE; reconnects if dropped; works when opened after the run finished (replays events).
3. Polish: consistent spacing, readable at 1366×768, quick transitions; INR formatting (₹1,23,456.00) everywhere.

Phase Report with screenshots if possible (Playwright), commit "Phase 6: new run + live view".
```

**You test**
- [ ] Run golden 01, 03, 05 from the sample picker — stages light up one by one; green boxes appear on the invoice during Stage 3.
- [ ] Click "total" in the fields table → viewer jumps to the box.
- [ ] Run 08 → red/no box on the smudged total, decision HOLD explains why.
- [ ] Drag-and-drop upload a PDF.
- [ ] Wrong Gemini key → failure screen → "Retry with Groq" works.
- [ ] Ask a friend to watch one run without explanation: can they tell what happened and why?

---

## PHASE 7 — Dashboard, Run Detail, Hold Queue, Test Suite, Data, Settings

```
Read CLAUDE.md. We are doing PHASE 7 only.

1. Dashboard: KPI tiles (total runs, Approve/Hold/Reject counts and %, avg processing time, % critical fields independently verified, est. AP time saved with assumption tooltip, runs by model); a small chart of decisions over time and top reason codes; runs table (time, file, vendor, amount, PO, model, decision, status, duration) with filters, search, pagination; row click → Run Detail. Test runs hidden by default (toggle).
2. Run Detail: same layout as Live Run View but static (boxes included), plus complete audit trail (every event + human actions with role, comment, time), raw extracted + verification JSON (collapsible), link to retried/original run.
3. Hold Queue: held invoices grouped by routed role; each card shows the question, key evidence (with a thumbnail crop of the relevant box when available) and actions: Approve / Reject / Assign PO (candidate POs with scores for PO_INFERRED/AMBIGUOUS) / Confirm value (for LOW_CONFIDENCE_FIELD / FIELD_NOT_VERIFIED — user types the correct value) — comment required; resolved cards show who/when/why.
4. Test Suite & Evaluation: "Run golden test suite" (progress, pacing countdown for rate limits, expected vs actual per case with ✓/✗, total score); plus latest rules-eval, extraction-eval and verification-eval reports rendered (confusion matrix, per-scenario pass rates, model comparison, verification recall / catch rate).
5. Data: Vendors (status badges), POs (value, billed, remaining, status, progress bar; expand to lines and linked invoices), Invoice history.
6. Settings: read-only config incl. verification settings and OCR status, plain-English explanations; configured models; "Reset demo data" with confirmation dialog.

Phase Report, commit "Phase 7: dashboard + supporting screens".
```

**You test**
- [ ] Run 5–6 golden cases → Dashboard numbers add up.
- [ ] Resolve Hold on 05 (assign PO) → audit trail shows your action; PO balance updates on Data page.
- [ ] Resolve Hold on 08 by confirming the total → logged with your comment.
- [ ] Run the golden test suite from the UI → 12/12.
- [ ] Reset demo data → dashboard and ledger back to seeded state.

---

## PHASE 8 — Hardening + real-world robustness

```
Read CLAUDE.md. We are doing PHASE 8 only: make it robust for a live demo and for real invoices I may upload.

1. Real-world set: data/invoices/real_world/README.md explaining how to add real invoices (my own purchase invoices, publicly available sample GST invoices) and hand-write labels/<file>.json (ground_truth fields only; decision optional). Run eval_extraction and eval_verification on whatever I add and report.
2. Real-world behaviour checks (tests + fixes):
   - Unknown vendor + no PO + different buyer → HOLD with clear reasons (VENDOR_UNKNOWN, BUYER_MISMATCH, PO_NOT_FOUND), never a crash or wrong Reject.
   - Phone photos (perspective, glare, shadows) → handled; OCR may verify less → Hold with clear reason, not a wrong decision.
   - Password-protected, corrupt, empty, 0-page, >10 MB, >5-page, non-invoice image → clean messages.
   - Tax-inclusive prices, multiple tax rates on one invoice, negative lines, round-off ±₹1, totals only in words, mixed Hindi/English labels → sensible results.
   - Mixed PDFs (some pages text, some scanned) → per-page source used correctly.
3. OCR resilience: simulate Tesseract missing / crashing / timing out (OCR timeout 20 s per page) → run completes with OCR_UNAVAILABLE warning and model-confidence fallback.
4. Reliability: timeouts everywhere, provider errors → friendly messages, SSE reconnection, server restart mid-run marks run "interrupted", rate-limit countdown in Test Suite.
5. Logging: structured logs per run_id; no API keys or file contents in logs.
6. Performance: typical digital invoice < 20 s end-to-end on Gemini; a 1-page scan's OCR < 8 s on the Render free instance (measure; if slower, lower OCR_DPI for large pages or OCR only the regions needed — report the trade-off). Check peak memory during OCR stays well within the free instance.
7. Re-run eval_rules (golden + stress), eval_verification (all) and the full test suite — Phase 3/4 targets must still hold.

Phase Report listing every edge behaviour verified, commit "Phase 8: hardening".
```

**You test**
- [ ] Upload 2–3 real invoices (e.g. an online-shopping invoice of yours) → fields correct, boxes on the right values, sensible HOLD with clear reasons.
- [ ] Upload a phone photo of a printed invoice.
- [ ] Upload a random non-invoice PDF and an unrelated image → graceful outcome.
- [ ] Temporarily set `VERIFY_ENABLED=false` (or a wrong `TESSERACT_CMD`) → runs still complete with the "OCR unavailable" warning. Restore.
- [ ] Stop the backend mid-run, restart → run shows "interrupted".

---

## PHASE 9 — Production DB, smoke test, README, demo script

```
Read CLAUDE.md. We are doing PHASE 9 only.

1. Production DB: DATABASE_URL → Supabase Postgres in Render env; seed + reset work on Postgres; one-time seeding command documented; connection pooling suitable for Supabase.
2. Render (Docker runtime from Phase 0.5): confirm build, health check /api/health (models + OCR ✓), all env vars set; document the warm-up step (free instance sleeps when idle).
3. scripts/smoke_test.py <base_url>: health (models + OCR), list samples, run golden 01 (expect APPROVE with verified total), run a mild-scan sample (expect OCR verification), reset demo. Run against the live URL.
4. README.md for interviewers: what it does (3 lines), live link, Mermaid architecture diagram, the 8 stages, "AI reads, OCR verifies, code decides", edge cases A–J table with expected outcomes, assumptions (INR only, one invoice per file, 2-way match, tolerance values, GST 2.0 rates, free-tier data note), how to run locally (incl. Tesseract/Docker), evaluation results (rules accuracy golden + stress, extraction accuracy per model, verification recall + fault-injection catch rate), known limitations and next steps (3-way match with GRN, email inbox ingestion, ERP connectors, learning from human overrides, multi-currency, layout-aware models).
5. docs/DEMO_SCRIPT.md: click-by-click order for (a) the 5-minute video: Reset → 01 happy (point at green boxes) → 03 overrun → 05 no-PO + resolve in Hold Queue → 08 unverified total → Dashboard; and (b) the live interview: 01, 03, 04, 05, 06, 08 + model switch + test suite + eval page; one or two sentences to say at each step; backup plan if a provider is rate-limited (switch model; cached extraction with visible badge).

Phase Report with live URL and smoke-test output, commit "Phase 9: production".
```

**You test (final checklist)**
- [ ] Live URL works on your phone and in an incognito window; health shows models ✓ and OCR ✓.
- [ ] Reset → run all 12 golden on the live link → all as expected, boxes visible.
- [ ] README reads well to someone who has never seen the project.
- [ ] Rehearse the demo script twice with a timer. Record the 5-minute video.
- [ ] 10 minutes before the interview: open the live URL (wake the instance), Reset demo data, check models + OCR ✓.

---

## PHASE 10 — Demo mode vs real mode

```
Read CLAUDE.md (§12). We are doing PHASE 10 only. Nothing that exists may change behaviour or accuracy in real
mode: the full test suite, eval_rules (golden + stress 283/283), the unseen set (42/42) and the verification evals
must give the same results before and after.

1. Start screen (no mode chosen yet): "Try demo (no sign-in)" and "Use real mode" (Gmail sign-in arrives in
   Phase 11). A banner shows the current mode on every screen, with a way back to the start screen.
2. Mode is a cookie. Every API request resolves its database through api/common.engine_of: real mode -> the main
   DATABASE_URL; demo mode -> the visitor's own sandbox (a SQLite copy of the freshly seeded database, keyed by a
   random visitor id cookie, deleted after DEMO_SANDBOX_TTL_HOURS of inactivity). No check, stage or rule changes.
3. Demo inbox: data/demo_inbox/inbox.json - fixed emails from the fictional vendors (sender = vendor email in the
   master) with the 12 golden invoices attached, plus emails without bills. Inbox screen: list, read, preview
   attachments, tick and run (one -> a run, several -> a batch). Runs remember the email they came from.
4. Demo restrictions: invoices only from the demo inbox (no uploads, no samples, no Test Suite runs - the files
   must exist in the PO data); Gemini only, with DEMO_GEMINI_API_KEY / DEMO_GEMINI_MODEL (no Groq, no fallback);
   at most DEMO_MAX_RUNS_PER_HOUR runs per visitor. Reset demo data resets only that visitor's sandbox.
5. Rate limit in demo: shown as a calm notice, "The AI model has reached its rate limit - please try again after
   some time", not as an error with a model switch.
6. Tests: sandbox isolation (two visitors never see each other's runs; real mode never sees demo runs), demo
   restrictions, demo settings (key/model, no Groq), inbox run -> run/batch with source email, reset per visitor.
Phase Report, commit "Phase 10: demo mode + demo inbox".
```

**You test**
- [ ] Incognito window: start screen -> Try demo -> inbox shows the sample emails -> run 01 -> APPROVE.
- [ ] A second incognito/browser: Try demo -> fresh data (01 is not "already paid").
- [ ] Real mode: dashboard still shows only your own runs; upload works as before.

---

## PHASE 11 — Real mode: Gmail inbox

```
Read CLAUDE.md. We are doing PHASE 11 only.

1. Google sign-in (OAuth 2.0, scope gmail.readonly + openid email). Client id/secret from env only. The refresh
   token is stored encrypted (Fernet key from env). Real mode is allowed only for OWNER_EMAIL.
2. The Inbox screen (same as demo) lists Gmail messages with PDF/PNG/JPG attachments (query + paging); chosen
   attachments are downloaded and queued exactly like demo inbox files; runs store the Gmail message id.
3. Disconnect button; token expiry handled with a clear "reconnect Gmail" message.
4. Tests with a fake Gmail client (tests/ only). No change to demo mode or decisions.
Phase Report, commit "Phase 11: gmail inbox".
```

