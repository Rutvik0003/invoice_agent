"""Which mode a request is in (CLAUDE.md §12): 'demo' (a visitor's sandbox) or 'real' (the main database).

The mode and the visitor id are cookies. A request without a mode cookie (scripts, tests, the API docs) is in
real mode, exactly as before demo mode existed. Once OWNER_EMAIL is set, real mode is only for that Google account,
signed in (cookie ia_owner = a session in the main database); everyone else can use the demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException, Request
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.demo.sandbox import VISITOR_ID, SandboxPool
from app.gmail import accounts
from app.models import Run

MODE_COOKIE = "ia_mode"
VISITOR_COOKIE = "ia_visitor"
OWNER_COOKIE = "ia_owner"
Mode = Literal["demo", "real"]


def cookie_secure(request: Request) -> bool:
    """Cookies carry the Secure flag on HTTPS (also behind a proxy such as Render's, which says so in
    X-Forwarded-Proto), so they are never sent over plain HTTP; local http://localhost keeps working."""
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def current_mode(request: Request) -> Mode | None:
    """The mode chosen on the start screen, or None when nothing was chosen yet (or demo without a valid visitor)."""
    mode = request.cookies.get(MODE_COOKIE)
    if mode == "demo" and visitor_id(request) is None:
        return None
    if mode == "real" and not real_mode_allowed(request):
        return None
    return mode if mode in ("demo", "real") else None


def real_mode_locked() -> bool:
    """Real mode is owner-only once OWNER_EMAIL is set (local development without Google stays open)."""
    return bool(get_settings().owner_email.strip())


def signed_in_owner(request: Request) -> str | None:
    """The owner's email when this browser is signed in as the owner, else None."""
    email = accounts.session_email(request.app.state.engine, request.cookies.get(OWNER_COOKIE))
    return email if email and email == get_settings().owner_email.strip().lower() else None


def real_mode_allowed(request: Request) -> bool:
    return not real_mode_locked() or signed_in_owner(request) is not None


def require_owner(request: Request) -> None:
    """Real-mode data (the main database) needs the signed-in owner once real mode is locked."""
    if not real_mode_allowed(request):
        raise HTTPException(status_code=401, detail={"type": "sign_in_required",
                            "message": "Real mode is only for the owner. Sign in with Google, or try the demo."})


def visitor_id(request: Request) -> str | None:
    value = request.cookies.get(VISITOR_COOKIE)
    return value if value and VISITOR_ID.match(value) else None


def is_demo(request: Request) -> bool:
    return current_mode(request) == "demo"


def demo_engine(request: Request) -> Engine | None:
    """The visitor's sandbox database in demo mode, else None (real mode uses the main database)."""
    if not is_demo(request):
        return None
    pool: SandboxPool = request.app.state.sandboxes
    return pool.engine_for(visitor_id(request))


def require_real_mode(request: Request, what: str) -> None:
    """Refuse an action the demo does not offer (the demo only processes the invoices of its own inbox)."""
    if is_demo(request):
        raise HTTPException(status_code=403, detail={"type": "demo_restricted", "message": f"{what} is not available "
                            "in the demo. The demo processes the invoices in its inbox (their vendors and POs are in "
                            "the demo data)."})


def runs_last_hour(engine: Engine) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(Run).where(Run.created_at >= since)) or 0


def check_demo_quota(request: Request, engine: Engine, new_runs: int, limit: int) -> None:
    """A demo visitor may start at most `limit` runs per hour (protects the demo AI key's free-tier quota)."""
    if not is_demo(request):
        return
    used = runs_last_hour(engine)
    if used + new_runs > limit:
        raise HTTPException(status_code=429, detail={
            "type": "demo_limit",
            "message": f"The demo allows {limit} invoice runs per hour and {used} were used. "
                       "Please try again after some time."})
