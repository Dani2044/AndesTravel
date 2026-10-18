"""PII redaction for logs and audit payloads.

Minimization and safe logging are requirements of the Ley 1581 / Decreto 1377
compliance band. Redaction is intentionally conservative: it favors over-redacting
rather than leaking personal data into logs.
"""

from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<![\d-])(?:\+?\d[\d\s().-]{6,}\d)(?![\d-])")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")
_LONG_ID = re.compile(r"(?<!\d)\d{7,}(?!\d)")

_REDACTED = "[REDACTED]"


def redact_text(value: str) -> str:
    """Return ``value`` with emails, phones, card numbers and long IDs masked."""

    result = _EMAIL.sub(_REDACTED, value)
    result = _CARD.sub(_REDACTED, result)
    result = _PHONE.sub(_REDACTED, result)
    result = _LONG_ID.sub(_REDACTED, result)
    return result


def redact_mapping(value: Any) -> Any:
    """Recursively redact text inside dicts, lists and scalars."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_mapping(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_mapping(v) for v in value]
    return value
