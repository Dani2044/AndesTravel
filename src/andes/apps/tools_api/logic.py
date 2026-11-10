"""Pure business rules for the tools API: identifiers, dates, packages and prices.

Everything here is deterministic and free of I/O so it can be unit-tested directly.
Domain problems are reported as :class:`DomainError` with a stable ``code`` that the
agent instructions map to fixed phrases (see orchestrate/agents/*.yaml).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from andes.core.seed import COMMISSION_RATE

QUOTE_TTL = timedelta(minutes=60)
INSURANCE_PER_PERSON = 180_000
MAX_TRAVELERS = 20
MAX_TRIP_DAYS = 30
MAX_DAYS_AHEAD = 548  # ~18 months
PERSONA_PROMPT_MAX = 600
CURRENCY = "COP"


class DomainError(Exception):
    """An expected, user-facing problem. ``code`` is stable; agents branch on it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- travelers

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


def normalize_traveler_id(raw: str) -> str:
    """Return the canonical traveler id: lowercase e-mail, or phone in E.164.

    Colombian mobiles given without a country code (10 digits starting with 3)
    get ``+57``. Anything else is rejected with ``invalid_traveler_id``.
    """
    value = (raw or "").strip()
    if "@" in value:
        email = value.lower()
        if _EMAIL.match(email):
            return email
        raise DomainError("invalid_traveler_id", "El correo no es válido.")
    digits = re.sub(r"[\s().-]", "", value)
    if digits.startswith("+") and digits[1:].isdigit() and 8 <= len(digits) - 1 <= 15:
        return digits
    if digits.isdigit() and len(digits) == 10 and digits.startswith("3"):
        return "+57" + digits
    if digits.isdigit() and digits.startswith("57") and len(digits) == 12:
        return "+" + digits
    raise DomainError(
        "invalid_traveler_id",
        "Necesito un correo electrónico o un número de celular válido.",
    )


# --------------------------------------------------------------------------- packages


def fold(text: str) -> str:
    """Lowercase and strip accents, for forgiving name matching."""
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@dataclass(frozen=True)
class Package:
    id: str
    destination: str
    name: str
    duration_days: int
    rate_per_person: int
    currency: str = CURRENCY

    def summary(self) -> dict:
        return {
            "package_id": self.id,
            "destination": self.destination,
            "name": self.name,
            "duration_days": self.duration_days,
        }


def match_package(query: str, packages: list[Package]) -> Package:
    """Find a package by id, exact name or destination (accent/case-insensitive)."""
    wanted = fold(query or "")
    if not wanted:
        raise DomainError("unknown_package", "No tenemos ese destino en nuestro catálogo.")
    for p in packages:
        if wanted in (p.id, fold(p.name), fold(p.destination)):
            return p
    raise DomainError("unknown_package", "No tenemos ese destino en nuestro catálogo.")


# --------------------------------------------------------------------------- dates


@dataclass(frozen=True)
class Trip:
    start: date
    end: date

    @property
    def nights(self) -> int:
        return (self.end - self.start).days


def parse_trip(start_date: str, end_date: str, today: date) -> Trip:
    """Validate a trip window. Raises ``invalid_dates`` with a reason the agent can say."""
    try:
        start = date.fromisoformat((start_date or "").strip())
        end = date.fromisoformat((end_date or "").strip())
    except ValueError as exc:
        raise DomainError("invalid_dates", "Necesito una fecha válida (AAAA-MM-DD).") from exc
    if start < today:
        raise DomainError("invalid_dates", "La fecha de salida ya pasó.")
    if end <= start:
        raise DomainError("invalid_dates", "La fecha de regreso debe ser posterior a la salida.")
    if (end - start).days > MAX_TRIP_DAYS:
        raise DomainError("invalid_dates", f"El viaje no puede durar más de {MAX_TRIP_DAYS} días.")
    if (start - today).days > MAX_DAYS_AHEAD:
        raise DomainError("invalid_dates", "Solo cotizamos viajes en los próximos 18 meses.")
    return Trip(start, end)


def check_travelers(travelers: int) -> int:
    if not 1 <= travelers <= MAX_TRAVELERS:
        raise DomainError(
            "invalid_travelers",
            f"Podemos cotizar entre 1 y {MAX_TRAVELERS} viajeros por reserva.",
        )
    return travelers


# --------------------------------------------------------------------------- prices


def quote_lines(package: Package, travelers: int, include_insurance: bool) -> list[dict]:
    """Itemized quote lines. The package rate and the insurance are per person."""
    lines = [
        {
            "description": f"Paquete {package.name} ({package.destination})",
            "unit_amount": package.rate_per_person,
            "quantity": travelers,
            "amount": package.rate_per_person * travelers,
        }
    ]
    if include_insurance:
        lines.append(
            {
                "description": "Seguro de viaje",
                "unit_amount": INSURANCE_PER_PERSON,
                "quantity": travelers,
                "amount": INSURANCE_PER_PERSON * travelers,
            }
        )
    return lines


def commission(total: int) -> int:
    return int(total * COMMISSION_RATE)


def clean_persona_prompt(text: str | None) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    if len(text) > PERSONA_PROMPT_MAX:
        raise DomainError(
            "persona_prompt_too_long",
            f"El resumen del viajero debe tener máximo {PERSONA_PROMPT_MAX} caracteres.",
        )
    return text or None
