"""Start screen: choose demo mode (no sign-in, own sandbox) or real mode (CLAUDE.md §12)."""

from __future__ import annotations

import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import Engine

from app.api.common import engine_of
from app.config import get_settings
from app.demo.mode import (MODE_COOKIE, VISITOR_COOKIE, cookie_secure, current_mode, is_demo, real_mode_allowed, real_mode_locked,
                           runs_last_hour, signed_in_owner, visitor_id)
from app.gmail import accounts
from app.runtime_settings import effective_settings

router = APIRouter(prefix="/api", tags=["mode"])
COOKIE_DAYS = 30


class ModeChoice(BaseModel):
    mode: Literal["demo", "real"]


def _mode_dict(mode: str | None, demo_engine: Engine | None) -> dict:
    out: dict = {"mode": mode}
    if demo_engine is not None:
        settings = effective_settings(demo_engine)
        base = get_settings()
        out["demo"] = {"model_name": settings.gemini_model, "uses_demo_key": bool(base.demo_gemini_api_key.strip()),
                       "key_configured": settings.gemini_configured,
                       "max_runs_per_hour": settings.demo_max_runs_per_hour,
                       "runs_last_hour": runs_last_hour(demo_engine),
                       "sandbox_hours": settings.demo_sandbox_ttl_hours}
    return out


def _auth_dict(request: Request) -> dict:
    """What the start screen and the sidebar need to know about real mode's sign-in (never a token)."""
    engine = request.app.state.engine
    owner = signed_in_owner(request)
    gmail = owner or (None if real_mode_locked() else accounts.connected_email(engine))
    return {"google_configured": get_settings().google_configured, "locked": real_mode_locked(),
            "signed_in_as": owner, "gmail": gmail if gmail and accounts.account(engine, gmail) else None,
            "sign_in_url": "/api/auth/google/start"}


@router.get("/mode")
def get_mode(request: Request) -> dict:
    """The current mode (None = show the start screen) and the real-mode sign-in state."""
    return {**_mode_dict(current_mode(request), engine_of(request) if is_demo(request) else None),
            "auth": _auth_dict(request)}


@router.post("/mode")
def choose_mode(body: ModeChoice, request: Request, response: Response) -> dict:
    """Remember the choice in a cookie. Demo mode also gets a visitor id (their own sandbox), kept on later visits
    so a reviewer who comes back finds their runs again."""
    long = COOKIE_DAYS * 24 * 3600
    if body.mode == "real" and not real_mode_allowed(request):
        raise HTTPException(status_code=401, detail={"type": "sign_in_required", "sign_in_url": "/api/auth/google/start",
                                                     "message": "Real mode is only for the owner: sign in with Google."})
    response.set_cookie(MODE_COOKIE, body.mode, max_age=long, httponly=True, samesite="lax",
                        secure=cookie_secure(request))
    sandbox = None
    if body.mode == "demo":
        vid = visitor_id(request) or secrets.token_urlsafe(18)
        response.set_cookie(VISITOR_COOKIE, vid, max_age=long, httponly=True, samesite="lax",
                        secure=cookie_secure(request))
        sandbox = request.app.state.sandboxes.engine_for(vid)  # created now: the first screen opens without a wait
    return {**_mode_dict(body.mode, sandbox), "auth": _auth_dict(request)}


@router.delete("/mode")
def leave_mode(response: Response) -> dict:
    """Back to the start screen (a demo sandbox is kept until it expires)."""
    response.delete_cookie(MODE_COOKIE)
    return {"mode": None}
