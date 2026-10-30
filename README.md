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
python -m datagen.generate_all --master-only   # writes data/master/*.csv + buyer.json
python -m datagen.validate_master              # 13 consistency checks (GSTIN checksums, PO ledger vs history, ...)
python backend/scripts/seed_db.py              # loads data/master into the DB (safe to re-run)
```

The SQLite file lives at `backend/local.db` whichever folder you run from.

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

## Layout

See `CLAUDE.md` §3. `backend/` (FastAPI), `frontend/` (React + Vite + Tailwind + shadcn/ui), `datagen/` (synthetic
data), `data/` (master data, invoices, eval reports), `Dockerfile` + `render.yaml` (deployment).
