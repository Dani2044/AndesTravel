"""Domain enums shared across the application."""

from __future__ import annotations

from enum import StrEnum


class Channel(StrEnum):
    """Supported traveler-facing channels."""

    WEB = "web"
    WHATSAPP = "whatsapp"
    VOICE = "voice"
    EMAIL = "email"
    SMS = "sms"


class ConsentPurpose(StrEnum):
    """Purposes for which personal data may be processed (Ley 1581)."""

    PERSONALIZATION = "personalization"
    QUOTATION = "quotation"
    BOOKING = "booking"


class MemoryKind(StrEnum):
    """Kind of long-term memory record."""

    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"


class ReservationStatus(StrEnum):
    """Lifecycle of a reservation."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Intent(StrEnum):
    """Top-level intents the supervisor routes on."""

    GREETING = "greeting"
    PROFILE = "profile"
    RECOMMEND = "recommend"
    QUOTE = "quote"
    BOOK = "book"
    HUMAN = "human"
    UNKNOWN = "unknown"
