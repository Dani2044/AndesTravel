"""ASGI entrypoint for the API gateway.

Keeps the conventional ``main:app`` import path used by uvicorn / the Makefile.
"""

from __future__ import annotations

from andes.apps.api.app import app, create_app

__all__ = ["app", "create_app"]
