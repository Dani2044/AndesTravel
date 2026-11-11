"""Pure business rules for the tools API: identifiers, dates, packages and prices.

Everything here is deterministic and free of I/O so it can be unit-tested directly.
Domain problems are reported as :class:`DomainError` with a stable ``code`` that the
agent instructions map to fixed phrases (see orchestrate/agents/*.yaml).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher

from andes.core.seed import COMMISSION_RATE

QUOTE_TTL = timedelta(minutes=60)
INSURANCE_PER_PERSON = 180_000
MAX_TRAVELERS = 20
MAX_TRIP_DAYS = 30
MAX_DAYS_AHEAD = 548  # ~18 months
PERSONA_PROMPT_MAX = 600
CURRENCY = "COP"
# Andes Travel sells in Colombia (UTC-5, no daylight saving): "today" is Bogotá's date.
LOCAL_TZ = timezone(timedelta(hours=-5), "America/Bogota")


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
    # Agents sometimes add extras ("Eje Cafetero, Parque del Café"): accept the text when it
    # names exactly one catalog destination or package.
    named = [p for p in packages if fold(p.destination) in wanted or fold(p.name) in wanted]
    if len(named) == 1:
        return named[0]
    # LLMs mistype names in tool arguments ("Taybola" for Tayrona): accept a close spelling
    # of exactly one destination or package name, never a different place ("Marte").
    scored = sorted(
        (
            (max(_similar(wanted, fold(p.destination)), _similar(wanted, fold(p.name))), p)
            for p in packages
        ),
        key=lambda sp: sp[0],
        reverse=True,
    )
    best, runner_up = scored[0], scored[1] if len(scored) > 1 else (0.0, None)
    if best[0] >= FUZZY_MIN and best[0] - runner_up[0] >= FUZZY_MARGIN:
        return best[1]
    raise DomainError("unknown_package", "No tenemos ese destino en nuestro catálogo.")


FUZZY_MIN = 0.7  # "taybola" vs "tayrona" scores 0.71; "marte" vs any destination < 0.6
FUZZY_MARGIN = 0.1


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def local_today(now: datetime) -> date:
    """Today's date in Colombia for a timezone-aware instant."""
    return now.astimezone(LOCAL_TZ).date()


# --------------------------------------------------------------------------- dates


@dataclass(frozen=True)
class Trip:
    start: date
    end: date

    @property
    def nights(self) -> int:
        return (self.end - self.start).days


def parse_trip(start_date: str, end_date: str | None, today: date, days: int | None = None) -> Trip:
    """Validate a trip window. Raises ``invalid_dates`` with a reason the agent can say.

    Without an end_date the trip lasts `days` (the package length): the return date is
    departure + days - 1, so the agent never has to work it out.
    """
    try:
        start = date.fromisoformat((start_date or "").strip())
        if (end_date or "").strip():
            end = date.fromisoformat((end_date or "").strip())
        elif days:
            end = start + timedelta(days=days - 1)
        else:
            raise ValueError("no end date")
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


def check_duration(package: Package, trip: Trip) -> None:
    """Packages have a fixed length: the return date is departure + duration_days - 1."""
    expected = trip.start + timedelta(days=package.duration_days - 1)
    if trip.end != expected:
        raise DomainError(
            "invalid_duration",
            f"El paquete {package.name} dura {package.duration_days} días: saliendo el "
            f"{trip.start.isoformat()} regresas el {expected.isoformat()}.",
        )


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


def merge_attributes(previous: dict, new: dict) -> dict:
    """Update a stored profile without losing what earlier conversations taught us.

    New values win; interests accumulate (case-insensitive, first spelling kept).
    """
    merged = {**previous, **{k: v for k, v in new.items() if k != "interests"}}
    interests: list[str] = []
    for item in [*previous.get("interests", []), *new.get("interests", [])]:
        if fold(item) not in {fold(i) for i in interests}:
            interests.append(item)
    merged.pop("interests", None)
    if interests:
        merged["interests"] = interests
    return merged


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
