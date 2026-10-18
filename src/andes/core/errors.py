"""Domain errors."""

from __future__ import annotations


class AndesError(Exception):
    """Base class for domain errors."""


class ValidationError(AndesError):
    """A payload failed domain validation."""


class ConsentRequired(AndesError):
    """The operation needs a consent that was not granted."""


class NotFound(AndesError):
    """A referenced entity does not exist."""


class QuoteExpired(AndesError):
    """The quote is past its validity window."""


class UpstreamUnavailable(AndesError):
    """A downstream dependency failed transiently (retryable)."""

    retryable = True


class GuardrailViolation(AndesError):
    """An input or output violated a safety guardrail."""
