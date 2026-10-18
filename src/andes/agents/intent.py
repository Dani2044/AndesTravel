"""Deterministic intent classification.

The classifier is rule-based by default so routing is testable and reproducible.
An LLM-based classifier can be layered on top without changing the interface.
"""

from __future__ import annotations

import re

from andes.core.enums import Intent

_KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    (
        Intent.BOOK,
        (
            "reserva",
            "reservar",
            "aparta",
            "apartar",
            "confirmo la reserva",
            "quiero reservar",
            "book",
        ),
    ),
    (
        Intent.QUOTE,
        (
            "cotiza",
            "cotización",
            "cotizacion",
            "precio",
            "cuánto",
            "cuanto cuesta",
            "costo",
            "presupuesto",
            "tarifa",
            "quote",
        ),
    ),
    (
        Intent.HUMAN,
        ("asesor", "humano", "persona real", "agente humano", "hablar con alguien"),
    ),
    (
        Intent.RECOMMEND,
        (
            "recomienda",
            "recomiéndame",
            "recomiendame",
            "sugerencia",
            "sugiere",
            "qué destinos",
            "que destinos",
            "ideas",
            "opciones",
            "dónde viajar",
            "donde viajar",
        ),
    ),
    (
        Intent.PROFILE,
        ("mi perfil", "recuerda", "mis preferencias", "mi historial"),
    ),
    (
        Intent.GREETING,
        ("hola", "buenos días", "buenas", "buen día", "saludos"),
    ),
]


def classify_intent(text: str) -> Intent:
    lowered = text.lower().strip()
    if not lowered:
        return Intent.UNKNOWN
    for intent, keywords in _KEYWORDS:
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}", lowered):
                return intent
    return Intent.UNKNOWN
