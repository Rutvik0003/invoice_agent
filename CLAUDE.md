# CLAUDE.md — Invoice Decision Agent (Zamp ASA Case Study, PS-1)

> Put this file in the root of the repository. Claude Code reads it automatically at the start of every session.
> Owner: Rutvik Kachhadiya. Build is done phase by phase from `PHASE_PROMPTS.md`.
>
> **Version 2 (changelog):** added Stage 3 "Verify on page" — an independent OCR / PDF-text-layer check of the AI's extracted values (pipeline is now **8 stages**); new reason code `FIELD_NOT_VERIFIED`; highlight boxes in the UI; deployment moves to **Docker** (needed for Tesseract OCR). Phase 0 was built under v1 — Phase 0.5 migrates it.

---

## 1. What we are building

A web app that takes a vendor invoice (PDF or image) and produces a clear, reasoned **Approve / Hold / Reject** decision, with every step visible.

- **Input:** an invoice PDF/image uploaded by the user (simulates an AP email inbox).
- **Processing:** 8 stages. An AI model reads the invoice; an independent OCR/text-layer check verifies what the AI read; plain Python code makes every decision.
- **Output:** a decision card with plain-English reasons, a full audit trail, a routed question (Hold) or a draft vendor note (Reject), and an update to the PO ledger (Approve).
- **UI:** a live run view (each stage lights up as it runs, extracted values highlighted on the invoice image) and a dashboard (history, status, outputs across runs). The UI is graded.
- **Audience:** Zamp interviewers (AI finance-ops company). It must run live, reliably, during an interview.

## 2. Non-negotiable rules for Claude Code

1. **Work on one phase at a time.** Only do what the current phase prompt asks. When the phase is done, stop and print the "Phase report" (see §11). Never start the next phase on your own.
2. **AI reads, OCR verifies, code decides.** The LLM is used only in Stage 2 (extraction). OCR / the PDF text layer is used only in Stage 3 to confirm or doubt what the LLM read — it never replaces LLM values and never decides anything. Vendor matching, duplicate detection, PO matching, maths, tax checks and the final decision are deterministic Python. Never ask an LLM to make or explain a decision.
3. **Never invent data.** If a field is not on the invoice, extraction returns `null`. Never fill gaps with guesses or defaults.
4. **When unsure → Hold.** Code must never auto-approve something it is not sure about (inferred PO, low-confidence or unverified critical field).
5. **Never fake tests.** Do not change expected outcomes, labels or thresholds just to make a test pass. If a test fails, fix the logic or stop and explain the conflict to me.
6. **Expected outcomes are defined by the scenario, never by running the engine.** The data generator writes expected decisions from the scenario definition (§8). It must never import or call the decision engine or the verifier.
7. **No secrets in code or git.** API keys come only from environment variables. Keep `.env` in `.gitignore`; maintain `.env.example` with placeholder values.
8. **No mock paths in production code.** Fakes/stubs are allowed only inside `tests/`.
9. **Every reason has a code.** All check results use the fixed `ReasonCode` enum (§6) with a severity and a plain-English message template.
10. **Small, typed, tested.** Python 3.11+, type hints everywhere, Pydantic models at every boundary, pure functions for checks, `pytest` tests for every module. Run the full test suite before declaring a phase done.
11. **Explainable code.** Clear names, short functions, a docstring on every check explaining the business rule in one sentence. I must be able to explain any line in an interview.
12. **Ask before adding dependencies** not listed in §4, and before changing anything in §5–§7.
13. **Commit at the end of each phase** with message `Phase N: <summary>` (only after tests pass).
14. **Degrade gracefully.** If OCR is unavailable or crashes, the run continues using model confidence only and the UI shows an "OCR unavailable — not verified" warning. OCR problems must never crash a run.

## 3. Repository layout

```
invoice-agent/
├── CLAUDE.md
├── PHASE_PROMPTS.md
├── README.md
├── .env.example
├── Dockerfile                     # multi-stage: build frontend → Python + Tesseract runtime (Phase 0.5)
├── .dockerignore
├── render.yaml                    # Render service using Docker runtime
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app; also serves frontend/dist
│   │   ├── config.py              # settings from env (pydantic-settings)
│   │   ├── db.py, models.py       # SQLAlchemy engine + tables
│   │   ├── schemas.py             # Pydantic models (ExtractedInvoice, VerificationResult, CheckResult, Decision, RunEvent…)
│   │   ├── extraction/            # base.py, gemini.py, groq.py, prompt.py, cache.py, pdf_utils.py
│   │   ├── verification/          # page_text.py (PyMuPDF words), ocr.py (Tesseract words), matchers.py, verify.py
│   │   ├── pipeline/              # intake, normalise, self_check, vendor_check, duplicate_check,
│   │   │                          # po_match, amount_match, decision, reason_codes, orchestrator
│   │   └── api/                   # runs.py, data.py, holds.py, eval.py, admin.py
│   ├── scripts/                   # seed_db.py, extract_one.py, verify_one.py, run_pipeline.py,
│   │                              # eval_rules.py, eval_extraction.py, eval_verification.py, smoke_test.py
│   └── tests/
├── datagen/                       # catalog.py, gstin.py, master_data.py, scenarios.py,
│                                  # templates/, render.py, degrade.py, contact_sheet.py, generate_all.py
├── data/
│   ├── master/                    # buyer.json, vendors.csv, po_headers.csv, po_lines.csv, invoice_history.csv
│   ├── invoices/golden/           # 12 demo invoices + labels/
│   ├── invoices/stress/           # ~250 generated invoices + labels/
│   ├── invoices/real_world/       # real invoices added by Rutvik + labels/ (optional)
│   └── eval_reports/
└── frontend/                      # React + Vite + TypeScript + Tailwind + shadcn/ui
```

## 4. Tech stack (all free)

| Part | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2, Pydantic v2, pydantic-settings |
| Database | SQLite locally (`DATABASE_URL=sqlite:///./local.db`); Supabase Postgres in production (same SQLAlchemy code). Store uploaded files as bytes in the DB (files ≤ 10 MB) — no separate storage service. |
| AI extraction | Google Gemini (free tier, Flash model) via `google-genai`; Groq (free tier, vision-capable model) via `groq`. **Model names come from env vars** (`GEMINI_MODEL`, `GROQ_MODEL`) — check the providers' current model lists; do not hardcode, as providers retire models. |
| Verification — digital PDFs | PyMuPDF `page.get_text("words")` (exact text + word boxes; no OCR needed) |
| Verification — scans/photos | Tesseract OCR via `pytesseract` (`image_to_data` → words + boxes + per-word confidence), English language pack. Installed as a system package in the Docker image. Light on memory (fits Render free instance). |
| PDF handling | PyMuPDF (`pymupdf`) — text-layer detection, page → PNG rendering |
| Fuzzy matching | RapidFuzz |
| Live updates | Server-Sent Events (`sse-starlette`) |
| Real mode: sign-in + Gmail | Google OAuth 2.0 + Gmail API v1 over HTTPS (`httpx`), stored token encrypted with `cryptography` (Fernet); scopes `openid email gmail.readonly` |
| Data generation | ReportLab (PDFs), Pillow + NumPy (scan degradation), Faker (`en_IN` locale) |
| Tests | pytest |
| Frontend | React + Vite + TypeScript + Tailwind + shadcn/ui + lucide-react icons + TanStack Query |
| Hosting | Render, **Docker runtime**, single web service (FastAPI serves API + built frontend) |

Local development: install Tesseract on the developer machine (Windows: UB-Mannheim installer and add to PATH / set `TESSERACT_CMD`; macOS: `brew install tesseract`; Linux: `apt install tesseract-ocr`). If it is missing locally, the app still runs with the "OCR unavailable" warning (rule 14). `docker build` + `docker run` must also work locally.

## 5. Business context and configuration

- **Buyer company:** Zenith Retail Pvt Ltd, Maharashtra (GST state code `27`). Buyer GSTIN in `data/master/buyer.json`.
- **Currency:** INR only. **One invoice per file.** (Documented assumptions.)
- **GST slabs (GST 2.0, effective 22 Sep 2025):** valid rates are 0%, 5%, 18%, 40% (plus special 3% and 0.25% for precious metals/stones). Invoices dated before 22 Sep 2025 may legitimately show 12% or 28%.
- **GST type rule:** vendor state (first 2 digits of vendor GSTIN) == buyer state → CGST + SGST, each = half the rate. Different state → IGST at the full rate.
- **Config (env vars with defaults, shown in a Settings panel):**
  - `TOLERANCE_PCT=1.0` and `TOLERANCE_ABS_INR=500` → a variance is acceptable if ≤ min(1% of value, ₹500)
  - `CONFIDENCE_THRESHOLD=0.80` → model confidence below this is "low"
  - `PO_INFER_MIN_SCORE=0.85`, `PO_INFER_MIN_GAP=0.15`, `PO_INFER_FLOOR=0.50`
  - `POSSIBLE_DUP_DAYS=3`
  - `DEFAULT_MODEL=gemini`
  - `VERIFY_ENABLED=true`, `OCR_DPI=300`, `OCR_MIN_WORD_CONF=40` (ignore OCR words below this), `VERIFY_FUZZY_MIN=90` (text identifiers), `TESSERACT_CMD` (optional path)
- **Critical fields (must be present, and verified or high-confidence):** vendor_gstin, vendor_name, invoice_number, invoice_date, total_amount. **Verified fields:** the critical fields + po_reference, subtotal, cgst/sgst/igst, bank_account, buyer_gstin.

## 6. The 8-stage pipeline

Each stage emits `RunEvent`s (`stage_started`, `check_result`, `stage_completed`, `stage_failed`) that are saved to the DB and streamed over SSE.

1. **Intake** — accept PDF/PNG/JPG; reject other types, empty or password-protected files with a clear error; compute SHA-256; detect text-layer vs scanned per page (PyMuPDF); render page images for the UI; create a `Run` record with the chosen model.
2. **Read & extract (AI — exactly one model call per invoice)** — returns `ExtractedInvoice` (§7) with per-field confidence and a short `evidence` snippet for key fields. Validate with Pydantic; on invalid JSON, one repair retry; on failure, stop the run with `EXTRACTION_FAILED` and a typed reason (`rate_limited`, `timeout`, `invalid_response`, `provider_error`, `auth_error`). The user can retry with the other model in one click (no silent auto-switch). Gemini receives the PDF directly; Groq receives page PNGs (max 5 pages).
3. **Verify on page (no AI)** — build a word list with boxes for every page: text-layer pages → PyMuPDF words (source `text_layer`, exact); image pages / image files → Tesseract words at `OCR_DPI` (source `ocr`, with word confidence). For each verified field (§5) with a non-null value, search the words (single words and runs of up to 6 adjacent words on the same line) using type-aware matchers:
   - **amounts:** parse every number-like token/run (remove ₹, Rs, INR, commas, "/-") and compare numerically within ± ₹1;
   - **invoice number / PO ref:** normalised exact match, else RapidFuzz ratio ≥ `VERIFY_FUZZY_MIN` after mapping common OCR confusions (O↔0, I/l↔1, S↔5, B↔8, Z↔2);
   - **GSTIN / bank account:** normalised (no spaces) exact, or ≤ 1 character different only when source is `ocr`;
   - **dates:** parse date-like tokens/runs in all supported formats → compare as ISO dates;
   - **names:** RapidFuzz token_set_ratio ≥ 90.
   Output per field: `status` ∈ {`verified`, `not_found`, `not_applicable` (value is null), `unavailable` (OCR failed/disabled)}, `source`, `page`, `bbox` (normalised 0–1 coordinates, for UI highlighting), `matched_text`, `ocr_word_conf`.
   **Stage 3b — cross-check (no AI, added after Phase 8 at Rutvik's request):** a `not_found` / `unavailable` field becomes `cross_checked` (source `master_data` or `calculation`) when our records confirm the AI's value: buyer GSTIN = Zenith's; vendor GSTIN and name belong to the same vendor-master record; bank account / PO belong to that vendor; or the AI's GSTIN fails the GSTIN check digit, is ≤ 2 characters from a master GSTIN (Zenith's or a vendor's), and that master GSTIN is printed on the page (a misreading; `reference_value` = the printed master GSTIN, used by the buyer/vendor checks); or the amount follows from amounts found on the page (lines → subtotal, CGST = SGST, subtotal + GST → total; a calculation needs at least one page anchor). Listed as INFO `FIELD_CROSS_CHECKED`. Invoice number and date cannot be cross-checked.
   **Effective trust rule (used by later stages):** a field is **trusted** if `verified` or `cross_checked`, or if `unavailable` and model confidence ≥ threshold. A field is **doubtful** if `not_found` (→ `FIELD_NOT_VERIFIED`) or if not verified and model confidence < threshold (→ `LOW_CONFIDENCE_FIELD`). Independent verification overrides the model's own low self-rating.
4. **Clean up & self-check** — normalise dates (many formats → ISO), amounts (₹, Rs., INR, Indian commas, "/-"), invoice numbers (uppercase, remove spaces / `-` / `/` / `_` / `.`, strip leading zeros of numeric part), GSTIN (remove spaces). Checks: document is a tax invoice; required fields present; doubtful critical fields; lines sum to subtotal (± ₹1); subtotal − discount + charges + tax + round-off = total (± ₹1); GST type matches state rule; GST rate valid for invoice date; buyer GSTIN/name matches Zenith.
5. **Vendor & duplicate check** — vendor by GSTIN exact match (a GSTIN that is impossible as read — a digit where the format needs a letter or vice versa — is corrected for look-alikes 0/O, 1/I, 5/S, 8/B, 2/Z, 6/G and used only if its check character then validates), else name fuzzy match (RapidFuzz token_sort_ratio ≥ 90) → flag "matched by name only". Checks: vendor known, approved, not blocked; bank account + IFSC on invoice match vendor master (if printed). Duplicates: same file hash as an approved run (an earlier hold/reject only notes it); same vendor + same normalised invoice number; same vendor + same total + invoice date within ±3 days (possible duplicate).
6. **Find the PO (code, no AI)** — explicit PO reference → exact lookup (normalised). If missing: score each open PO of that vendor: `0.5 × item_similarity + 0.3 × amount_closeness + 0.2 × qty_match`. Best ≥ 0.85 and gap to 2nd ≥ 0.15 → `PO_INFERRED` (Hold with one-click confirm). Best ≥ 0.50 otherwise → `PO_AMBIGUOUS` (Hold, show top 3). Else `PO_NOT_FOUND`. An inferred PO is never auto-approved. Also check PO belongs to this vendor and is not closed.
7. **Match amounts** — map invoice lines to PO lines (fuzzy description + unit price). Checks: item exists on PO; qty billed ≤ remaining qty; unit price variance within tolerance; cumulative billed on PO (from history) + this invoice ≤ PO value + tolerance.
8. **Decision engine (rules)** — collect all check results. Any REJECT-severity code → **Reject**; else any HOLD-severity code → **Hold**; else **Approve** (approve-with-note if INFO codes exist). Always list every reason. Hold → routed question to a role. Reject → draft vendor note. Approve → update PO ledger + add to invoice history.

### ReasonCode enum (severity → routed role)

| Code | Severity | Route / action |
|---|---|---|
| `NOT_A_TAX_INVOICE` | REJECT | Note to sender: document is a quotation/proforma/challan/credit note/PO copy |
| `DUPLICATE_FILE` | REJECT | Same file already **approved and paid** in an earlier run (link to it). An earlier run that only held/rejected it does not count: see `FILE_SEEN_BEFORE` |
| `DUPLICATE_INVOICE_NUMBER` | REJECT | Vendor note: already received/paid (link to original) |
| `GST_TYPE_INVALID` | REJECT | Vendor note: reissue with correct IGST/CGST+SGST |
| `ARITHMETIC_MISMATCH` | REJECT (only if every field involved is **trusted** per Stage 3; otherwise becomes `ARITHMETIC_UNCERTAIN`) | Vendor note: totals don't add up |
| `PO_CLOSED` | REJECT | Vendor note: PO closed/fully billed |
| `ARITHMETIC_UNCERTAIN` | HOLD | AP clerk: verify figures |
| `FIELD_NOT_VERIFIED` | HOLD | AP clerk: "AI read {field} = {value}, but this value could not be found on the document — please confirm" |
| `LOW_CONFIDENCE_FIELD` | HOLD | AP clerk: confirm specific field(s) |
| `POSSIBLE_DUPLICATE` | HOLD | AP clerk: compare with listed invoice |
| `VENDOR_UNKNOWN` | HOLD | Procurement: vendor not in master |
| `VENDOR_NOT_APPROVED` / `VENDOR_BLOCKED` | HOLD | Procurement |
| `VENDOR_MATCHED_BY_NAME_ONLY` | HOLD | AP clerk: GSTIN missing/different |
| `BANK_DETAILS_MISMATCH` | HOLD (fraud flag) | Finance controller: verify via known contact, not invoice contact |
| `BUYER_MISMATCH` | HOLD | AP clerk: invoice not addressed to Zenith |
| `GST_RATE_UNUSUAL` | HOLD | Tax team: rate not valid for date/item |
| `MISSING_REQUIRED_FIELD` | HOLD | AP clerk |
| `PO_NOT_FOUND` / `PO_AMBIGUOUS` / `PO_INFERRED` | HOLD | Buyer: confirm/assign PO |
| `PO_VENDOR_MISMATCH` | HOLD | Buyer |
| `ITEM_NOT_ON_PO` / `QTY_EXCEEDS_PO` | HOLD | Buyer |
| `PRICE_VARIANCE_OVER_TOLERANCE` | HOLD | Buyer: accept or dispute |
| `PO_OVERRUN` | HOLD | Buyer: amend PO or approve remaining balance only |
| `PRICE_VARIANCE_WITHIN_TOLERANCE` | INFO | Approve with note |
| `OCR_UNAVAILABLE` | INFO | Verification skipped; decision relied on model confidence (shown as warning) |
| `FILE_SEEN_BEFORE` | INFO | Same file processed before but not approved (retry / second opinion): judged again on its own, linked to the earlier run |
| `FIELD_CROSS_CHECKED` | INFO | Not found on the page, but confirmed by master data or the page's arithmetic (approve with note) |
| `EXTRACTION_FAILED` | (run status, not a decision) | User: retry with other model |

## 7. Key data shapes

`ExtractedInvoice`: document_type (`tax_invoice | quotation | proforma | credit_note | delivery_challan | purchase_order | other`), vendor_name, vendor_gstin, vendor_address, vendor_state, buyer_name, buyer_gstin, invoice_number, invoice_date, po_reference, line_items[ {description, hsn_sac, quantity, unit, unit_price, amount, tax_rate} ], subtotal, discount, other_charges, cgst, sgst, igst, round_off, total_amount, amount_in_words, bank_account, bank_ifsc, page_count. Every scalar field is `{value, confidence (0–1), evidence (short text from the document or null)}`.

`VerificationResult`: `{engine_used: text_layer|ocr|mixed|unavailable, pages: [{page, source, word_count, mean_ocr_conf}], fields: {field_name: {status, source, page, bbox[x0,y0,x1,y1], matched_text, ocr_word_conf}}, duration_ms}`.

Label file (`labels/<invoice_id>.json`) for generated data: `invoice_id`, `scenario`, `template`, `is_scanned`, `degradations[]`, `ground_truth` (an `ExtractedInvoice`-shaped object of exactly what is printed), `field_boxes` ({field: {page, bbox}} recorded by the renderer for printed key values; for degraded pages transformed with the same rotation/scale, or marked `approximate`), `obscured_fields[]` (fields deliberately smudged/covered), `rules_eval_signals` ({field: {confidence, verification_status}} that the rules evaluation should assume — default `{0.95, verified}`; heavy-scan scenarios set the smudged field to e.g. `{0.40, not_found}`), `expected_decision`, `acceptable_decisions[]`, `expected_reason_codes[]` (must include), `notes`.

DB tables: `vendors`, `po_headers`, `po_lines`, `invoice_history`, `runs` (id, created_at, file_name, file_hash, file_bytes, model, status, decision, total_amount, vendor_id, po_number, duration_ms, extracted_json, verification_json, reasons_json, is_test_run), `run_events`, `hold_actions` (run_id, actor_role, action, comment, created_at), `extraction_cache` (file_hash + model → json), `page_words_cache` (file_hash + page → words json), `batches` (bulk uploads; runs carry `batch_id`), `email_log` (vendor emails, demo: logged not delivered), `app_settings` (AI request gap edited in Settings).
Verification `status` also allows `cross_checked` (Stage 3b).

## 8. Data generation principles (see Phase 2)

- Fixed random seed → fully reproducible.
- **Scenario first:** each invoice comes from a scenario definition that states the mutation and the expected outcome; master data and history are generated *together* with scenarios so every case is consistent (e.g. overrun scenarios have prior partial bills in history; duplicate scenarios have the original in history).
- All vendors, people, logos and brands are fictional. Valid-format, checksum-correct GSTINs; valid-format PAN, IFSC, account numbers.
- Variety designed to transfer to real invoices: ≥ 8 visual layouts, many label synonyms, date/number formats, tax presentations, page counts, and scan degradations.
- The renderer records where key values are printed (`field_boxes`) so verification and highlighting can be tested against ground truth.

## 9. Demo safety

- **Reset demo data:** an admin action restores master data, PO ledger and invoice history to the seeded state and clears runs, batches, hold actions, emails, admin settings and the Test Suite result (a first visit; only the extraction/OCR caches are kept). Approving an invoice records it as **paid** (demo assumption). Required because approving an invoice changes the ledger (re-running the same invoice would correctly be flagged as a duplicate).
- **Test runs are isolated:** the Test Suite runs in a sandbox (`is_test_run=true`, ledger changes rolled back) so it never pollutes demo state.
- **Extraction cache:** keyed by file hash + model. Used by evaluation scripts and the Test Suite to save free-tier quota. **Off by default for live runs**; when used, the UI shows a "cached extraction" badge (never hide it). Verification always runs fresh (it is free and local); page-word results may be cached by file hash.
- **Rate limits:** pace batch runs (configurable delay); on HTTP 429 show "rate limit reached" with the retry/switch option.

## 10. UI requirements (graded)

Clean, professional, light theme, consistent spacing; works at 1366×768 and up. Screens: New Run, Live Run View, Dashboard, Run Detail, Hold Queue, Test Suite & Evaluation, Data (vendors/POs/ledger), Settings (read-only config + Reset demo data). Status colours: green Approve, amber Hold, red Reject, gray running/failed. **Shown to people as "Paid", "Needs human verification" and "Rejected"** (approving pays the invoice in this demo; the codes APPROVE/HOLD/REJECT stay internal). The Hold Queue is shown as the **Verification queue**: one check per invoice (the PO if one is needed, the doubtful values pre-filled to confirm or correct, a required note), then **Verify & pay** or **Reject**; the person's role is the routed role, not chosen by hand. Every decision shows its reasons in plain English, and every number shown links back to where it came from (invoice evidence or PO line).

**Verification in the UI:** on the page viewer, draw a box around each verified value (green = verified, red dashed = AI value not found on the page; hover shows field name and matched text). In the extracted-fields table each field shows a badge: "✓ verified (text layer)", "✓ verified (OCR)", "✗ not found on page", or "— not verified (OCR unavailable)". Clicking a field jumps to its box on the right page.

## 11. Phase report format (print at the end of every phase)

```
PHASE N REPORT
- What I built: …
- Files created/changed: …
- Tests: X passed, Y failed (paste summary)
- How Rutvik can test this manually: numbered steps with exact commands/URLs and expected results
- Known limitations / decisions I made that you should confirm: …
- Ready for Phase N+1? (yes / blocked because …)
```

## 12. Demo mode and real mode (Phase 10–11)

- **Start screen:** "Try demo (no sign-in)" for reviewers, "Real mode" for Rutvik (Gmail sign-in in Phase 11; real mode is then allowed only for `OWNER_EMAIL`).
- **Same app, same rules.** Mode only decides *which database* a request uses (`api/common.engine_of`) and *which AI key*; no check, threshold or decision differs between modes.
- **Demo sandbox:** every demo visitor gets their own SQLite copy of the freshly seeded database (random visitor-id cookie), so reviewers never see each other's runs and "already paid" never leaks between them. Deleted after `DEMO_SANDBOX_TTL_HOURS` (default 24) of inactivity. Reset demo data resets only that visitor's sandbox.
- **Demo inbox:** `data/demo_inbox/inbox.json`, fixed emails from the fictional vendors with the golden invoices attached (plus emails without bills). In demo, invoices come only from these emails: no uploads, no samples, no Test Suite runs.
- **Demo AI:** Gemini only, `DEMO_GEMINI_API_KEY` (a separate Google Cloud project, so its free-tier quota is separate); the visitor picks one of the Gemini models (`DEMO_GEMINI_MODEL` default, `DEMO_GEMINI_MODELS`, default `GEMINI_MODELS`); no Groq and no automatic fallback. At most `DEMO_MAX_RUNS_PER_HOUR` (default 20) runs per visitor. A rate limit is shown as a calm notice ("the AI model has reached its rate limit — please try again after some time").
- `runs.source_json` (nullable) records the email an invoice came from. The vendor email for such a run is a **reply in that thread** (to the sender, `Re: <their subject>`); `email_log.thread_message_id` / `body` keep it, and the Inbox shows it under the original email.
- **Real mode (Phase 11):** "Sign in with Google" (scopes openid, email, gmail.readonly) connects the owner's Gmail and opens real mode. Once `OWNER_EMAIL` is set, real-mode data (the main database, via `engine_of`) needs that account's signed-in session (cookie `ia_owner`, hashed in `owner_sessions`); any other account is turned away and its access revoked. The refresh token is stored encrypted (`gmail_accounts`). The Inbox reads Gmail (bills only by default, Gmail search, paging); chosen attachments run like uploads, with the email as `source_json`. Vendor replies stay in the app (shown in the thread); nothing is ever sent from the owner's Gmail. Sign out / Disconnect (revokes at Google).
- **Running processes** screen: runs and batches still processing (they continue on the server when the user leaves their screen) and those finished in the last 30 minutes.

