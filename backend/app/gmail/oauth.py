"""Google sign-in (OAuth 2.0) for real mode: one consent gives the owner's email address and read-only Gmail access.

Plain HTTPS calls to Google's documented endpoints (httpx). The refresh token is encrypted (Fernet) before it is
stored; the key comes from the environment. Nothing here decides anything about invoices.
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = ("openid", "email", GMAIL_READONLY)
TIMEOUT_S = 20


class OAuthError(Exception):
    """Sign-in or token refresh failed; the message is safe to show (never contains a token)."""


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scopes: str


def authorization_url(settings: Settings, redirect_uri: str, state: str) -> str:
    """Google's consent page: email + read-only Gmail, offline access (a refresh token), always asking again so a
    re-connect gets a fresh refresh token."""
    query = {"client_id": settings.google_client_id, "redirect_uri": redirect_uri, "response_type": "code",
             "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": state,
             "include_granted_scopes": "true"}
    return f"{AUTH_URL}?{urlencode(query)}"


def _token_request(data: dict) -> Tokens:
    try:
        response = httpx.post(TOKEN_URL, data=data, timeout=TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise OAuthError(f"Could not reach Google ({type(exc).__name__}).") from exc
    if response.status_code != 200:
        error = response.json().get("error", "") if response.headers.get("content-type", "").startswith("application/json") else ""
        if error == "invalid_grant":
            raise OAuthError("Google no longer accepts the stored Gmail access (expired or revoked). Connect Gmail again.")
        raise OAuthError(f"Google refused the request ({response.status_code} {error}).")
    body = response.json()
    return Tokens(body["access_token"], body.get("refresh_token"), time.time() + int(body.get("expires_in", 3600)),
                  body.get("scope", ""))


def exchange_code(settings: Settings, code: str, redirect_uri: str) -> Tokens:
    """The one-time code from the consent page -> access + refresh token."""
    return _token_request({"code": code, "client_id": settings.google_client_id,
                           "client_secret": settings.google_client_secret, "redirect_uri": redirect_uri,
                           "grant_type": "authorization_code"})


def refresh_access_token(settings: Settings, refresh_token: str) -> Tokens:
    return _token_request({"refresh_token": refresh_token, "client_id": settings.google_client_id,
                           "client_secret": settings.google_client_secret, "grant_type": "refresh_token"})


def signed_in_email(access_token: str) -> str:
    """The Google account that signed in (only a verified address counts)."""
    try:
        response = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise OAuthError(f"Could not reach Google ({type(exc).__name__}).") from exc
    body = response.json() if response.status_code == 200 else {}
    if not body.get("email") or not body.get("email_verified"):
        raise OAuthError("Google did not confirm a verified email address for this account.")
    return str(body["email"]).lower()


def revoke(token: str) -> None:
    """Withdraw the app's Gmail access at Google (best effort: the stored token is deleted anyway)."""
    try:
        httpx.post(REVOKE_URL, data={"token": token}, timeout=TIMEOUT_S)
    except httpx.HTTPError:
        pass


def _fernet(settings: Settings) -> Fernet:
    """TOKEN_ENCRYPTION_KEY, or a key derived from the client secret (also a secret that lives only in the env)."""
    if settings.token_encryption_key.strip():
        return Fernet(settings.token_encryption_key.strip().encode())
    digest = hashlib.sha256(("invoice-agent:" + settings.google_client_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(settings: Settings, value: str) -> str:
    return _fernet(settings).encrypt(value.encode()).decode()


def decrypt(settings: Settings, value: str) -> str:
    try:
        return _fernet(settings).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise OAuthError("The stored Gmail access cannot be read (the encryption key changed). Connect Gmail again.") from exc
