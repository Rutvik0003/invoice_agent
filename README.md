# Invoice Agent

Takes a vendor invoice (PDF or image) and produces a reasoned **Approve / Hold / Reject** decision, with every step visible.
**AI reads, OCR verifies, code decides:** an AI model reads the invoice, an independent PDF-text-layer / Tesseract OCR
check confirms what it read, and plain Python rules make every decision. (Zamp ASA case study, PS-1.)

> Status: Phase 0.5 — skeleton with Docker + Tesseract. Business logic arrives in later phases (see `PHASE_PROMPTS.md`).

## Local setup

Prerequisites: Python 3.11+, Node.js 20+, Tesseract OCR.

### 1. Install Tesseract

| OS | Command |
|---|---|
| Windows | [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) — tick "Add to PATH" (or set `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`). Open a new terminal afterwards. |
| macOS | `brew install tesseract` |
| Linux | `sudo apt install tesseract-ocr tesseract-ocr-eng` |

Check with `tesseract --version`. If Tesseract is missing the app still runs; the status page shows
"OCR unavailable — not verified".

### 2. Install and run

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
python tasks.py install          # backend + frontend deps
cp .env.example .env             # then paste your Gemini and Groq API keys into .env
python tasks.py dev              # backend :8000 + frontend :5173
```

Open http://localhost:5173 — the page shows backend status, which models are configured, and the OCR version.

| Task | Command | `make` equivalent |
|---|---|---|
| Dev servers | `python tasks.py dev` | `make dev` |
| Tests | `python tasks.py test` | `make test` |
| Build frontend | `python tasks.py build` | `make build` |
| Build Docker image | `python tasks.py docker-build` | `make docker-build` |
| Run Docker image | `python tasks.py docker-run` | `make docker-run` |

Windows has no `make` by default, so `tasks.py` is the cross-platform entry point; the `Makefile` just calls it.

### Demo data

All companies, people and numbers are fictional and fully reproducible (fixed seed, fixed reference date 30 Oct 2026).

```bash
python -m datagen.generate_all                 # master data + 12 golden + ~270 stress invoices with labels (~4 min)
python -m datagen.generate_all --master-only   # only data/master/*.csv + buyer.json (same CSVs, no files)
python -m datagen.validate_master              # 13 consistency checks (GSTIN checksums, PO ledger vs history, ...)
python backend/scripts/seed_db.py              # loads data/master into the DB (safe to re-run)
```

Generated invoices live in `data/invoices/golden/` and `data/invoices/stress/`, each with a `labels/` folder
(ground truth exactly as printed, where each key value sits on the page, and the expected decision).
`data/invoices/generation_report.md` summarises the sets; `contact_sheet_*.png` and `box_check_*.png` are for
eyeballing variety and box placement. The generator uses standard Windows fonts (Arial, Calibri, Segoe UI,
Georgia, Ink Free ...) for the ₹ glyph; the generated files are committed, so other machines don't need them.

The SQLite file lives at `backend/local.db` whichever folder you run from.

### Reading and verifying one invoice

```bash
python backend/scripts/extract_one.py data/invoices/golden/01_happy_clean.pdf --model gemini   # what the AI read
python backend/scripts/verify_one.py data/invoices/golden/01_happy_clean.pdf --model groq       # + checked on the page
python backend/scripts/eval_verification.py --set all          # no AI: recall, box IoU, fault-injection catch rate
python backend/scripts/eval_extraction.py --set golden --model both   # AI accuracy vs labels (paced for free tiers)
```

Results are cached by file hash + model in the local database, so re-running a script doesn't spend API quota
(`--no-cache` forces a fresh call). Reports go to `data/eval_reports/`.

### Running the full pipeline

```bash
python backend/scripts/run_pipeline.py 01_happy_clean --model gemini    # all 8 stages, live, in colour
python backend/scripts/eval_rules.py --set all                          # stages 4-8 on every labelled invoice
```

The API (`python tasks.py dev`, then http://localhost:8000/docs) exposes runs with a live event stream
(`GET /api/runs/{id}/events`, Server-Sent Events), the hold queue, master data, stats, the sandboxed golden
Test Suite and `POST /api/admin/reset-demo`. Approving an invoice really updates the PO ledger, so running the
same invoice twice is (correctly) rejected as a duplicate; reset the demo to start over.

## Docker

The `Dockerfile` is multi-stage: a Node image builds `frontend/dist`, then a `python:3.11-slim` image with
`tesseract-ocr` + `tesseract-ocr-eng` installs the backend and runs uvicorn on `$PORT` (default 8000) as a non-root user.

```bash
docker build -t invoice-agent .
docker run --rm -p 8000:8000 --env-file .env -e TESSERACT_CMD= invoice-agent
```

Then open http://localhost:8000 (FastAPI serves both the API and the built frontend). `TESSERACT_CMD=` clears any
Windows path from your `.env`; inside the image Tesseract is on PATH.

## Deploy to Render (Docker runtime)

`render.yaml` defines one Docker web service with health check `/api/health`.

1. Push the repo to GitHub.
2. In Render: **New → Blueprint**, pick the repo (it reads `render.yaml`). An existing native-Python service can't
   switch runtime in place — create the new service from the Blueprint and delete the old one.
3. Set the env vars marked `sync: false` in the dashboard: at least `GEMINI_API_KEY`, `GROQ_API_KEY`,
   `GEMINI_MODEL`, `GROQ_MODEL` (and `DATABASE_URL` from Phase 9). Leave the business-rule ones empty to use defaults.
4. Deploy, then open the service URL: the status page should show OCR available.

The free instance sleeps when idle; the first request after a while takes ~1 minute.

## Known limitations

### OCR verification recall on scanned invoices: 89.8% (target 95%)

Stage 3 checks every value the AI read against the page itself. On digital PDFs it reads the exact text layer:
**100% of printed values are found**. On scans and photos it uses Tesseract OCR, and on our mild scans
(150–200 DPI, slight blur, noise and JPEG artefacts) it finds **89.8%** of the printed key values
(707/787, `data/eval_reports/verification_eval_all_minconf40_*.md`), below the 95% target.

What this means in practice:

- **It never causes a wrong approval.** A value that OCR cannot confirm is reported "not found on page", and the
  invoice goes to **Hold** for a person to check. Fault injection confirms the other direction: 1371/1371 wrong
  values were rejected (100% catch rate).
- The cost is extra Holds on scanned invoices whose values are actually correct.

What we tried (details in the Phase 3 report): deskew, denoising and 200/300/400 DPI made no real difference
(77–79% on a sample); recognising a misread ₹ ("₹13,266" read as "213,266") and combining four OCR passes
(normal and sharpened image × two page-layout modes) raised it to 89.8%. Remaining misses are genuine Tesseract
misreads of small or bold fonts, e.g. "PO-2026-1188" read as "PO-2026-1108".

`OCR_MIN_WORD_CONF` stays at **40**. At 0, recall rises to 91.9%, but one deliberately wrong value was accepted
(99.93% catch rate). We prefer never accepting a wrong value over fewer Holds.

### Would a paid service fix it?

**A better OCR engine likely would; a better (paid) LLM would not.**

- **Paid AI models don't fix the verifier.** Verification must stay *independent* of the model that read the
  invoice: that independence is how it catches a model's confident misreads. Using a stronger LLM for both reading
  and checking would mean the AI checking its own work. A stronger extraction model does make the *values* more
  accurate (Gemini 2.5 Flash already scores 96.8% on the golden set), so there is less to catch, but the verifier's
  recall on scans is limited by OCR, not by the LLM.
- **A commercial OCR / document-AI service** (for example Google Cloud Vision or Document AI, AWS Textract, or
  Azure AI Document Intelligence) is built for exactly this: noisy, low-resolution scans and small fonts. It
  returns the same thing Tesseract does (words + boxes + confidence), so it could replace `verification/ocr.py`
  without changing the rest of Stage 3, and it would still be independent of the extraction model. We have not
  measured it here, so the improvement is expected, not proven: run `eval_verification.py` to compare before
  switching. These services are paid per page after a small free allowance, and they send invoice images to a
  third party, which needs a data-handling review in a real AP setting.

### OCR speed on Render's free instance (0.1 CPU, 512 MB)

Measured in the Docker image with `--cpus` and `--memory` limits (Phase 8):

| Machine | OCR passes | 1-page mild scan | Heavy 300-DPI scanned PDF | Peak memory |
|---|---:|---:|---:|---:|
| Dev laptop (16 cores) | 4 | 5–6 s | 5.5 s | 466 MB (container) |
| 0.5 CPU (Render Starter) | 2 | - | over 20 s → timeout | 313 MB |
| 0.1 CPU (Render free) | 1 | 13.5–22 s | ~31 s, 3 words read | 172–233 MB |

- **Digital PDFs are unaffected.** They are verified from the text layer in well under a second, and a typical
  digital invoice runs end to end in about 14 s on Gemini (13 s of that is the model call).
- **Scans on the free instance don't meet the 8 s target.**
  - The app counts its CPU quota and runs fewer OCR passes on small machines. Four parallel passes would also need
    about 466 MB, too close to the 512 MB limit.
  - Even one pass takes about 14–22 s on 0.1 CPU. A page that takes over 20 s is not checked: the run continues
    with the "OCR unavailable" warning and holds anything the model is unsure of (rule 14).
- **Lowering the DPI doesn't help.** Photos are images, so the DPI setting doesn't apply to them. On our
  heavy scan, 200 DPI found 198 words instead of 542.
- **For a live demo with scans, run locally or in Docker on a laptop**, or use a larger instance (2+ CPUs runs all
  four passes).

### Groq free tier

Groq's free tier for `qwen/qwen3.8-27b` (its only image model on this account) allows about 1,000 output and
7,000 input tokens per minute. So Groq returns compact output (evidence only for the 12 key fields), handles
roughly one invoice per minute, and **cannot read multi-page invoices** (the run fails with a clear error and a
one-click retry with Gemini). A paid Groq tier raises these limits; Gemini, the default model, has no such problem.

## Layout

See `CLAUDE.md` §3. `backend/` (FastAPI), `frontend/` (React + Vite + Tailwind + shadcn/ui), `datagen/` (synthetic
data), `data/` (master data, invoices, eval reports), `Dockerfile` + `render.yaml` (deployment).
