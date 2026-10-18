"""Lightweight profile extraction from free text.

Keeps a deterministic, dependency-free extractor (destinations, party size,
budget, interests). An LLM extractor can replace it behind the same interface.
"""

from __future__ import annotations

import re

from andes.core.seed import CATALOG

_DESTINATIONS = {p["destination"].lower(): p["destination"] for p in CATALOG}
_INTERESTS = {
    "playa": "playa",
    "familia": "familia",
    "familiar": "familia",
    "aventura": "aventura",
    "montaña": "montaña",
    "montana": "montaña",
    "ecoturismo": "ecoturismo",
    "naturaleza": "naturaleza",
    "cultural": "cultural",
    "cultura": "cultural",
    "buceo": "buceo",
}

_PARTY_RE = re.compile(r"(\d{1,2})\s*(personas|viajeros|adultos|niños|integrantes)")
_BUDGET_UNIT_RE = re.compile(r"(\d[\d.,]*)\s*(millones|millón|millon|cop|pesos)", re.IGNORECASE)
_BUDGET_PLAIN_RE = re.compile(r"\b(\d{6,})\b")


def _parse_budget(lowered: str) -> int | None:
    if match := _BUDGET_UNIT_RE.search(lowered):
        raw = match.group(1).replace(".", "").replace(",", "")
        try:
            value = int(float(raw))
        except ValueError:
            return None
        unit = match.group(2).lower()
        if "millon" in unit or "mill" in unit:
            value *= 1_000_000
        return value
    if match := _BUDGET_PLAIN_RE.search(lowered):
        return int(match.group(1))
    return None


def extract_profile(text: str) -> dict:
    lowered = text.lower()
    result: dict = {}

    for key, canonical in _DESTINATIONS.items():
        if key in lowered:
            result["destination"] = canonical
            break

    tags = [canonical for key, canonical in _INTERESTS.items() if key in lowered]
    if tags:
        result["tags"] = sorted(set(tags))

    if match := _PARTY_RE.search(lowered):
        result["party"] = int(match.group(1))

    if (value := _parse_budget(lowered)) is not None:
        result["budget"] = value

    return result
