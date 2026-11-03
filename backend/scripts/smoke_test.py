"""Smoke test a running instance (local, Docker or the live Render URL) the way a reviewer would use it.

    python backend/scripts/smoke_test.py https://invoice-agent-9ukc.onrender.com
    python backend/scripts/smoke_test.py http://localhost:8000 --no-ai      # skip the two AI calls

Checks: health (models + OCR), real mode locked to the owner, the demo opens a private sandbox with the sample
inbox, golden 01 from the inbox is Paid with its total verified on the page, the blurry scan 08 is checked with
OCR, and resetting the sandbox clears it. Uses at most two AI requests. Exit code 0 = everything passed.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

RESULTS: list[tuple[str, bool, str]] = []
SKIPPED: list[str] = []
WAKE_TIMEOUT_S = 120  # a free Render instance sleeps when idle and takes up to a minute to wake
RUN_TIMEOUT_S = 420  # OCR of a scan on Render free (0.1 CPU) takes minutes


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}", flush=True)
    return ok


def rate_limited(run: dict) -> bool:
    """The AI provider refused for quota or load (free tier): not a fault of the deployment."""
    error = run.get("error") or {}
    return run.get("status") == "extraction_failed" and (error.get("type") == "rate_limited"
                                                       or "busy" in (error.get("message") or ""))


def skip(name: str, why: str) -> None:
    SKIPPED.append(name)
    print(f"  SKIP  {name}  ({why})", flush=True)


def wake(client: httpx.Client) -> dict | None:
    """/api/health, waiting for a sleeping instance to wake up."""
    deadline = time.monotonic() + WAKE_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            response = client.get("/api/health", timeout=30)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        print("  ...waiting for the server to wake up", flush=True)
        time.sleep(5)
    return None


def run_inbox_attachment(client: httpx.Client, file_name: str, model_name: str | None) -> dict | None:
    """Start a run from the demo inbox attachment with this file name and wait until it finishes."""
    inbox = client.get("/api/inbox").json()
    found = next(((m, a) for m in inbox["messages"] for a in m["attachments"] if a["file_name"] == file_name), None)
    if found is None:
        return None
    message, attachment = found
    started = client.post("/api/inbox/run", json={"items": [{"message_id": message["id"], "attachment_id": attachment["id"]}],
                                                      "model_name": model_name})
    if started.status_code != 200:
        return {"status": f"refused {started.status_code}", "detail": started.text[:200]}
    run_id = started.json()["run_id"]
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            run = client.get(f"/api/runs/{run_id}").json()
        except httpx.TimeoutException:  # a small instance busy with OCR answers slowly: keep waiting
            continue
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(3)
    return {"status": "timed out", "id": run_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base_url", help="e.g. https://invoice-agent-9ukc.onrender.com or http://localhost:8000")
    parser.add_argument("--no-ai", action="store_true", help="skip the checks that call the AI model")
    parser.add_argument("--model", help="Gemini model for the AI checks (default: the server's), e.g. gemini-3.6-flash")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60, follow_redirects=False)

    print(f"Smoke test of {args.base_url}")
    health = wake(client)
    if not check("health answers", health is not None):
        return 1
    check("Gemini configured", health["models_configured"]["gemini"])
    check("OCR available", health["ocr"]["available"], health["ocr"].get("version") or "")

    auth = client.get("/api/mode").json()["auth"]
    check("Google sign-in configured", auth["google_configured"])
    check("real mode locked to the owner", auth["locked"])
    if auth["locked"]:
        check("real-mode data refused without sign-in", client.get("/api/runs").status_code == 401)

    chosen = client.post("/api/mode", json={"mode": "demo"})
    check("demo opens without sign-in", chosen.status_code == 200 and chosen.json()["mode"] == "demo")
    inbox = client.get("/api/inbox").json()
    bills = sum(len(m["attachments"]) for m in inbox["messages"])
    check("demo inbox has the sample emails", inbox["source"] == "demo" and bills == 12,
          f"{len(inbox['messages'])} emails, {bills} bills")
    upload = {"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}
    check("uploads are off in the demo", client.post("/api/runs", files=upload).status_code == 403)

    if not args.no_ai:
        happy = run_inbox_attachment(client, "01_happy_clean.pdf", args.model) or {}
        if rate_limited(happy):
            skip("golden 01 is Paid", "AI rate limit / busy model: try again later or with --model")
        else:
            total = ((happy.get("verification") or {}).get("fields") or {}).get("total_amount", {})
            check("golden 01 is Paid", happy.get("decision") == "APPROVE", f"{happy.get('status')}, {happy.get('decision')}")
            check("its total is verified on the page", total.get("status") == "verified", total.get("source") or "")
        scan = run_inbox_attachment(client, "08_F_blurry_scan.pdf", args.model) or {}
        if rate_limited(scan):
            skip("blurry scan 08 is checked with OCR", "AI rate limit / busy model: try again later or with --model")
        else:
            sources = {f.get("source") for f in ((scan.get("verification") or {}).get("fields") or {}).values()}
            check("blurry scan 08 is checked with OCR", "ocr" in sources, f"{scan.get('status')}, {scan.get('decision')}")
            check("and needs human verification", scan.get("decision") == "HOLD")

    reset = client.post("/api/admin/reset-demo")
    check("reset clears the demo sandbox", reset.status_code == 200 and client.get("/api/runs").json()["total"] == 0)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed" + (f"; failed: {', '.join(failed)}" if failed else "")
          + (f"; skipped (AI limits): {', '.join(SKIPPED)}" if SKIPPED else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
