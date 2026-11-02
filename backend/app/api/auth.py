"""Real-mode sign-in: "Sign in with Google" connects the owner's Gmail (read-only) and opens real mode.

Only OWNER_EMAIL may sign in (when it is set). Another account is turned away and its access is revoked at once,
so its token is never stored. Sign out ends this browser's session; Disconnect also withdraws the Gmail access.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.demo.mode import MODE_COOKIE, OWNER_COOKIE, cookie_secure, real_mode_locked, signed_in_owner
from app.gmail import accounts, oauth
from app.logging_setup import get_logger

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = get_logger("auth")
STATE_COOKIE = "ia_oauth_state"
COOKIE_DAYS = 30


def redirect_uri(request: Request) -> str:
    """Where Google sends the browser back: GOOGLE_REDIRECT_URI, else this server's own callback address."""
    configured = get_settings().google_redirect_uri.strip()
    return configured or str(request.url_for("google_callback"))


def _back_to_start(error: str) -> RedirectResponse:
    response = RedirectResponse(f"/?auth_error={error}", status_code=303)
    response.delete_cookie(STATE_COOKIE)
    return response


@router.get("/google/start")
def google_start(request: Request) -> RedirectResponse:
    """Send the browser to Google's consent page (a random state guards against forged callbacks)."""
    settings = get_settings()
    if not settings.google_configured:
        raise HTTPException(status_code=409, detail="Google sign-in is not configured (GOOGLE_CLIENT_ID / SECRET).")
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(oauth.authorization_url(settings, redirect_uri(request), state), status_code=303)
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax",
                        secure=cookie_secure(request))
    return response


@router.get("/google/callback", name="google_callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None,
                    error: str | None = None) -> RedirectResponse:
    """Google's answer: check the state, get the tokens, check it is the owner, store the Gmail access, sign in."""
    settings = get_settings()
    if error:
        return _back_to_start("cancelled")
    expected = request.cookies.get(STATE_COOKIE)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return _back_to_start("invalid_state")
    try:
        tokens = oauth.exchange_code(settings, code, redirect_uri(request))
        email = oauth.signed_in_email(tokens.access_token)
    except oauth.OAuthError:
        logger.exception("google sign-in failed")
        return _back_to_start("google")
    owner = settings.owner_email.strip().lower()
    if owner and email != owner:
        oauth.revoke(tokens.refresh_token or tokens.access_token)
        logger.warning("sign-in refused: not the owner", extra={"signed_in_as": email, "owner_email": owner})
        return _back_to_start("not_owner")
    if oauth.GMAIL_READONLY not in tokens.scopes.split() or not tokens.refresh_token:
        oauth.revoke(tokens.refresh_token or tokens.access_token)
        return _back_to_start("no_gmail")
    engine = request.app.state.engine
    accounts.save_account(engine, settings, email, tokens)
    request.app.state.gmail_clients.pop(email, None)
    response = RedirectResponse("/inbox", status_code=303)
    long = COOKIE_DAYS * 24 * 3600
    response.set_cookie(OWNER_COOKIE, accounts.start_session(engine, email), max_age=long, httponly=True, samesite="lax",
                        secure=cookie_secure(request))
    response.set_cookie(MODE_COOKIE, "real", max_age=long, httponly=True, samesite="lax",
                        secure=cookie_secure(request))
    response.delete_cookie(STATE_COOKIE)
    logger.info("owner signed in, Gmail connected")
    return response


def _signed_out(response: Response) -> None:
    response.delete_cookie(OWNER_COOKIE)
    response.delete_cookie(MODE_COOKIE)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    """End this browser's session (the Gmail connection stays for the next sign-in)."""
    accounts.end_session(request.app.state.engine, request.cookies.get(OWNER_COOKIE))
    _signed_out(response)
    return {"mode": None}


@router.post("/disconnect")
def disconnect(request: Request, response: Response) -> dict:
    """Withdraw the app's Gmail access at Google and forget it (and every session of the owner)."""
    email = signed_in_owner(request)
    if email is None and real_mode_locked():
        raise HTTPException(status_code=401, detail="Sign in as the owner first.")
    engine = request.app.state.engine
    email = email or accounts.connected_email(engine)
    if email:
        accounts.disconnect(engine, get_settings(), email)
        request.app.state.gmail_clients.pop(email, None)
    _signed_out(response)
    return {"mode": None, "disconnected": email}
