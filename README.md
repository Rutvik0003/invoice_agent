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

### Demo mode and real mode

The first screen offers two ways in:

- **Try demo (no sign-in)**: for reviewers. A sample AP inbox (`data/demo_inbox/inbox.json`) of 15 emails from
  the fictional vendors: the 12 golden invoices (clean approvals and the edge cases) plus emails without bills.
  Tick bills and check them (one = a live run, several = a batch). Each visitor gets a **private sandbox**, a
  copy of the freshly seeded database (cookie `ia_visitor`, files in `backend/demo_sandboxes/`, deleted after
  24 h unused), so approvals and resets never reach anyone else or the real data. The demo uses Gemini only
  with `DEMO_GEMINI_API_KEY` and a choice of Gemini models (no Groq, no automatic fallback), at most 20 runs
  per visitor per hour; when the free tier is exhausted it says so calmly ("the AI model has reached its rate
  limit, please try again after some time") and offers the other Gemini models, which have their own limits.
  "Reply to vendor" on a held/rejected invoice answers in the email thread the invoice came in (shown under that
  email in the Inbox; logged, not delivered).
  Uploads, samples and Test Suite runs are off in the demo, because only the inbox invoices have their vendors
  and POs in the demo data.
- **Real mode**: the full app on the main database (uploads, samples, batches, Test Suite, both models) plus
  your **Gmail inbox**. "Sign in with Google" connects Gmail read-only; with `OWNER_EMAIL` set, only that account
  gets into real mode (anyone else is sent back to the start screen and offered the demo).

**Running** (sidebar, with a live count) lists every invoice and batch still processing; they keep going on the
server when you leave their screen.

Decisions are shown as **Paid** (approved; approving pays the invoice in this demo), **Needs human
verification** (held) and **Rejected**. The **Verification queue** asks one thing per invoice: choose the PO if
one is needed, confirm or correct the values the AI was unsure of, add a note, then **Verify & pay** or **Reject**.

Both modes run exactly the same pipeline and rules; the mode only decides which database and which AI key a
request uses (`app/api/common.engine_of`).

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
same invoice twice is (correctly) rejected as already paid; reset the demo to start over.

- **Approved = paid** (demo assumption): an approved invoice goes into the invoice history as paid, dated today.
- **The same file again:** if an earlier run approved it, the new run is rejected (`DUPLICATE_FILE`, "already
  approved and paid"). If earlier runs only held or rejected it, the new run is a retry or second opinion. It is
  judged on its own, with an INFO note linking the earlier run (`FILE_SEEN_BEFORE`). A person also cannot approve
  a hold whose invoice has been paid since.
- **Reset demo data** is a first visit. Master data, the PO ledger and the history are reseeded. Every run, batch,
  hold action and email is deleted. Admin settings go back to their defaults, and the Test Suite result is
  forgotten. Only the extraction and OCR caches stay; they are invisible and save free-tier quota.

### Working with many invoices

- **Confirmed from our own records (Stage 3b).** OCR sometimes misses a value the AI read correctly. Such a value
  still counts as confirmed, shown as "✓ our records" or "✓ by calculation", when:
  - **Buyer GSTIN:** it equals Zenith's GSTIN (we are the only buyer).
  - **Vendor GSTIN and name:** both belong to the same vendor-master record.
  - **Bank account and PO number:** they are that vendor's account and one of that vendor's POs.
  - **Misread GSTIN:** the AI's GSTIN fails the GSTIN check digit, is at most 2 characters from Zenith's or a
    vendor's GSTIN, and that GSTIN is printed on the page. The page's GSTIN is then the one checked.
  - **Calculation:** a missing amount follows from amounts that *were* found on the page (lines → subtotal,
    CGST = SGST, subtotal + GST → total).

  This works even when OCR is unavailable. AI values that only agree with each other prove nothing, so a
  calculation always needs an anchor found on the page. The invoice number and date cannot be confirmed this way,
  so they still hold. Confirmed values are listed in an INFO note (`FIELD_CROSS_CHECKED`), and the decision may
  then be Approve with that note.
- **Bulk upload.** Drop several files on New Run. They are queued, then processed one at a time in upload order
  by a background worker. The queue lives in the database, so it carries on after a restart. The batch page shows
  progress, every decision and the combined result, and can be downloaded as CSV. The API is `POST /api/batches`.
- **Pause between AI requests** (Settings, default `AI_REQUEST_GAP_S=6`). Every AI request (live runs, batches,
  the Test Suite) starts at least this long after the previous one, so the free-tier per-minute limits are not
  hit.
- **One-tap vendor email** (Hold and Reject). The subject is `<vendor> - <problem> - Invoice <number>`. The body
  gives each problem and the change needed, worded for the vendor (never "possible fraud" or "the AI read"), and
  the invoice file is attached. It is addressed to the vendor's email on file. **Demo:** nothing is delivered;
  the email is logged against the run and the screen shows "Mail sent".
- **Misread GSTINs.** A GSTIN has a fixed shape: state digits, then the PAN (5 letters, 4 digits, 1 letter). A
  digit read where only a letter can be (`33BUZC0...` → `33BUZCO...`), or the reverse, is corrected. The
  corrected GSTIN is used only if its check character then validates, and the vendor check says what was
  corrected. A valid GSTIN is never changed.
- **Compare with PO.** On a held invoice (Hold Queue, or the run view), the invoice and its PO are shown side by
  side, line by line. Each line shows quantity against the open quantity and price against the PO price, with the
  same tolerance as Stage 7, plus the PO balance before and after this invoice. Any other PO of the vendor can be
  picked to compare.
- **Gemini model per run.** New Run offers every model in `GEMINI_MODELS` (default `gemini-2.5-flash`,
  `gemini-3.6-flash`, `gemini-3.8-flash`, all free-tier Flash models). `GEMINI_MODEL` stays the default.

## Connect Gmail (real mode)

One-time setup in Google Cloud (free):

1. <https://console.cloud.google.com/> → create a project (e.g. "Invoice Agent").
2. **APIs & Services → Library** → enable **Gmail API**.
3. **APIs & Services → OAuth consent screen** → External → app name, your email as support and developer
   contact → **Scopes**: add `openid`, `.../auth/userinfo.email`, `.../auth/gmail.readonly` → **Test users**: add
   the Gmail address you will connect. (Leave the app in *Testing*: no Google review is needed for your own
   account; Google shows an "unverified app" notice, click *Continue*. Refresh tokens of apps in Testing expire
   after 7 days, so you may need to sign in again after a week.)
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** → *Web application* →
   **Authorized redirect URIs**: `http://localhost:5173/api/auth/google/callback` (Vite dev server),
   `http://localhost:8000/api/auth/google/callback` (backend / Docker), and later
   `https://<your-render-app>.onrender.com/api/auth/google/callback`.
5. Put the client id and secret in `.env` with your address:

   ```
   GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   OWNER_EMAIL=you@gmail.com
   ```

6. Restart the backend → start screen → **Real mode → Sign in with Google**. The Inbox now lists your emails
   with PDF/PNG/JPG attachments (search box = Gmail search). Tick bills → **Check**. Settings → Gmail →
   *Disconnect* withdraws the access at Google.

The app only reads Gmail (`gmail.readonly`); replies to vendors are kept in the app and shown in the email's
thread, never sent from your account. The refresh token is stored encrypted (`TOKEN_ENCRYPTION_KEY`, or a key
derived from the client secret).

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

### Very poor scans: when neither the AI nor OCR can read a value

On a badly degraded scan, the free-tier models we use can misread a value too badly for anything to recover it.
Example: stress invoice `S0006` is scanned at 100 DPI, blurred, noisy, JPEG quality 47 and rotated 3.6°, with a
stamp and a coffee stain.

- **Groq** (`qwen/qwen3.8-27b`) read the vendor GSTIN as `07ZINCP5001Q1Z4`. The printed GSTIN is
  `07ZHNCP5749Q1ZA`, so 5 of 15 characters are wrong. Groq only sees a page image reduced to 1400 px, because of
  its free-tier token limit.
- **Tesseract** found no text on the page that looks like a GSTIN.
- **The rules** can prove the AI's value is wrong (it fails the GSTIN check digit), but not what it should be. The
  misread rule accepts at most 2 differing characters; more would risk matching the wrong vendor.

The invoice is therefore held, with `VENDOR_MATCHED_BY_NAME_ONLY` (the name matched, the GSTIN did not). This is
the intended outcome: when unsure, hold. A larger vision model, or Gemini reading the PDF at full resolution, may
read such a scan better; that is a model limit, not a rule we can safely loosen. In practice the fix is a clearer
copy of the invoice, which is what the vendor email for this hold asks for.

### OCR verification recall on scanned invoices: 91.6% (target 95%)

Stage 3 checks every value the AI read against the page itself. On digital PDFs it reads the exact text layer:
**100% of printed values are found**. On scans and photos it uses Tesseract OCR, and on our mild scans
(150–200 DPI, slight blur, noise and JPEG artefacts) it finds **91.6%** of the printed key values
(721/787, `data/eval_reports/verification_eval_all_*.md`), below the 95% target.

What this means in practice:

- **It never causes a wrong approval.** A value that OCR cannot confirm is reported "not found on page", and the
  invoice goes to **Hold** for a person to check. Fault injection confirms the other direction: 1371/1371 wrong
  values were rejected (100% catch rate).
- The cost is extra Holds on scanned invoices whose values are actually correct.

What we tried (details in the Phase 3 report): deskew, denoising and 200/300/400 DPI made no real difference
(77–79% on a sample); recognising a misread ₹ ("₹13,266" read as "213,266") and combining four OCR passes
(normal and sharpened image × two page-layout modes) raised it to 89.8%. A fifth pass on a locally thresholded
image, which reads faded or unevenly lit print, raised it to 91.6% (Phase 8). Remaining misses are genuine Tesseract
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

### OCR speed and memory on small machines (Render free: 0.1 CPU, 512 MB)

**Accuracy comes first: every machine runs all five OCR passes.** The adaptive-threshold pass is skipped only when
its black-and-white image is more than 10% ink, which means it is mostly noise.
- The app reads its container's CPU and memory limits and decides how many passes run at the same time: one at
  a time on a fraction of a CPU, at most two at once in 512 MB.
- The time limit per pass stretches on slow CPUs (20 s on a full CPU, 200 s at 0.1 CPU), so OCR is not abandoned
  just because the machine is slow.
- If one pass fails, the words from the others are kept.
- Small photos and web images are enlarged to 3000 px before OCR. On four real uploads this confirmed 20 values
  instead of 15.

Measured on the whole server in the Docker image, with the pipeline running on a scan:

| Machine | Passes at once | 1-page mild scan (PNG) | Heavy 300-DPI scanned PDF | Peak memory |
|---|---:|---:|---:|---:|
| 4 CPUs, 512 MB | 2 | 5.5 s, 11/11 fields verified | 15.5 s | 372 MB |
| 0.1 CPU, 512 MB (Render free) | 1 | 77 s, 11/11 fields verified | 256 s | 301 MB |

- **Same accuracy everywhere.** Only the time differs. The 8 s target for scans is not met on the free
  instance; we chose accuracy over speed there.
- **Memory limit:** running all passes at once would need about 466 MB plus the server, too close to 512 MB.
  That is why passes are limited by memory.
- **Digital PDFs are unaffected.** They are verified from the text layer in well under a second, and a typical
  digital invoice runs end to end in about 14 s on Gemini (13 s of that is the model call).
- **Lowering the DPI doesn't help.** Photos are images, so the DPI setting doesn't apply to them. On our heavy
  scan, 200 DPI found 198 words instead of 542.
- **For a snappy live demo with scans,** run locally or in Docker on a laptop.

### Results on data the pipeline was never tuned on

Verification only (no AI): the true printed values are looked up on the page. Wrong values must never pass.

| Set | Values found on the page | Wrong values accepted |
|---|---:|---:|
| Held-out invoices (3 new layouts), digital PDF | 103/103 (100%) | 0 of 210 |
| Held-out, phone photos (tilt, glare, shadow) | 112/115 (97.4%) | |
| Held-out, low-res web images (700–1000 px) | 103/104 (99.0%) | |
| Held-out, mild scans | 103/110 (93.6%) | |
| Real receipt photos, CORD v2 (`fetch_cord.py`) | 18/33 | 0 of 38 |

The real receipts are hard: faded thermal print, creases, and photos as small as 432×648 px. Seven of their
values use the Indonesian `60.000` (sixty thousand) format, which an INR-only system reads as 60.00 and so does
not find. All held-out decisions match their scenario (42/42, `eval_rules.py --set holdout`).

### Groq free tier

Groq's free tier for `qwen/qwen3.8-27b` (its only image model on this account) allows about 1,000 output and
7,000 input tokens per minute. So Groq returns compact output (evidence only for the 12 key fields), handles
roughly one invoice per minute, and **cannot read multi-page invoices** (the run fails with a clear error and a
one-click retry with Gemini). A paid Groq tier raises these limits; Gemini, the default model, has no such problem.

## Layout

See `CLAUDE.md` §3. `backend/` (FastAPI), `frontend/` (React + Vite + Tailwind + shadcn/ui), `datagen/` (synthetic
data), `data/` (master data, invoices, eval reports), `Dockerfile` + `render.yaml` (deployment).
