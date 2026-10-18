"""Input and output guardrails (OWASP LLM Top 10)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from andes.core.errors import GuardrailViolation

MAX_INPUT_CHARS = 4000

# Direct prompt-injection and jailbreak heuristics (English + Spanish).
_INJECTION_PATTERNS = [
    r"ignore (all|any|the)? ?(previous|prior|above) instructions",
    r"disregard (all|any|the)? ?(previous|prior|above)",
    r"forget (everything|your instructions|the rules)",
    r"reveal (your |the )?(system )?prompt",
    r"print (your |the )?(system )?prompt",
    r"you are now",
    r"act as (an? )?(unrestricted|jailbroken|dan)",
    r"ignora (todas?|las)? ?(instrucciones|reglas) (anteriores|previas)",
    r"olvida (todo|todos|toda|todas|tus instrucciones|las reglas)",
    r"(revela|muestra|imprime) (el )?(prompt|mensaje) (del sistema|de sistema)",
    r"ahora eres",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

_LEAK_MARKERS = [
    r"system prompt",
    r"you are an? (helpful|ai) assistant",
    r"prompt del sistema",
]


@dataclass(slots=True)
class GuardResult:
    ok: bool
    text: str
    reasons: list[str] = field(default_factory=list)


def scan_input(text: str) -> GuardResult:
    """Validate inbound traveler text.

    Raises :class:`GuardrailViolation` for hard failures (length or injection).
    """

    if len(text) > MAX_INPUT_CHARS:
        raise GuardrailViolation(f"input exceeds {MAX_INPUT_CHARS} characters")
    if _INJECTION_RE.search(text):
        raise GuardrailViolation("possible prompt injection detected")
    return GuardResult(ok=True, text=text)


def scan_output(text: str) -> GuardResult:
    """Validate outbound assistant text for system-prompt leakage."""

    reasons: list[str] = []
    lowered = text.lower()
    for marker in _LEAK_MARKERS:
        if re.search(marker, lowered):
            reasons.append(f"leak indicator: {marker}")
    ok = not reasons
    if not ok:
        raise GuardrailViolation("; ".join(reasons))
    return GuardResult(ok=True, text=text)
