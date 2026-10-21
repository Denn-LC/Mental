"""Sign in with Google: the OAuth 2.0 authorization code flow with PKCE, standard library only.

The browser goes to Google, Google sends it back with a one-time code, and the server trades that
code (with the PKCE verifier and the client secret) for an ID token directly with Google over
HTTPS. A token received that way needs no signature check (OpenID Connect Core 3.1.3.7), but its
claims are checked: issuer, audience, expiry and subject. Only the `openid` scope is asked for, so
Google tells us nothing but a stable account id (`sub`).
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class SignInFailed(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    base_url: str
    client_id: str | None
    client_secret: str | None

    @property
    def enabled(self):
        return bool(self.client_id and self.client_secret)

    @property
    def secure(self):
        return self.base_url.startswith("https://")

    @property
    def redirect_uri(self):
        return f"{self.base_url}/auth/callback"


def settings():
    """Read from the environment each time, so tests and hosting can set it."""
    return Settings(
        base_url=os.environ.get("MENTAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        client_id=os.environ.get("MENTAL_GOOGLE_CLIENT_ID") or None,
        client_secret=os.environ.get("MENTAL_GOOGLE_CLIENT_SECRET") or None,
    )


def new_state():
    return secrets.token_urlsafe(32)


def new_verifier():
    return secrets.token_urlsafe(64)  # 86 characters; PKCE allows 43-128


def sign_in_url(settings, state, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })


def post_form(url, fields):
    """POST a form over HTTPS (certificates checked by default) and return the JSON reply."""
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def google_account(settings, code, verifier):
    """Trade the one-time code for the Google account id (`sub`). SignInFailed if anything is off."""
    try:
        reply = post_form(TOKEN_URL, {
            "code": code,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "redirect_uri": settings.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        })
        payload = reply["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (OSError, ValueError, LookupError, TypeError, AttributeError) as error:
        raise SignInFailed(f"unusable reply from Google ({error!r})") from None
    if not isinstance(claims, dict):
        raise SignInFailed("unusable reply from Google")
    if claims.get("iss") not in ISSUERS:
        raise SignInFailed("not issued by Google")
    if claims.get("aud") != settings.client_id:
        raise SignInFailed("issued for another app")
    expires = claims.get("exp")
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or expires <= time.time():
        raise SignInFailed("expired")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not 0 < len(sub) <= 255:
        raise SignInFailed("no account id")
    return sub
