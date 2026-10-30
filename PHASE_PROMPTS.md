# PHASE_PROMPTS.md — Copy-paste prompts for Claude Code

**How to use this file**
1. Create an empty folder `invoice-agent/`, put `CLAUDE.md` and this file inside, open Claude Code there.
2. Paste **one phase prompt at a time**. Wait for the Phase Report.
3. Do the **"You test"** checklist yourself. Only move on when every box is ticked.
4. If something fails, paste the error and say: *"Fix this within Phase N only. Do not start the next phase."*
5. Start each new Claude Code session with: *"Read CLAUDE.md and PHASE_PROMPTS.md. We are on Phase N."*

| Phase | What | Day |
|---|---|---|
| 0 | Skeleton + hello-world deploy | 1 |
| 1 | Master data (vendors, POs, history) | 2 |
| 2 | Invoice generator: 12 golden + ~250 stress invoices with labels | 2 |
| 3 | AI extraction layer (Gemini + Groq) + extraction evaluation | 3 |
| 4 | Rules engine (stages 3–7) + rules evaluation on all invoices | 3–4 |
| 5 | Pipeline orchestration, run storage, API, live event stream | 4 |
| 6 | Frontend: New Run + Live Run View | 5 |
| 7 | Frontend: Dashboard, Run Detail, Hold Queue, Test Suite, Data, Settings | 5 |
| 8 | Hardening + real-world invoice robustness | 6 |
| 9 | Production deploy, smoke test, README, demo script | 6–7 |

---

## PHASE 0 — Skeleton and hello-world deploy

**Before pasting, you do:** create accounts — GitHub, Render, Supabase, Google AI Studio (Gemini API key), Groq (API key). Create an empty GitHub repo `invoice-agent`.

```
Read CLAUDE.md fully. We are doing PHASE 0 only.

Goal: an empty but working skeleton that runs locally and is ready to deploy.

Tasks:
1. Create the repository layout from CLAUDE.md §3 (empty modules with docstrings are fine).
2. Backend: FastAPI app with GET /api/health returning {"status":"ok","version":...,"models_configured":{"gemini":bool,"groq":bool}} — booleans say whether each API key env var is set (never return the keys).
3. config.py using pydantic-settings with every setting from CLAUDE.md §5 plus GEMINI_API_KEY, GROQ_API_KEY, GEMINI_MODEL, GROQ_MODEL, DATABASE_URL, APP_ENV. Create .env.example with placeholders and comments. Add .env, local.db, __pycache__, node_modules, dist to .gitignore.
4. Frontend: Vite + React + TypeScript + Tailwind + shadcn/ui initialised. One page that calls /api/health and shows status and which models are configured. Vite dev server proxies /api to the backend.
5. FastAPI serves frontend/dist as static files at "/" in production (SPA fallback to index.html for unknown non-/api routes).
6. A Makefile (or scripts) with: `make dev` (backend + frontend), `make test`, `make build` (builds frontend into dist).
7. render.yaml for a single Render web service: build installs Python deps + builds frontend; start runs uvicorn on $PORT. Environment variables declared without values.
8. pytest set up with one test for /api/health.
9. README.md with local setup steps.

Do not build any business logic yet. Finish with the Phase Report and commit "Phase 0: skeleton".
```

**You test**
- [ ] Copy `.env.example` → `.env`, paste your Gemini and Groq keys.
- [ ] `make dev` → open the frontend URL → page shows "ok" and both models ✓.
- [ ] `make test` passes.
- [ ] `git log` shows the commit; `.env` is **not** in git (`git status` shows it untracked/ignored).
- [ ] Push to GitHub, create a Render Web Service from the repo (or Blueprint from render.yaml), add env vars in Render → open the live URL → same page works. **You now have a live link on Day 1.**

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
   - vendors.csv — 40 vendors across ≥ 12 states (≈ 30% Maharashtra so both CGST+SGST and IGST cases are common). Columns: vendor_id, legal_name, trade_name, gstin, pan, state, state_code, address, email, phone, bank_name, bank_account, ifsc, status (approved 34 / pending 3 / blocked 3), category, payment_terms_days. Include realistic name variants risk (e.g. "Pvt Ltd" vs "Private Limited") by storing legal_name and trade_name.
   - po_headers.csv + po_lines.csv — ~200 POs over the last 9 months, 1–8 lines each, items from the vendor's category, statuses open / partially_billed / closed. PO numbers in format PO-2026-NNNN.
   - invoice_history.csv — ~400 past invoices (approved/paid) against those POs, with realistic invoice-number styles per vendor (e.g. "SIT/26-27/0881", "INV-00457", "2026/KOS/57", "BW1234"), dates after PO dates, partial billing on some POs, and PO statuses consistent with history (closed = fully billed).
   - Leave room for Phase 2: expose functions so Phase 2 scenarios can reserve specific POs/vendors and append history rows. The final CSVs are written by a single entry point (datagen/generate_all.py) so master data and scenarios stay consistent.
4. backend: SQLAlchemy models for all tables in CLAUDE.md §7; scripts/seed_db.py loads data/master/* into the DB (idempotent: drops & recreates seeded tables). Use SQLite locally.
5. A consistency checker datagen/validate_master.py: every GSTIN valid; vendor state matches GSTIN state code; every PO line belongs to an existing PO and vendor; billed totals per PO ≤ PO value; closed POs are fully billed; no duplicate invoice numbers per vendor in history; all GST rates valid for their dates. Prints a summary table.

Tests for all of the above. Phase Report, commit "Phase 1: master data".
```

**You test**
- [ ] `python -m datagen.generate_all --master-only` then `python -m datagen.validate_master` → all checks green, summary shows ~40 vendors / ~200 POs / ~400 history rows.
- [ ] Open `vendors.csv` and `po_lines.csv` in Excel/Sheets — do the names, items and prices look believable?
- [ ] Pick 2 GSTINs and check them on any free online GSTIN *format/checksum* validator (format only — they are fictional, so they won't exist on the government portal).
- [ ] `python backend/scripts/seed_db.py` runs twice without errors.

---

## PHASE 2 — Invoice generator (golden + stress sets with labels)

```
Read CLAUDE.md. We are doing PHASE 2 only: generate realistic invoice files with ground-truth labels.
Remember rule 6: expected outcomes come from scenario definitions, never from the decision engine (which doesn't exist yet anyway).

A. Layout templates (datagen/templates/, ReportLab). Build at least 8 visually distinct layouts so the extractor can't overfit:
   1. Classic GST tax invoice (bordered table, HSN column, CGST/SGST columns per line)
   2. Modern minimal (no borders, big total, sans font)
   3. Services invoice (SAC codes, hours × rate, no quantities of goods)
   4. Compact two-column header with tax summary table at bottom (rate-wise breakup)
   5. Multi-page invoice (2–3 pages, "continued on next page", totals only on last page)
   6. Landscape wide table with discount and freight columns
   7. "Tally-style" invoice (dense, small font, amount in words, declaration, signature block)
   8. Small-vendor invoice (simple, handwritten-style font for some values, stamp image)
   Every template: fictional logo drawn from shapes, vendor block, buyer block (Zenith), invoice meta, line table, totals, bank details, terms, authorised signatory.

B. Variation knobs (randomised per invoice, recorded in labels):
   - Title: "Tax Invoice", "TAX INVOICE", "GST Invoice", "Invoice", "Bill of Supply" (only for 0% items)
   - Label synonyms: Invoice No / Inv. No. / Bill No / Invoice #; PO No / P.O. Ref / Your Order No / Against PO / PO mentioned only in Notes; Date / Inv Date / Dated
   - Date formats: 05/03/2026, 05-03-2026, 5 Mar 2026, 05-Mar-26, March 5, 2026, 2026-03-05
   - Amount formats: ₹1,23,456.00 / Rs. 1,23,456/- / INR 123456.00 / 1,23,456 (no symbol)
   - Tax shown per line vs only in summary; CGST+SGST vs IGST per state rule; optional round-off line; optional discount; optional freight/packing charges; amount in words
   - Vendor name printed as legal name OR trade name OR slightly abbreviated ("Sharma IT Solns Pvt. Ltd."); GSTIN sometimes printed with spaces
   - Page count 1–3
C. Scan degradation (datagen/degrade.py) applied to the rendered page images, then saved back as an image-only PDF (and some as PNG/JPG files):
   - mild: 150–200 DPI, rotation ±1.5°, light noise, slight blur, JPEG quality 60–80  (should still be read correctly)
   - heavy: 100 DPI, rotation ±4°, strong blur/noise, shadow gradient, coffee-stain blotch, smudge over the total or invoice number (used for low-confidence scenario)
   - extras: rubber-stamp overlay, signature scribble, punch holes, fax-style black & white
D. Scenarios (datagen/scenarios.py). Each scenario reserves the vendors/POs/history it needs, applies a mutation, and declares expected_decision, acceptable_decisions and expected_reason_codes (must-include):

   GOLDEN SET (data/invoices/golden/, exactly these 12, fixed files, clean digital unless stated):
   01_happy_clean — approved Maharashtra vendor, exact PO match → APPROVE
   02_happy_tolerance — different layout, ₹200 rounding difference within tolerance → APPROVE (PRICE_VARIANCE_WITHIN_TOLERANCE)
   03_A_split_overrun — 3rd partial invoice on a PO already billed ~88% → HOLD (PO_OVERRUN)
   04_B_duplicate — same invoice as a paid history row but number styled differently (e.g. KOS-0457 vs KOS/457) → REJECT (DUPLICATE_INVOICE_NUMBER)
   05_C_no_po — no PO reference; two open POs for this vendor, one clearly matches → HOLD (PO_INFERRED)
   06_D_bank_change — bank account/IFSC differ from vendor master → HOLD (BANK_DETAILS_MISMATCH)
   07_E_wrong_gst — inter-state vendor charges CGST+SGST → REJECT (GST_TYPE_INVALID)
   08_F_blurry_scan — heavy scan, total smudged → HOLD (LOW_CONFIDENCE_FIELD); acceptable_decisions also includes the underlying correct decision
   09_G_price_variance — unit price +3% vs PO → HOLD (PRICE_VARIANCE_OVER_TOLERANCE)
   10_H_bad_maths — line amounts don't sum to printed total → REJECT (ARITHMETIC_MISMATCH)
   11_I_quotation — document titled "Quotation" → REJECT (NOT_A_TAX_INVOICE)
   12_J_unapproved_vendor — vendor with status pending → HOLD (VENDOR_NOT_APPROVED)

   STRESS SET (data/invoices/stress/, ~250 files, randomised across all templates; ~30% mild scans; ids like S0001):
   CLEAN_EXACT 40 · CLEAN_WITHIN_TOLERANCE 15 · PO_OVERRUN 15 ·
   DUPLICATE_EXACT_NUMBER 8 · DUPLICATE_DISGUISED_NUMBER 12 · POSSIBLE_DUPLICATE (same vendor+amount, date ±2 days, different number) 8 ·
   NO_PO_CLEAR_MATCH 12 · NO_PO_AMBIGUOUS 8 · BANK_CHANGE 12 · GST_WRONG_TYPE 12 (both directions: IGST charged intra-state too) ·
   HEAVY_SCAN_LOW_CONFIDENCE 12 · PRICE_OVER_TOLERANCE 12 · QTY_EXCEEDS_PO 8 · ITEM_NOT_ON_PO 6 · ARITHMETIC_ERROR 12 ·
   NOT_AN_INVOICE 12 (quotation, proforma, credit note, delivery challan, purchase order copy) ·
   VENDOR_NOT_APPROVED 6 · VENDOR_BLOCKED 4 · VENDOR_UNKNOWN 8 · BUYER_MISMATCH 6 · PO_CLOSED 6 · GST_RATE_UNUSUAL 6 (e.g. 12% on an invoice dated after 22 Sep 2025) ·
   MISSING_INVOICE_NUMBER 6 · MULTI_ISSUE 15 (2–3 problems at once, e.g. bank change + price variance; expected decision follows severity precedence and ALL codes must be listed).
E. Labels: one JSON per file in labels/ exactly as CLAUDE.md §7 describes; ground_truth is what is PRINTED (e.g. printed invoice number "KOS/457", not the normalised one).
F. History & master consistency: scenarios append the history rows they need (originals for duplicates, prior partial bills for overruns) and generate_all.py writes final CSVs + files in one run. Re-run validate_master.py at the end.
G. Contact sheets: datagen/contact_sheet.py writes data/invoices/contact_sheet_golden.png and contact_sheet_stress_<n>.png (grids of first-page thumbnails with ids) so I can eyeball variety quickly.
H. Self-verification (no AI): for every DIGITAL file, extract the text layer with PyMuPDF and assert that key printed values in ground_truth (invoice number, total, GSTIN, PO ref if printed) actually appear in the text. Report pass rate (must be 100%).
I. Summary report printed + saved to data/invoices/generation_report.md: counts by scenario, template, scanned/digital, expected decision.

Tests for knobs, degrader, label schema validity. Phase Report, commit "Phase 2: invoice generator".
```

**You test**
- [ ] `python -m datagen.generate_all` finishes; `generation_report.md` shows 12 golden + ~250 stress, roughly 35–40% Approve, mix of Hold/Reject.
- [ ] Open `contact_sheet_golden.png` — 12 different-looking invoices?
- [ ] Open 5 random stress PDFs — would you believe they're real invoices? Check one multi-page and one heavy scan.
- [ ] Open `04_B_duplicate` and find the original row in `invoice_history.csv` — same vendor/amount, number styled differently?
- [ ] Open `03_A_split_overrun` — find its PO and the 2 earlier invoices in history; do the sums actually exceed the PO?
- [ ] Self-verification pass rate = 100%.

---

## PHASE 3 — AI extraction layer + extraction evaluation

```
Read CLAUDE.md. We are doing PHASE 3 only: Stage 2 extraction with two providers, plus an evaluation harness.

1. extraction/base.py — Extractor interface: extract(file_bytes, mime, page_images) -> ExtractionResult {invoice: ExtractedInvoice | None, error: ExtractionError | None, model_name, latency_ms, raw_response}. ExtractionError has type (rate_limited | timeout | invalid_response | provider_error | auth_error | unsupported_file) and a user-friendly message.
2. extraction/prompt.py — one shared extraction prompt + JSON schema used by both providers. The prompt must: extract only what is printed; return null for anything absent; never compute or infer missing totals; classify document_type; give per-field confidence (0–1) and a short evidence snippet; keep numbers as printed strings AND parsed numbers where possible; handle Indian formats and multi-page invoices (totals usually on last page). Temperature 0.
3. extraction/gemini.py — google-genai SDK; send the PDF bytes directly (or the image for PNG/JPG); use structured JSON output with the schema; model from GEMINI_MODEL.
4. extraction/groq.py — groq SDK; render pages to PNG with PyMuPDF (max 5 pages, ~150 DPI, size-limited), send as images; JSON mode; model from GROQ_MODEL (must be vision-capable — check Groq's current model list and tell me which one you chose and why).
5. Validation: Pydantic-validate the JSON; on failure do ONE repair retry (send the validation error back); then fail with invalid_response. Map provider exceptions to ExtractionError types (429 → rate_limited, etc.). Timeout 60 s.
6. extraction/cache.py — DB cache keyed by (file_hash, model); used only when use_cache=True.
7. scripts/extract_one.py <file> --model gemini|groq [--no-cache] → pretty-prints extracted fields with confidence, latency, and model.
8. scripts/eval_extraction.py — compares extraction against labels:
   - --set golden|stress|real_world, --model gemini|groq|both, --sample N (stratified by template, scanned/digital, scenario), --delay seconds between calls (default 13 s to respect free-tier limits), resumable (uses cache, skips done files).
   - Field scores after normalisation: invoice_number, invoice_date, vendor_gstin, buyer_gstin, po_reference, total_amount (± ₹1), subtotal, tax amounts, line-item count, line amounts, document_type.
   - Report: overall field accuracy, accuracy by template, digital vs mild scan vs heavy scan, per-model comparison, list of worst files. Save markdown + CSV to data/eval_reports/.
9. Tests use recorded fake responses (no network in unit tests).

Phase Report (include the model names chosen and measured accuracy on the golden set for both models), commit "Phase 3: extraction".
```

**You test**
- [ ] `python backend/scripts/extract_one.py data/invoices/golden/01_happy_clean.pdf --model gemini` → fields look right.
- [ ] Same with `--model groq`.
- [ ] Same on `08_F_blurry_scan` → the smudged field has **low confidence**, not a confident wrong number.
- [ ] Temporarily set a wrong GEMINI_API_KEY in `.env` → you get a clean `auth_error` message, not a crash. Restore the key.
- [ ] `eval_extraction.py --set golden --model both` → report shows accuracy for both models.
- [ ] Optional (spread across days to stay within free limits): `--set stress --sample 40 --model gemini`.

---

## PHASE 4 — Rules engine (stages 3–7) + rules evaluation

```
Read CLAUDE.md. We are doing PHASE 4 only: deterministic stages 3–7 as pure functions.

1. pipeline/reason_codes.py — ReasonCode enum exactly as CLAUDE.md §6, each with severity, routed role and a message template with placeholders (e.g. "Unit price ₹{billed} is {pct}% above PO price ₹{po} (tolerance {tol}%)").
2. pipeline/normalise.py — dates, amounts, invoice numbers, GSTIN, names; thorough unit tests with messy inputs (all formats from Phase 2 knobs + extra real-world ones).
3. pipeline/self_check.py, vendor_check.py, duplicate_check.py, po_match.py, amount_match.py — exactly the logic in CLAUDE.md §6. Each check returns CheckResult {code|None, passed, severity, message, evidence {invoice_field, invoice_value, reference_source, reference_value}}. Each function has a one-line business-rule docstring.
4. pipeline/decision.py — severity precedence, approve-with-note, routed question text for Hold, draft vendor note for Reject (polite, specific, lists exactly what to fix), ledger update instructions for Approve. Pure function: inputs → Decision; no DB writes here.
5. Data access through a small repository interface so the engine can run on (a) the DB or (b) in-memory master data for tests/eval.
6. scripts/eval_rules.py — runs stages 3–7 on the LABEL ground_truth (no AI, so it covers ALL ~262 invoices instantly). For each invoice compares decision vs expected_decision/acceptable_decisions and checks all expected_reason_codes are present. Treat each invoice independently against the seeded state (no ledger mutation between invoices). Outputs: overall accuracy, confusion matrix (expected vs actual decision), per-scenario pass rate, list of failures with diffs. Save to data/eval_reports/rules_eval_<timestamp>.md.
   Target: golden 12/12 and stress ≥ 98%. For any failure, decide whether the LOGIC or the SCENARIO definition is wrong and explain which to me — do not silently change labels.
7. Unit tests for every check incl. boundaries (exactly at tolerance, ₹1 rounding, 0% GST, inter/intra-state, PO fully billed, inferred-PO gap just below 0.15).

Phase Report (paste the confusion matrix), commit "Phase 4: rules engine".
```

**You test**
- [ ] `python backend/scripts/eval_rules.py --set golden` → 12/12.
- [ ] `--set stress` → ≥ 98%, and you read the explanation for every failure.
- [ ] Open the report: does each Hold have a sensible routed question? Does each Reject have a vendor note you'd be happy to send?
- [ ] Pick case 03 (overrun) and do the arithmetic by hand from the CSVs — does it match the message?

---

## PHASE 5 — Orchestration, storage, API, live events

```
Read CLAUDE.md. We are doing PHASE 5 only: connect stages 1–7 into runs with a live event stream.

1. pipeline/orchestrator.py — runs stages 1→7 for a Run; emits RunEvents (stage_started / check_result / stage_completed / stage_failed / run_completed) with timestamps and durations; persists events and final result; on Approve applies ledger update + appends invoice_history (unless is_test_run); stops cleanly on EXTRACTION_FAILED with status "extraction_failed".
2. API (api/*.py):
   - POST /api/runs (multipart file OR sample_id, model, use_cache=false) → run_id; processing runs in a background task.
   - GET /api/runs/{id}/events — SSE stream (replays past events then streams new ones; heartbeat every 15 s).
   - GET /api/runs/{id} — full run detail; GET /api/runs (filters: decision, status, vendor, model, date range, search; pagination).
   - GET /api/runs/{id}/pages/{n}.png — page images.
   - POST /api/runs/{id}/retry?model=groq — new run with same file, linked to the failed one.
   - GET /api/samples — list golden + stress invoices (id, scenario, expected decision) for the sample picker.
   - GET /api/holds; POST /api/holds/{run_id}/action {action: approve|reject|assign_po|confirm_field, role, comment (required), payload} → logs hold_actions, updates run decision as "resolved_by_human", applies ledger update on approve.
   - GET /api/data/vendors, /api/data/pos (with billed & remaining balance), /api/data/history.
   - GET /api/stats — counts by decision/status, avg duration, runs per model, top reason codes, estimated AP minutes saved (assume 8 min manual per invoice; show the assumption).
   - POST /api/admin/reset-demo — restore seeded state (CLAUDE.md §9).
   - POST /api/eval/golden — Test Suite: runs the 12 golden invoices as sandboxed test runs (is_test_run, ledger rollback), paced by delay, use_cache configurable; GET /api/eval/latest returns expected vs actual.
3. scripts/run_pipeline.py <file|sample_id> --model … prints the event stream in the terminal with coloured stage lines.
4. Integration tests with a fake extractor (no network): every golden case end-to-end via API gives the expected decision; SSE delivers events in order; reset-demo restores ledger; approving the same invoice twice → second is DUPLICATE.

Phase Report, commit "Phase 5: orchestration + API".
```

**You test**
- [ ] `python backend/scripts/run_pipeline.py 01_happy_clean --model gemini` → 7 stages print, ends APPROVE.
- [ ] Run it again → now REJECT as duplicate (correct!). Then `curl -X POST localhost:8000/api/admin/reset-demo` and run again → APPROVE.
- [ ] Open `http://localhost:8000/docs` (FastAPI auto docs) and try POST /api/runs with a file.
- [ ] `curl -N localhost:8000/api/runs/<id>/events` shows events streaming.

---

## PHASE 6 — Frontend: New Run + Live Run View

```
Read CLAUDE.md (§10 UI requirements). We are doing PHASE 6 only.

App shell: left sidebar nav (New Run, Dashboard, Hold Queue, Test Suite, Data, Settings), product name "Invoice Agent", subtle "Demo data — Zenith Retail Pvt Ltd" badge.

1. New Run page:
   - Drag-and-drop upload (PDF/PNG/JPG, max 10 MB, clear validation errors) OR "Pick a sample" searchable list (golden first, with scenario name and expected decision shown as a hint toggle).
   - Model selector (Gemini default / Groq) with one-line description and a "configured" indicator; disabled if key missing.
   - "Use cached extraction" toggle, off by default (tooltip explains it saves free-tier quota).
   - Start → navigates to Live Run View.
2. Live Run View (the centrepiece of the demo):
   - Left: page viewer (page images, page switcher, zoom). When a field is selected on the right, show its evidence text.
   - Right: vertical stepper of the 7 stages; each shows pending / running (spinner) / passed / warning / failed, duration, and expands to show its checks (✓/!/✗, plain-English message, invoice value vs reference value).
   - Stage 2 expanded shows extracted fields as a table with confidence bars (red below threshold) and model badge (+ "cached" badge if used).
   - Final decision card: big APPROVE / HOLD / REJECT, every reason listed, and the action output: routed question + role (Hold), vendor note with copy button (Reject), ledger change before→after (Approve).
   - Extraction failure state: friendly explanation of the error type + "Retry with Groq/Gemini" button (one click, same file).
   - Driven by the SSE stream; reconnects if dropped; works if opened after the run finished (replays events).
3. Visual polish: consistent spacing, readable at 1366×768, smooth but quick transitions; INR formatting (₹1,23,456.00) everywhere.

Phase Report with screenshots if you can take them (Playwright), commit "Phase 6: new run + live view".
```

**You test**
- [ ] Run golden 01, 03, 05 from the sample picker — watch stages light up one by one.
- [ ] Click an extracted field — evidence shows; low-confidence fields are visibly red on 08.
- [ ] Upload a PDF by drag-and-drop.
- [ ] Set a wrong Gemini key → failure screen → "Retry with Groq" works.
- [ ] Ask a friend to watch one run without explanation: can they tell what happened and why?

---

## PHASE 7 — Dashboard, Run Detail, Hold Queue, Test Suite, Data, Settings

```
Read CLAUDE.md. We are doing PHASE 7 only.

1. Dashboard: KPI tiles (total runs, Approve/Hold/Reject counts and %, avg processing time, est. AP time saved with assumption tooltip, runs by model); a small chart of decisions over time and top reason codes; runs table (time, file, vendor, amount, PO, model, decision, status, duration) with filters, search, pagination; row click → Run Detail. Test runs hidden by default (toggle).
2. Run Detail: same layout as Live Run View but static, plus the complete audit trail (every event + human actions with role, comment, time), raw extracted JSON (collapsible), and link to the retried/original run if any.
3. Hold Queue: list of held invoices grouped by routed role; each card shows the question, key evidence and actions: Approve / Reject / Assign PO (dropdown of candidate POs with scores for PO_INFERRED/AMBIGUOUS) / Confirm value (for LOW_CONFIDENCE_FIELD) — comment required; after action the card moves to "Resolved" with who/when/why.
4. Test Suite & Evaluation: "Run golden test suite" button (shows progress, pacing countdown for rate limits, expected vs actual per case with ✓/✗, total score); plus the latest rules-eval and extraction-eval reports rendered (confusion matrix, per-scenario pass rates, model comparison).
5. Data: Vendors (status badges), POs (value, billed, remaining, status, progress bar; expand to lines and linked invoices), Invoice history.
6. Settings: read-only view of tolerance/confidence/PO-inference config with plain-English explanation; configured models; "Reset demo data" button with confirmation dialog.

Phase Report, commit "Phase 7: dashboard + supporting screens".
```

**You test**
- [ ] Run 5–6 golden cases, then check the Dashboard numbers add up.
- [ ] Resolve a Hold (assign PO on case 05) → audit trail shows your action; PO balance updated on Data page.
- [ ] Run the golden test suite from the UI → 12/12 (or explained acceptable outcome on 08).
- [ ] Reset demo data → dashboard and ledger back to the seeded state.

---

## PHASE 8 — Hardening + real-world robustness

```
Read CLAUDE.md. We are doing PHASE 8 only: make it robust for a live demo and for real invoices I may upload.

1. Real-world set: create data/invoices/real_world/README.md telling me how to add real invoices (my own purchase invoices, publicly available sample GST invoices) and hand-write labels/<file>.json (ground_truth fields only; decision optional). Run eval_extraction on whatever I add and report.
2. Real-world behaviour checks (add tests + fixes):
   - Unknown vendor + no PO + addressed to a different buyer → HOLD with clear reasons (VENDOR_UNKNOWN, BUYER_MISMATCH, PO_NOT_FOUND), never a crash or a wrong Reject.
   - Image uploads (phone photo of an invoice: perspective, glare) → handled; low confidence → Hold.
   - Password-protected, corrupt, empty, 0-page, >10 MB, >5-page, non-invoice image (e.g. a photo of a cat) → clean messages.
   - Invoices with tax-inclusive prices, multiple tax rates on one invoice, negative lines (discounts/credits), round-off up to ±₹1, totals only in words, invoice in a mix of Hindi/English labels → sensible results.
3. Reliability: timeouts everywhere, provider errors mapped to friendly messages, SSE reconnection, server restart mid-run marks the run "interrupted" (not stuck forever), rate-limit countdown in the Test Suite.
4. Logging: structured logs per run_id; no API keys or file contents in logs.
5. Performance: a typical digital invoice completes in < 20 s end-to-end on Gemini; page rendering cached.
6. Re-run eval_rules on golden + stress (must still meet Phase 4 targets) and full test suite.

Phase Report listing every edge behaviour verified, commit "Phase 8: hardening".
```

**You test**
- [ ] Upload 2–3 real invoices (e.g. an online-shopping invoice of yours) → sensible HOLD with clear reasons, extracted fields correct.
- [ ] Upload a phone photo of a printed invoice.
- [ ] Upload a random non-invoice PDF and an image of something else → graceful outcome.
- [ ] Stop the backend mid-run, restart → run shows "interrupted", not spinning forever.

---

## PHASE 9 — Production deploy, smoke test, README, demo script

```
Read CLAUDE.md. We are doing PHASE 9 only.

1. Production DB: switch DATABASE_URL to Supabase Postgres in Render env; make seed + reset work on Postgres; one-time seeding command documented. Verify connection pooling settings suitable for Supabase.
2. Render: confirm render.yaml builds frontend + backend in one service; health check path /api/health; set all env vars; note that the free instance sleeps when idle (document a warm-up step).
3. Smoke test script scripts/smoke_test.py <base_url>: health, list samples, run golden 01 (expects APPROVE), reset demo. Run it against the live URL.
4. README.md for interviewers: what it does (3 lines), live link, 60-second architecture diagram (Mermaid), the 7 stages, "AI reads, code decides", edge cases A–J table with expected outcomes, assumptions (INR only, one invoice per file, 2-way match, tolerance values, GST 2.0 rates, free-tier data note), how to run locally, evaluation results (paste golden + stress rules accuracy and extraction accuracy per model), known limitations and next steps (3-way match with GRN, email inbox ingestion, ERP connectors, learning from human overrides, multi-currency).
5. docs/DEMO_SCRIPT.md: exact click-by-click order for (a) the 5-minute video: Reset → 01 happy → 03 overrun → 05 no-PO + resolve in Hold Queue → Dashboard; and (b) the live interview: 01, 03, 04, 05, 06 + model switch + test suite; with what to say at each step (one or two sentences each) and backup plan if a provider is rate-limited (switch model; cached extraction with visible badge).

Phase Report with the live URL and smoke-test output, commit "Phase 9: production".
```

**You test (final checklist)**
- [ ] Live URL works from your phone and an incognito window.
- [ ] Reset → run all 12 golden on the live link → all as expected.
- [ ] README reads well to someone who has never seen the project.
- [ ] Rehearse the demo script twice with a timer. Record the 5-minute video.
- [ ] 10 minutes before the interview: open the live URL (wake the free instance), Reset demo data, check both models ✓.
