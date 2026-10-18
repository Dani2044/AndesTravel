from __future__ import annotations

import pytest

from andes.agents.intent import classify_intent
from andes.core.enums import Intent


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hola, buenos días", Intent.GREETING),
        ("quiero reservar el paquete", Intent.BOOK),
        ("¿cuánto cuesta Cartagena?", Intent.QUOTE),
        ("cotiza para 2 personas", Intent.QUOTE),
        ("recomiéndame un destino de playa", Intent.RECOMMEND),
        ("qué opciones tengo para diciembre", Intent.RECOMMEND),
        ("quiero hablar con un asesor humano", Intent.HUMAN),
        ("muéstrame mis preferencias guardadas", Intent.PROFILE),
        ("", Intent.UNKNOWN),
        ("asdf qwerty", Intent.UNKNOWN),
    ],
)
def test_classify_intent(text, expected):
    assert classify_intent(text) == expected


def test_book_takes_priority_over_quote():
    assert classify_intent("quiero reservar, cuánto cuesta") == Intent.BOOK
