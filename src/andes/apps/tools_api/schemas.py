"""Request/response models. Field descriptions become tool parameter docs in Orchestrate.

Inputs are deliberately permissive (plain strings for dates and ids) so that bad
values reach the domain rules and come back as ``ok: false`` with a stable error
code the agent can explain, instead of an opaque HTTP 422.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- shared


class ErrorInfo(BaseModel):
    code: str = Field(description="Stable error code, e.g. unknown_package, invalid_dates.")
    message: str = Field(description="Short explanation in Spanish, safe to tell the traveler.")


class Result(BaseModel):
    ok: bool = Field(description="False when the request could not be fulfilled; see error.")
    error: ErrorInfo | None = None


class PackageInfo(BaseModel):
    package_id: str
    destination: str
    name: str
    duration_days: int


class Money(BaseModel):
    amount: int = Field(description="Integer amount in the currency's units (COP has no cents).")
    currency: str


# --------------------------------------------------------------------------- travelers


class TravelerProfileAttributes(BaseModel):
    budget_cop_per_person: int | None = Field(
        default=None, description="Budget per person in COP, if the traveler gave one."
    )
    travel_style: str | None = Field(
        default=None, description="e.g. aventura, descanso, cultural, gastronómico."
    )
    interests: list[str] = Field(default_factory=list, description="e.g. playa, montaña, café.")
    group_size: int | None = Field(default=None, description="Usual number of travelers.")
    companions: str | None = Field(
        default=None, description="e.g. pareja, familia con niños, amigos, solo."
    )
    dates_flexibility: str | None = Field(default=None, description="e.g. fechas fijas, flexible.")
    notes: str | None = Field(
        default=None, description="Other preferences. Never documents, card or health data."
    )


class ProfileIn(BaseModel):
    consent_personalization: bool = Field(
        description=(
            "True only if the traveler explicitly agreed that Andes Travel stores their "
            "preferences to personalize future conversations. False revokes consent and "
            "erases the stored profile."
        )
    )
    attributes: TravelerProfileAttributes = Field(default_factory=TravelerProfileAttributes)
    persona_prompt: str | None = Field(
        default=None,
        description=(
            "Up to 600 characters, third person, summarizing what matters to personalize "
            "for this traveler (style, budget, companions, constraints, past trips). "
            "Rewrite the whole summary each time; no sensitive data."
        ),
    )


class ProfileOut(Result):
    traveler_id: str | None = None
    stored: bool = Field(default=False, description="True when the profile was saved.")
    erased: bool = Field(
        default=False, description="True when consent was denied and any stored profile is gone."
    )


class TravelerContext(Result):
    traveler_id: str | None = None
    known_traveler: bool = Field(
        default=False, description="True if Andes Travel has data for this traveler."
    )
    consent_personalization: bool = False
    persona_prompt: str | None = Field(
        default=None, description="Personalization summary; use it to tailor the conversation."
    )
    attributes: dict[str, Any] = Field(default_factory=dict)
    recent_reservations: list[dict[str, Any]] = Field(
        default_factory=list, description="Up to 3 recent bookings (destination and dates)."
    )
    today: str | None = Field(
        default=None,
        description="Today's date in Colombia (YYYY-MM-DD). Trip dates must be after it.",
    )


class HandoffIn(BaseModel):
    traveler_id: str | None = Field(
        default=None,
        description="Traveler e-mail or mobile number, if known. Never wait for it to escalate.",
    )
    reason: str = Field(description="Why a human is needed, e.g. asked_for_human, upset.")
    summary: str = Field(description="Short summary of the conversation for the advisor.")


class HandoffOut(Result):
    handoff_id: str | None = None
    status: str | None = None
    message: str | None = Field(default=None, description="What to tell the traveler.")


# --------------------------------------------------------------------------- catalog


class AvailabilityOut(Result):
    available: bool = False
    package: PackageInfo | None = None
    rate_per_person: Money | None = None
    nights: int | None = None


class QuoteIn(BaseModel):
    traveler_id: str = Field(description="Traveler e-mail or mobile number.")
    package: str = Field(description="Package id, package name or destination name.")
    start_date: str = Field(description="Departure date, YYYY-MM-DD.")
    end_date: str | None = Field(
        default=None,
        description=(
            "Return date, YYYY-MM-DD. Leave it out when the traveler gave no return date: "
            "the package length sets it."
        ),
    )
    travelers: int = Field(description="Number of travelers (1-20).")
    include_insurance: bool = Field(
        default=False, description="Add travel insurance (priced per person)."
    )


class QuoteLine(BaseModel):
    description: str
    unit_amount: int
    quantity: int
    amount: int


class QuoteOut(Result):
    quote_id: str | None = None
    package: PackageInfo | None = None
    start_date: str | None = None
    end_date: str | None = None
    travelers: int | None = None
    lines: list[QuoteLine] = Field(default_factory=list)
    total: Money | None = None
    expires_at: str | None = Field(
        default=None, description="ISO-8601 UTC time after which the quote is no longer valid."
    )


class ReservationIn(BaseModel):
    traveler_id: str = Field(description="Traveler e-mail or mobile number.")
    quote_id: str = Field(description="The quote the traveler explicitly accepted.")
    idempotency_key: str | None = Field(
        default=None,
        description="Ignored: the server derives it from quote_id (res-<quote_id>).",
    )


class ReservationOut(Result):
    reservation_id: str | None = None
    status: str | None = None
    quote_id: str | None = None
    package: PackageInfo | None = None
    start_date: str | None = None
    end_date: str | None = None
    travelers: int | None = None
    total: Money | None = None
    deduplicated: bool = Field(
        default=False, description="True when this key was already used; nothing new was booked."
    )


class PluginIn(BaseModel):
    """What watsonx Orchestrate sends to an OpenAPI plug-in."""

    payload: dict = Field(description="The agent payload for this phase (messages, tool_calls).")
    context: dict = Field(description="System, request and plug-in context.")


class PluginOut(BaseModel):
    continue_processing: bool = True
    modified_payload: dict | None = None


class TestTravelersIn(BaseModel):
    """Test support: ids must start with "test+"; others are ignored. None = every test id."""

    traveler_ids: list[str] | None = None
