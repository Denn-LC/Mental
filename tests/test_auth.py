import base64
import hashlib
import http.client
import io
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from fake_google import FakeGoogle, b64json, good_claims
from mental.web import auth

SETTINGS = auth.Settings(base_url="http://testserver", client_id="test-client", client_secret="test-secret")


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(auth, "post_form", fake)
    return fake


def test_settings_defaults(monkeypatch):
    for name in ["MENTAL_BASE_URL", "MENTAL_GOOGLE_CLIENT_ID", "MENTAL_GOOGLE_CLIENT_SECRET"]:
        monkeypatch.delenv(name, raising=False)
    settings = auth.settings()
    assert settings.base_url == "http://127.0.0.1:8000"
    assert settings.redirect_uri == "http://127.0.0.1:8000/auth/callback"
    assert not settings.enabled
    assert not settings.secure


def test_settings_from_the_environment(monkeypatch):
    monkeypatch.setenv("MENTAL_BASE_URL", "https://mental.example/")
    monkeypatch.setenv("MENTAL_GOOGLE_CLIENT_ID", "abc")
    monkeypatch.setenv("MENTAL_GOOGLE_CLIENT_SECRET", "xyz")
    settings = auth.settings()
    assert settings.enabled
    assert settings.secure
    assert settings.redirect_uri == "https://mental.example/auth/callback"


def test_sign_in_url_asks_google_for_a_code_with_pkce():
    url = urlparse(auth.sign_in_url(SETTINGS, "the-state", "the-verifier"))
    query = {key: values[0] for key, values in parse_qs(url.query).items()}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(b"the-verifier").digest()).rstrip(b"=").decode()
    assert f"{url.scheme}://{url.netloc}{url.path}" == auth.AUTH_URL
    assert query == {
        "client_id": "test-client", "redirect_uri": "http://testserver/auth/callback",
        "response_type": "code", "scope": "openid", "state": "the-state",
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
    }


def test_states_and_verifiers_are_random_and_the_right_length():
    assert len({auth.new_state() for _ in range(50)}) == 50
    assert 43 <= len(auth.new_verifier()) <= 128  # PKCE's allowed range


def test_a_good_reply_gives_the_google_account(google):
    google.codes["code-1"] = good_claims("google-123")
    assert auth.google_account(SETTINGS, "code-1", "the-verifier") == "google-123"
    assert google.posts == [(auth.TOKEN_URL, {
        "code": "code-1", "client_id": "test-client", "client_secret": "test-secret",
        "redirect_uri": "http://testserver/auth/callback", "grant_type": "authorization_code",
        "code_verifier": "the-verifier",
    })]


@pytest.mark.parametrize("change", [
    {"iss": "https://elsewhere.example"}, {"aud": "another-app"}, {"exp": 1},
    {"sub": ""}, {"sub": 123}, {"sub": "x" * 256},
    {"exp": None}, {"exp": True}, {"exp": float("nan")}, {"exp": float("inf")}, {"aud": ["test-client"]},
], ids=["issuer", "audience", "expired", "empty-sub", "number-sub", "long-sub",
        "no-exp", "bool-exp", "nan-exp", "inf-exp", "list-aud"])
def test_claims_that_dont_check_out_are_refused(google, change):
    google.codes["code-1"] = {**good_claims("google-123"), **change}
    google.codes["code-1"] = {k: v for k, v in google.codes["code-1"].items() if v is not None}
    with pytest.raises(auth.SignInFailed):
        auth.google_account(SETTINGS, "code-1", "v")


@pytest.mark.parametrize("reply", [
    {}, {"id_token": "no-dots"}, {"id_token": "a.%%%.c"}, {"id_token": f"a.{b64json([1, 2])}.c"}, ["a", "list"],
], ids=["no-token", "no-dots", "bad-base64", "not-an-object", "not-a-dict"])
def test_unusable_replies_are_refused(monkeypatch, reply):
    monkeypatch.setattr(auth, "post_form", lambda url, fields: reply)
    with pytest.raises(auth.SignInFailed):
        auth.google_account(SETTINGS, "code", "v")


def test_a_code_google_refuses_is_refused(google):
    with pytest.raises(auth.SignInFailed):
        auth.google_account(SETTINGS, "unknown-code", "v")


def test_the_alternative_issuer_is_accepted(google):
    google.codes["code-1"] = {**good_claims("google-123"), "iss": "accounts.google.com"}
    assert auth.google_account(SETTINGS, "code-1", "v") == "google-123"


@pytest.mark.parametrize("failure", [
    TimeoutError("timed out"), http.client.IncompleteRead(b"par"), RecursionError(),
], ids=["timeout", "incomplete-read", "recursion"])
def test_network_trouble_is_a_failed_sign_in(monkeypatch, failure):
    def broken(url, fields):
        raise failure
    monkeypatch.setattr(auth, "post_form", broken)
    with pytest.raises(auth.SignInFailed):
        auth.google_account(SETTINGS, "code", "v")


def test_googles_error_is_in_the_message(monkeypatch):
    body = io.BytesIO(b'{"error": "invalid_grant", "error_description": "Bad Request code"}')

    def refused(url, fields):
        raise urllib.error.HTTPError(url, 400, "Bad Request", None, body)
    monkeypatch.setattr(auth, "post_form", refused)
    with pytest.raises(auth.SignInFailed, match="invalid_grant.*Bad Request code"):
        auth.google_account(SETTINGS, "code", "v")


@pytest.mark.parametrize("body", [b"not json", b"[1]", b'{"error": 5}', b""])
def test_an_unreadable_error_body_still_fails_cleanly(monkeypatch, body):
    def refused(url, fields):
        raise urllib.error.HTTPError(url, 400, "bad", None, io.BytesIO(body))
    monkeypatch.setattr(auth, "post_form", refused)
    with pytest.raises(auth.SignInFailed):
        auth.google_account(SETTINGS, "code", "v")
