"""The owner's Gmail connection and signed-in sessions (real mode), stored in the main database."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.gmail import oauth
from app.models import GmailAccount, OwnerSession

SESSION_DAYS = 30
_access_tokens: dict[str, oauth.Tokens] = {}  # email -> short-lived access token (memory only)
_lock = threading.Lock()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def start_session(engine: Engine, email: str) -> str:
    """A new signed-in session; returns the cookie value (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    with Session(engine) as session:
        session.add(OwnerSession(token_hash=_hash(token), email=email,
                                 expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
        session.commit()
    return token


def session_email(engine: Engine, token: str | None) -> str | None:
    """The email of a valid, unexpired session, else None."""
    if not token:
        return None
    with Session(engine) as session:
        row = session.get(OwnerSession, _hash(token))
        if row is None or _utc(row.expires_at) < datetime.now(timezone.utc):
            return None
        return row.email


def end_session(engine: Engine, token: str | None) -> None:
    if token:
        with Session(engine) as session:
            session.execute(delete(OwnerSession).where(OwnerSession.token_hash == _hash(token)))
            session.commit()


def save_account(engine: Engine, settings: Settings, email: str, tokens: oauth.Tokens) -> None:
    """Store (or replace) the encrypted refresh token of the connected Gmail."""
    with Session(engine) as session:
        session.merge(GmailAccount(email=email, refresh_token_encrypted=oauth.encrypt(settings, tokens.refresh_token or ""),
                                   scopes=tokens.scopes, connected_at=datetime.now(timezone.utc)))
        session.commit()
    with _lock:
        _access_tokens[email] = tokens


def account(engine: Engine, email: str | None) -> GmailAccount | None:
    if not email:
        return None
    with Session(engine) as session:
        row = session.get(GmailAccount, email)
        if row is not None:
            session.expunge(row)
        return row


def access_token(engine: Engine, settings: Settings, email: str) -> str:
    """A valid access token for this Gmail, refreshed with the stored refresh token when needed."""
    with _lock:
        cached = _access_tokens.get(email)
        if cached and cached.expires_at - 60 > time.time():
            return cached.access_token
    row = account(engine, email)
    if row is None:
        raise oauth.OAuthError("Gmail is not connected.")
    tokens = oauth.refresh_access_token(settings, oauth.decrypt(settings, row.refresh_token_encrypted))
    with _lock:
        _access_tokens[email] = tokens
    return tokens.access_token


def disconnect(engine: Engine, settings: Settings, email: str) -> None:
    """Revoke the access at Google, delete the stored token and every session of this owner."""
    row = account(engine, email)
    if row is not None:
        try:
            oauth.revoke(oauth.decrypt(settings, row.refresh_token_encrypted))
        except oauth.OAuthError:
            pass
    with Session(engine) as session:
        session.execute(delete(GmailAccount).where(GmailAccount.email == email))
        session.execute(delete(OwnerSession).where(OwnerSession.email == email))
        session.commit()
    with _lock:
        _access_tokens.pop(email, None)


def connected_email(engine: Engine) -> str | None:
    """The Gmail address connected to this app, if any."""
    with Session(engine) as session:
        return session.scalars(select(GmailAccount.email)).first()
