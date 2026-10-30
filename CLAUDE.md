# CLAUDE.md — Invoice Decision Agent (Zamp ASA Case Study, PS-1)

> Put this file in the root of the repository. Claude Code reads it automatically at the start of every session.
> Owner: Rutvik Kachhadiya. Build is done phase by phase from `PHASE_PROMPTS.md`.

---

## 1. What we are building

A web app that takes a vendor invoice (PDF or image) and produces a clear, reasoned **Approve / Hold / Reject** decision, with every step visible.

- **Input:** an invoice PDF/image uploaded by the user (simulates an AP email inbox).
- **Processing:** 7 stages. AI only reads the invoice; plain Python code makes every decision.
- **Output:** a decision card with plain-English reasons, a full audit trail, a routed question (Hold) or a draft vendor note (Reject), and an update to the PO ledger (Approve).
- **UI:** a live run view (each stage lights up as it runs) and a dashboard (history, status, outputs across runs). The UI is graded.
- **Audience:** Zamp interviewers (AI finance-ops company). It must run live, reliably, during an interview.

## 2. Non-negotiable rules for Claude Code

1. **Work on one phase at a time.** Only do what the current phase prompt asks. When the phase is done, stop and print the "Phase report" (see §11). Never start the next phase on your own.
2. **AI reads, code decides.** The LLM is used only in Stage 2 (extraction). Vendor matching, duplicate detection, PO matching, maths, tax checks and the final decision are deterministic Python. Never ask an LLM to make or explain a decision.
3. **Never invent data.** If a field is not on the invoice, extraction returns `null`. Never fill gaps with guesses or defaults.
4. **When unsure → Hold.** Code must never auto-approve something it is not sure about (e.g. inferred PO, low-confidence total).
5. **Never fake tests.** Do not change expected outcomes, labels or thresholds just to make a test pass. If a test fails, fix the logic or stop and explain the conflict to me.
6. **Expected outcomes are defined by the scenario, never by running the engine.** The data generator writes expected decisions from the scenario definition (§8). It must never import or call the decision engine.
7. **No secrets in code or git.** API keys come only from environment variables. Keep `.env` in `.gitignore`; maintain `.env.example` with placeholder values.
8. **No mock paths in production code.** Fakes/stubs are allowed only inside `tests/`.
9. **Every reason has a code.** All check results use the fixed `ReasonCode` enum (§6) with a severity and a plain-English message template.
10. **Small, typed, tested.** Python 3.11+, type hints everywhere, Pydantic models at every boundary, pure functions for checks, `pytest` tests for every module. Run the full test suite before declaring a phase done.
11. **Explainable code.** Clear names, short functions, a docstring on every check explaining the business rule in one sentence. I must be able to explain any line in an interview.
12. **Ask before adding dependencies** not listed in §4, and before changing anything in §5–§7.
13. **Commit at the end of each phase** with message `Phase N: <summary>` (only after tests pass).

## 3. Repository layout

```
invoice-agent/
├── CLAUDE.md
├── PHASE_PROMPTS.md
├── README.md
├── .env.example
├── render.yaml                    # deployment config (Phase 9)
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app; also serves frontend/dist
│   │   ├── config.py              # settings from env (pydantic-settings)
│   │   ├── db.py, models.py       # SQLAlchemy engine + tables
│   │   ├── schemas.py             # Pydantic models (ExtractedInvoice, CheckResult, Decision, RunEvent…)
│   │   ├── extraction/            # base.py, gemini.py, groq.py, prompt.py, cache.py, pdf_utils.py
│   │   ├── pipeline/              # intake, normalise, self_check, vendor_check, duplicate_check,
│   │   │                          # po_match, amount_match, decision, reason_codes, orchestrator
│   │   └── api/                   # runs.py, data.py, holds.py, eval.py, admin.py
│   ├── scripts/                   # seed_db.py, extract_one.py, run_pipeline.py, eval_rules.py, eval_extraction.py
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
| PDF handling | PyMuPDF (`pymupdf`) — text-layer detection, page → PNG rendering |
| Fuzzy matching | RapidFuzz |
| Live updates | Server-Sent Events (`sse-starlette`) |
| Data generation | ReportLab (PDFs), Pillow + NumPy (scan degradation), Faker (`en_IN` locale) |
| Tests | pytest |
| Frontend | React + Vite + TypeScript + Tailwind + shadcn/ui + lucide-react icons + TanStack Query |
| Hosting | Render (single web service: FastAPI serves API + built frontend) |

## 5. Business context and configuration

- **Buyer company:** Zenith Retail Pvt Ltd, Maharashtra (GST state code `27`). Buyer GSTIN in `data/master/buyer.json`.
- **Currency:** INR only. **One invoice per file.** (Documented assumptions.)
- **GST slabs (GST 2.0, effective 22 Sep 2025):** valid rates are 0%, 5%, 18%, 40% (plus special 3% and 0.25% for precious metals/stones). Invoices dated before 22 Sep 2025 may legitimately show 12% or 28%.
- **GST type rule:** vendor state (first 2 digits of vendor GSTIN) == buyer state → CGST + SGST, each = half the rate. Different state → IGST at the full rate.
- **Config (env vars with defaults, shown in a Settings panel):**
  - `TOLERANCE_PCT=1.0` and `TOLERANCE_ABS_INR=500` → a variance is acceptable if ≤ min(1% of value, ₹500)
  - `CONFIDENCE_THRESHOLD=0.80` → any critical field below this is "low confidence"
  - `PO_INFER_MIN_SCORE=0.85`, `PO_INFER_MIN_GAP=0.15`, `PO_INFER_FLOOR=0.50`
  - `POSSIBLE_DUP_DAYS=3`
  - `DEFAULT_MODEL=gemini`
- **Critical fields:** vendor_gstin, vendor_name, invoice_number, invoice_date, total_amount, line items.

## 6. The 7-stage pipeline

Each stage emits `RunEvent`s (`stage_started`, `check_result`, `stage_completed`, `stage_failed`) that are saved to the DB and streamed over SSE.

1. **Intake** — accept PDF/PNG/JPG; reject other types, empty or password-protected files with a clear error; compute SHA-256; detect text-layer vs scanned (PyMuPDF); render page images for the UI; create a `Run` record with the chosen model.
2. **Read & extract (AI — exactly one model call per invoice)** — returns `ExtractedInvoice` (see §7) with per-field confidence and a short `evidence` text snippet for key fields. Validate with Pydantic; on invalid JSON, one repair retry; on failure, stop the run with `EXTRACTION_FAILED` and a typed reason (`rate_limited`, `timeout`, `invalid_response`, `provider_error`, `auth_error`). The user can retry with the other model in one click (no silent auto-switch). Gemini receives the PDF directly; Groq receives page PNGs (max 5 pages).
3. **Clean up & self-check** — normalise dates (many formats → ISO), amounts (₹, Rs., INR, Indian commas, "/-"), invoice numbers (uppercase, remove spaces / `-` / `/` / `_` / `.`, strip leading zeros of numeric part), GSTIN (remove spaces). Checks: document is a tax invoice; required fields present; lines sum to subtotal (± ₹1); subtotal − discount + charges + tax + round-off = total (± ₹1); GST type matches state rule; GST rate valid for invoice date; buyer GSTIN/name matches Zenith.
4. **Vendor & duplicate check** — vendor by GSTIN exact match, else name fuzzy match (RapidFuzz token_sort_ratio ≥ 90) → flag "matched by name only". Checks: vendor known, approved, not blocked; bank account + IFSC on invoice match vendor master (if printed). Duplicates: same file hash; same vendor + same normalised invoice number; same vendor + same total + invoice date within ±3 days (possible duplicate).
5. **Find the PO (code, no AI)** — explicit PO reference → exact lookup (normalised). If missing: score each open PO of that vendor: `0.5 × item_similarity + 0.3 × amount_closeness + 0.2 × qty_match`. Best ≥ 0.85 and gap to 2nd ≥ 0.15 → `PO_INFERRED` (Hold with one-click confirm). Best ≥ 0.50 otherwise → `PO_AMBIGUOUS` (Hold, show top 3). Else `PO_NOT_FOUND`. An inferred PO is never auto-approved. Also check PO belongs to this vendor and is not closed.
6. **Match amounts** — map invoice lines to PO lines (fuzzy description + unit price). Checks: item exists on PO; qty billed ≤ remaining qty; unit price variance within tolerance; cumulative billed on PO (from history) + this invoice ≤ PO value + tolerance.
7. **Decision engine (rules)** — collect all check results. Any REJECT-severity code → **Reject**; else any HOLD-severity code → **Hold**; else **Approve** (approve-with-note if INFO codes exist). Always list every reason. Hold → routed question to a role. Reject → draft vendor note. Approve → update PO ledger + add to invoice history.

### ReasonCode enum (severity → routed role)

| Code | Severity | Route / action |
|---|---|---|
| `NOT_A_TAX_INVOICE` | REJECT | Note to sender: document is a quotation/proforma/challan/credit note/PO copy |
| `DUPLICATE_FILE` | REJECT | Already processed (link to original run) |
| `DUPLICATE_INVOICE_NUMBER` | REJECT | Vendor note: already received/paid (link to original) |
| `GST_TYPE_INVALID` | REJECT | Vendor note: reissue with correct IGST/CGST+SGST |
| `ARITHMETIC_MISMATCH` | REJECT (only if all involved fields have confidence ≥ threshold; otherwise becomes `ARITHMETIC_UNCERTAIN`) | Vendor note: totals don't add up |
| `PO_CLOSED` | REJECT | Vendor note: PO closed/fully billed |
| `ARITHMETIC_UNCERTAIN` | HOLD | AP clerk: verify figures |
| `POSSIBLE_DUPLICATE` | HOLD | AP clerk: compare with listed invoice |
| `VENDOR_UNKNOWN` | HOLD | Procurement: vendor not in master |
| `VENDOR_NOT_APPROVED` / `VENDOR_BLOCKED` | HOLD | Procurement |
| `VENDOR_MATCHED_BY_NAME_ONLY` | HOLD | AP clerk: GSTIN missing/different |
| `BANK_DETAILS_MISMATCH` | HOLD (fraud flag) | Finance controller: verify via known contact, not invoice contact |
| `BUYER_MISMATCH` | HOLD | AP clerk: invoice not addressed to Zenith |
| `GST_RATE_UNUSUAL` | HOLD | Tax team: rate not valid for date/item |
| `MISSING_REQUIRED_FIELD` | HOLD | AP clerk |
| `LOW_CONFIDENCE_FIELD` | HOLD | AP clerk: confirm specific field(s) |
| `PO_NOT_FOUND` / `PO_AMBIGUOUS` / `PO_INFERRED` | HOLD | Buyer: confirm/assign PO |
| `PO_VENDOR_MISMATCH` | HOLD | Buyer |
| `ITEM_NOT_ON_PO` / `QTY_EXCEEDS_PO` | HOLD | Buyer |
| `PRICE_VARIANCE_OVER_TOLERANCE` | HOLD | Buyer: accept or dispute |
| `PO_OVERRUN` | HOLD | Buyer: amend PO or approve remaining balance only |
| `PRICE_VARIANCE_WITHIN_TOLERANCE` | INFO | Approve with note |
| `EXTRACTION_FAILED` | (run status, not a decision) | User: retry with other model |

## 7. Key data shapes

`ExtractedInvoice`: document_type (`tax_invoice | quotation | proforma | credit_note | delivery_challan | purchase_order | other`), vendor_name, vendor_gstin, vendor_address, vendor_state, buyer_name, buyer_gstin, invoice_number, invoice_date, po_reference, line_items[ {description, hsn_sac, quantity, unit, unit_price, amount, tax_rate} ], subtotal, discount, other_charges, cgst, sgst, igst, round_off, total_amount, amount_in_words, bank_account, bank_ifsc, page_count. Every scalar field is `{value, confidence (0–1), evidence (short text from the document or null)}`.

Label file (`labels/<invoice_id>.json`) for generated data: `invoice_id`, `scenario`, `template`, `is_scanned`, `degradations[]`, `ground_truth` (an `ExtractedInvoice`-shaped object of exactly what is printed), `expected_decision`, `acceptable_decisions[]` (e.g. heavy-scan cases accept Hold for low confidence OR the underlying correct decision), `expected_reason_codes[]` (must include), `notes`.

DB tables: `vendors`, `po_headers`, `po_lines`, `invoice_history`, `runs` (id, created_at, file_name, file_hash, file_bytes, model, status, decision, total_amount, vendor_id, po_number, duration_ms, extracted_json, reasons_json, is_test_run), `run_events`, `hold_actions` (run_id, actor_role, action, comment, created_at), `extraction_cache` (file_hash + model → json).

## 8. Data generation principles (see Phase 2)

- Fixed random seed → fully reproducible.
- **Scenario first:** each invoice comes from a scenario definition that states the mutation and the expected outcome; master data and history are generated *together* with scenarios so every case is consistent (e.g. overrun scenarios have prior partial bills in history; duplicate scenarios have the original in history).
- All vendors, people, logos and brands are fictional. Valid-format, checksum-correct GSTINs; valid-format PAN, IFSC, account numbers.
- Variety designed to transfer to real invoices: ≥ 8 visual layouts, many label synonyms, date/number formats, tax presentations, page counts, and scan degradations (§ Phase 2).

## 9. Demo safety

- **Reset demo data:** an admin action restores master data, PO ledger and invoice history to the seeded state and clears runs. Required because approving an invoice changes the ledger (re-running the same invoice would correctly be flagged as a duplicate).
- **Test runs are isolated:** the Test Suite runs in a sandbox (`is_test_run=true`, ledger changes rolled back) so it never pollutes demo state.
- **Extraction cache:** keyed by file hash + model. Used by evaluation scripts and the Test Suite to save free-tier quota. **Off by default for live runs**; when used, the UI shows a "cached extraction" badge (never hide it).
- **Rate limits:** pace batch runs (configurable delay); on HTTP 429 show "rate limit reached" with the retry/switch option.

## 10. UI requirements (graded)

Clean, professional, light theme, consistent spacing; works at 1366×768 and up. Screens: New Run, Live Run View, Dashboard, Run Detail, Hold Queue, Test Suite & Evaluation, Data (vendors/POs/ledger), Settings (read-only config + Reset demo data). Status colours: green Approve, amber Hold, red Reject, gray running/failed. Every decision shows its reasons in plain English, and every number shown links back to where it came from (invoice evidence or PO line).

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
