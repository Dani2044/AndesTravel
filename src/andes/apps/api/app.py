"""FastAPI gateway.

Exposes a channel-agnostic ``/chat`` endpoint plus provider webhooks (WhatsApp,
voice), a health probe and a simple metrics endpoint. The gateway owns transport
concerns only; all logic lives in :class:`andes.conversation.ConversationService`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from andes.analytics.events import InMemoryEventSink
from andes.analytics.metrics import compute_funnel
from andes.core.config import get_settings
from andes.core.errors import AndesError, ConsentRequired, GuardrailViolation
from andes.payments import verify_event
from andes.wiring import Container, build_container


class ChatRequest(BaseModel):
    text: str = Field(min_length=1)
    traveler_id: str | None = None
    session_id: str | None = None
    handle: str | None = None


def create_app(container: Container | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Andes Travel Assistant", version="0.1.0")
    container = container or build_container()
    app.state.container = container

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "env": settings.app_env}

    @app.post("/chat")
    def chat(request: ChatRequest) -> Any:
        payload = request.model_dump(exclude_none=True)
        return _dispatch(app, "web", payload)

    @app.get("/whatsapp/webhook")
    def whatsapp_verify(request: Request) -> PlainTextResponse:
        params = request.query_params
        if params.get("hub.verify_token") == settings.whatsapp_verify_token:
            return PlainTextResponse(params.get("hub.challenge", ""))
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/whatsapp/webhook")
    async def whatsapp_receive(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if "messages" not in _whatsapp_value(payload):
            return {"status": "ignored"}
        response = _dispatch(app, "whatsapp", payload)
        _send_whatsapp(response)
        return {"status": "ok"}

    @app.post("/voice")
    async def voice(request: Request) -> PlainTextResponse:
        form = await request.form()
        payload = dict(form)
        twiml = _dispatch(app, "voice", payload)
        return PlainTextResponse(twiml, media_type="application/xml")

    @app.post("/webhooks/wompi")
    async def wompi_events(request: Request) -> dict[str, Any]:
        payload = await request.json()
        secret = settings.wompi_events_secret or ""
        if secret and not verify_event(payload, secret):
            raise HTTPException(status_code=403, detail="invalid signature")
        return {"status": "ok"}

    @app.get("/metrics/funnel")
    def funnel() -> dict[str, Any]:
        sink = container.events
        events = sink.events() if isinstance(sink, InMemoryEventSink) else []
        metrics = compute_funnel(events)
        return {
            "turns": metrics.turns,
            "quotes": metrics.quotes,
            "reservations": metrics.reservations,
            "handoffs": metrics.handoffs,
            "quote_rate": round(metrics.quote_rate, 4),
            "conversion_rate": round(metrics.conversion_rate, 4),
            "handoff_rate": round(metrics.handoff_rate, 4),
        }

    return app


def _dispatch(app: FastAPI, channel: str, payload: dict) -> Any:
    container: Container = app.state.container
    try:
        return container.conversation.handle(channel, payload)
    except GuardrailViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConsentRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AndesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _whatsapp_value(payload: dict) -> dict:
    try:
        return payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return {}


def _send_whatsapp(response: dict) -> None:  # pragma: no cover - needs Meta creds
    settings = get_settings()
    if not settings.whatsapp_enabled:
        return
    import httpx  # noqa: PLC0415

    url = f"https://graph.facebook.com/v20.0/{settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
    httpx.post(url, json=response, headers=headers, timeout=10.0)


app = create_app()
