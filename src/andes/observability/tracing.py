"""Distributed tracing (OpenTelemetry).

A tiny abstraction so the domain can create spans without importing OTel. The
default is a no-op tracer; the OTel tracer is created only when tracing is
enabled and the SDK is installed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from andes.core.config import get_settings


class Tracer(Protocol):
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Any: ...


class NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None: ...

    def record_exception(self, exc: BaseException) -> None: ...


class NoopTracer:
    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[NoopSpan]:
        yield NoopSpan()


class OTelTracer:
    def __init__(self, service_name: str = "andes-travel") -> None:
        from opentelemetry import trace  # noqa: PLC0415

        self._tracer = trace.get_tracer(service_name)

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
        with self._tracer.start_as_current_span(name) as span:
            for key, value in (attributes or {}).items():
                span.set_attribute(key, value)
            yield span


def get_tracer() -> Tracer:
    settings = get_settings()
    if settings.app_env == "local":
        return NoopTracer()
    try:
        return OTelTracer()
    except Exception:  # pragma: no cover - SDK not configured
        return NoopTracer()
