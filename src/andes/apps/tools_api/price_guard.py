"""Output guardrail for the supervisor: no price reaches the traveler unless it was quoted.

watsonx Orchestrate calls POST /plugins/price_guard after the agent writes its answer
and before the traveler sees it (an `agent_post_invoke` plug-in). Every amount in the
answer must be an amount of a stored quote (total, line or unit price) or appear in the
tool calls of this run; otherwise the answer is replaced with SAFE_MESSAGE.

Everything here is pure: the route in main.py loads the quoted amounts and logs only the
payload's structure (keys and sizes), never the conversation.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

MIN_AMOUNT = 50_000  # below this a number is not a package price (days, minutes, people)
SAFE_MESSAGE = (
    "Para darte un precio exacto necesito generar una cotización. ¿Me confirmas el destino, "
    "las fechas y cuántas personas viajan en total?"
)

_SEP = r"[.\s  ,]"
_GROUPED = re.compile(rf"(?<![\d\-])\d{{1,3}}(?:{_SEP}\d{{3}})+(?![\d\-])")
_MILLIONS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:millones|millón|mill[oó]n|M\b)", re.I)
_PLAIN_MONEY = re.compile(
    r"(?:\$\s?|\bCOP\s?|\bUSD\s?)(\d{5,})\b|\b(\d{5,})\s?(?:COP|pesos|USD|d[oó]lares)\b", re.I
)


def amounts_in(text: str) -> set[int]:
    """Money amounts written in Spanish/Colombian styles: 5.600.000, 5 600 000, $5600000,
    5,6 millones. Dates (2027-02-08), ids and phone numbers do not count."""
    found: set[int] = set()
    for m in _GROUPED.finditer(text):
        found.add(int(re.sub(r"\D", "", m[0])))
    for m in _MILLIONS.finditer(text):
        found.add(round(float(m[1].replace(",", ".")) * 1_000_000))
    for m in _PLAIN_MONEY.finditer(text):
        found.add(int(m[1] or m[2]))
    return {a for a in found if a >= MIN_AMOUNT}


def numbers_in(node: Any) -> set[int]:
    """Every integer (or integer-looking text) inside tool calls, at any depth."""
    out: set[int] = set()
    if isinstance(node, bool):
        return out
    if isinstance(node, int):
        out.add(node)
    elif isinstance(node, float) and node.is_integer():
        out.add(int(node))
    elif isinstance(node, str):
        stripped = node.strip()
        if stripped[:1] in "{[":
            try:
                return numbers_in(json.loads(stripped))
            except ValueError:
                pass
        out |= amounts_in(node)
        out |= {int(n) for n in re.findall(r"\b\d{5,}\b", node)}
    elif isinstance(node, dict):
        for v in node.values():
            out |= numbers_in(v)
    elif isinstance(node, list):
        for v in node:
            out |= numbers_in(v)
    return {n for n in out if n >= MIN_AMOUNT}


def _texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return [content["text"]]
    if isinstance(content, list):
        return [t for c in content for t in _texts(c)]
    return []


def answer_text(payload: dict[str, Any]) -> str:
    """The assistant text the traveler is about to see (all assistant messages)."""
    messages = payload.get("messages") or []
    return "\n".join(
        t
        for m in messages
        if isinstance(m, dict) and m.get("role", "assistant") == "assistant"
        for t in _texts(m.get("content"))
    )


def shape(node: Any, depth: int = 0) -> Any:
    """Structure of the payload for the logs: keys, types and sizes; no values."""
    if depth > 6:
        return "…"
    if isinstance(node, dict):
        return {k: shape(v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [shape(node[0], depth + 1), f"len={len(node)}"] if node else []
    if isinstance(node, str):
        return f"str[{len(node)}]"
    return type(node).__name__


def unbacked(payload: dict[str, Any], quoted: set[int]) -> set[int]:
    """Amounts in the answer that no stored quote and no tool call of this run backs."""
    shown = amounts_in(answer_text(payload))
    if not shown:
        return set()
    return shown - quoted - numbers_in(payload.get("tool_calls"))


def replace_answer(payload: dict[str, Any], text: str = SAFE_MESSAGE) -> dict[str, Any]:
    """Same payload with the answer replaced: the first assistant message carries `text`,
    later assistant messages are dropped (they may repeat the price)."""
    out = copy.deepcopy(payload)
    kept, replaced = [], False
    for m in out.get("messages") or []:
        if not isinstance(m, dict) or m.get("role", "assistant") != "assistant":
            kept.append(m)
        elif not replaced:
            content = m.get("content")
            if isinstance(content, dict):
                content["text"] = text
            else:
                m["content"] = {"type": "text", "text": text}
            kept.append(m)
            replaced = True
    out["messages"] = kept
    return out
