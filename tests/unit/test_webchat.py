"""Embedded-chat tokens: RS256 JWTs signed with the key registered in Orchestrate."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from andes.apps.tools_api import webchat
from andes.apps.tools_api.main import create_app
from andes.apps.tools_api.repository import MemoryRepository

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()


def _decode(token: str) -> tuple[dict, dict]:
    head, body, sig = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    KEY.public_key().verify(
        base64.urlsafe_b64decode(pad(sig)),
        f"{head}.{body}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )  # raises if the signature is wrong
    return (
        json.loads(base64.urlsafe_b64decode(pad(head))),
        json.loads(base64.urlsafe_b64decode(pad(body))),
    )


def test_token_is_rs256_and_short_lived() -> None:
    header, claims = _decode(webchat.visitor_token("abc123", KEY, NOW))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert claims["sub"] == "abc123"
    assert claims["exp"] - claims["iat"] == 7000 <= 7100


def test_odd_user_ids_get_a_fresh_one() -> None:
    _, claims = _decode(webchat.visitor_token("<script>", KEY, NOW))
    assert claims["sub"] != "<script>" and len(claims["sub"]) == 32


def _client(pem: str = PEM) -> TestClient:
    app = create_app(repo=MemoryRepository(), api_key="k", clock=lambda: NOW, webchat_key=pem)
    return TestClient(app)


def test_route_needs_no_api_key_and_allows_only_the_landing_origin() -> None:
    c = _client()
    r = c.get(
        "/webchat/token",
        params={"user_id": "u1"},
        headers={"Origin": "https://andes-travel-poc.pages.dev"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://andes-travel-poc.pages.dev"
    assert _decode(r.text)[1]["sub"] == "u1"
    onrender = c.get("/webchat/token", headers={"Origin": "https://andes-travel-poc.onrender.com"})
    assert "access-control-allow-origin" not in onrender.headers
    other = c.get("/webchat/token", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_route_without_key_is_503_and_not_a_tool() -> None:
    c = _client(pem="")
    assert c.get("/webchat/token").status_code == 503
    assert "/webchat/token" not in c.get("/openapi.json").json()["paths"]
