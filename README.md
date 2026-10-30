# Invoice Agent

Takes a vendor invoice (PDF or image) and produces a reasoned **Approve / Hold / Reject** decision, with every step visible.
AI only reads the invoice; plain Python code makes every decision. (Zamp ASA case study, PS-1.)

> Status: Phase 0 — skeleton. Business logic arrives in later phases (see `PHASE_PROMPTS.md`).

## Local setup

Prerequisites: Python 3.11+, Node.js 20+.

```bash
# 1. Python virtualenv + dependencies
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
python tasks.py install          # backend + frontend deps

# 2. Secrets
cp .env.example .env             # then paste your Gemini and Groq API keys into .env

# 3. Run
python tasks.py dev              # backend :8000 + frontend :5173
```

Open http://localhost:5173 — the page shows backend status and which models are configured.

| Task | Command | `make` equivalent |
|---|---|---|
| Dev servers | `python tasks.py dev` | `make dev` |
| Tests | `python tasks.py test` | `make test` |
| Build frontend | `python tasks.py build` | `make build` |

Windows has no `make` by default, so `tasks.py` is the cross-platform entry point; the `Makefile` just calls it.

## Production

`render.yaml` defines one Render web service: the build installs Python deps and builds the frontend into
`frontend/dist`; FastAPI serves the API under `/api` and the frontend at `/` (unknown non-API routes fall back
to `index.html`). Set the secret env vars (`GEMINI_API_KEY`, `GROQ_API_KEY`, model names, `DATABASE_URL`) in the
Render dashboard. Health check: `/api/health`.

## Layout

See `CLAUDE.md` §3. `backend/` (FastAPI), `frontend/` (React + Vite + Tailwind + shadcn/ui), `datagen/` (synthetic
data), `data/` (master data, invoices, eval reports).
