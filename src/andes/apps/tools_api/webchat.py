"""Identity tokens for the watsonx Orchestrate embedded chat on the landing page.

The instance has embedded-chat security on: the chat only starts with a JWT signed
(RS256) by the key pair whose public half is registered in Orchestrate (Administration >
Settings > Embed Security). GET /webchat/token signs one per visitor with the private
key in WEBCHAT_PRIVATE_KEY (a Render environment variable, never in git).

The visitor is anonymous: `sub` is a random id the page keeps in sessionStorage. Tokens
last ~1 h 56 min (Orchestrate accepts at most 7,100 seconds); a longer visit reloads
the page.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

TOKEN_TTL = timedelta(seconds=7000)  # Orchestrate accepts at most 7,100 s
_USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load_private_key(pem: str) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("WEBCHAT_PRIVATE_KEY must be an RSA private key")
    return key


def anonymous_id(raw: str | None) -> str:
    """The page's own random id if it looks like one, else a fresh one."""
    return raw if raw and _USER_ID.match(raw) else uuid.uuid4().hex


def sign(claims: dict, key: rsa.RSAPrivateKey) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + _b64url(signature)


def visitor_token(user_id: str | None, key: rsa.RSAPrivateKey, now: datetime) -> str:
    issued = int(now.timestamp())
    claims = {
        "sub": anonymous_id(user_id),
        "iat": issued,
        "exp": issued + int(TOKEN_TTL.total_seconds()),
        "context": {"channel": "web", "user_role": "visitor"},
    }
    return sign(claims, key)
