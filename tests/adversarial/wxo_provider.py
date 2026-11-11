"""promptfoo provider: one attack = one new conversation with the Andes supervisor (draft).

Every case first identifies itself as its own test traveler (test+adv-<case>@andes.test),
as a real traveler would, and then sends the attack. Multi-turn uses the thread id that
the chat completions API returns (X-IBM-THREAD-ID). Needs WXO_API_KEY in the environment.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
IAM_URL = "https://iam.cloud.ibm.com/identity/token"
_token: dict[str, Any] = {}


def _instance_url() -> str:
    return yaml.safe_load((ROOT / "orchestrate" / "environment.yaml").read_text())["url"]


def _bearer() -> str:
    if _token.get("exp", 0) - 60 > time.time():
        return _token["value"]
    r = httpx.post(
        IAM_URL,
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": os.environ["WXO_API_KEY"],
        },
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    _token.update(value=body["access_token"], exp=body["expiration"])
    return _token["value"]


def _send(agent_id: str, text: str, thread: str | None) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {_bearer()}"}
    if thread:
        headers["X-IBM-THREAD-ID"] = thread
    r = httpx.post(
        f"{_instance_url()}/v1/orchestrate/{agent_id}/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": text}], "stream": False},
        timeout=180,
    )
    r.raise_for_status()
    body = r.json()
    return body["choices"][0]["message"]["content"], body["thread_id"]


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    config = options.get("config", {})
    case = context["vars"].get("case", "x")
    # setup is one string with turns separated by "||" (a list var would multiply the test)
    raw = context["vars"].get("setup") or f"Hola || test+adv-{case}@andes.test"
    setup = [turn.strip() for turn in raw.split("||") if turn.strip()]
    try:
        thread = None
        for turn in setup:
            _, thread = _send(config["agent_id"], turn, thread)
        answer, _ = _send(config["agent_id"], prompt, thread)
    except Exception as exc:  # surfaced as a promptfoo error, not a pass
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"output": answer}
