"""A stand-in for Google's token endpoint, so sign-in is tested without a network or an account."""
import base64
import json
import time
import urllib.error


def b64json(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def id_token(**claims):
    """An ID token shaped like Google's: header.payload.signature (the app never checks the signature)."""
    return f"{b64json({'alg': 'RS256'})}.{b64json(claims)}.signature"


def good_claims(sub, client_id="test-client"):
    return {"iss": "https://accounts.google.com", "aud": client_id, "exp": time.time() + 600, "sub": sub}


class FakeGoogle:
    """Replaces auth.post_form. A code put in `codes` is traded once for an ID token with its claims."""

    def __init__(self):
        self.codes = {}
        self.posts = []

    def __call__(self, url, fields):
        self.posts.append((url, fields))
        if fields.get("code") not in self.codes:
            raise urllib.error.HTTPError(url, 400, "invalid_grant", None, None)
        return {"id_token": id_token(**self.codes.pop(fields["code"]))}
