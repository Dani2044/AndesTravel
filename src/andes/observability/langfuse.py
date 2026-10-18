"""Langfuse sink (LLM observability), lazily imported.

Disabled by default; enable with ``LANGFUSE_ENABLED=true`` plus keys. The sink
never raises on failure: observability must not break a traveler turn.
"""

from __future__ import annotations

from typing import Any

from andes.core.config import get_settings


class LangfuseSink:
    def __init__(self, enabled: bool | None = None) -> None:
        settings = get_settings()
        self._enabled = settings.langfuse_enabled if enabled is None else enabled
        self._client: Any = None
        self._settings = settings

    def _get_client(self) -> Any:
        if self._client is None:
            from langfuse import Langfuse  # noqa: PLC0415

            self._client = Langfuse(
                public_key=self._settings.langfuse_public_key,
                secret_key=self._settings.langfuse_secret_key,
                host=self._settings.langfuse_host,
            )
        return self._client

    def log_turn(self, **fields: Any) -> None:
        if not self._enabled:
            return
        try:
            self._get_client().create_event(name="turn", **fields)
        except Exception:  # pragma: no cover - best effort
            return
