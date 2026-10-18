"""The conversation orchestrator.

``Assistant`` implements the turn logic that the LangGraph supervisor delegates
to. It is deliberately framework-agnostic and dependency-injected, so it is fully
unit-testable; ``graph.py`` wires the same logic into a LangGraph ``StateGraph``.

``turn`` is the full pipeline. The pipeline is also split into ``prepare`` (guard,
extract, classify) and ``finalize`` (output guard, audit) around the per-intent
handlers, so the graph can run each handler as its own node.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field

from andes.agents.extract import extract_profile
from andes.agents.intent import classify_intent
from andes.booking_api.store import BookingStore
from andes.core.enums import ConsentPurpose, Intent, MemoryKind, ReservationStatus
from andes.core.errors import ValidationError
from andes.core.schemas import (
    HandoffSummary,
    MessageEnvelope,
    PackageSummary,
    Quote,
    QuoteLine,
    Reservation,
)
from andes.core.seed import CATALOG, SeedPackage, find_by_destination
from andes.governance.audit import AuditLog
from andes.governance.guards import scan_input, scan_output
from andes.knowledge.retriever import Retriever
from andes.mcp_server.tools import create_reservation, quote_package
from andes.memory.service import ConsentService, ProfileService
from andes.memory.store import MemoryStore

DEFAULT_TRAVELERS = 2


class AssistantReply(BaseModel):
    text: str
    intent: Intent
    recommendations: list[PackageSummary] = Field(default_factory=list)
    quote: Quote | None = None
    reservation: Reservation | None = None
    handoff: HandoffSummary | None = None


class Assistant:
    def __init__(
        self,
        *,
        consent: ConsentService,
        profile: ProfileService,
        memory: MemoryStore,
        retriever: Retriever,
        audit: AuditLog | None = None,
        store: BookingStore | None = None,
    ) -> None:
        self._consent = consent
        self._profile = profile
        self._memory = memory
        self._retriever = retriever
        self._audit = audit
        self._store = store
        self._last_quote: dict[UUID, dict] = {}

    # -- pipeline ----------------------------------------------------------
    def prepare(self, envelope: MessageEnvelope) -> tuple[Intent, dict]:
        """Guard input, update profile/memory and classify intent."""

        scan_input(envelope.text)
        traveler_id = envelope.traveler_id

        extracted = extract_profile(envelope.text)
        if extracted:
            self._profile.update(traveler_id, extracted)
        profile = self._profile.get(traveler_id)
        attributes = profile.attributes if profile else {}

        self._memory.remember(traveler_id, envelope.text, MemoryKind.EVENT, envelope.channel)
        return classify_intent(envelope.text), attributes

    def finalize(self, envelope: MessageEnvelope, reply: AssistantReply) -> AssistantReply:
        scan_output(reply.text)
        if self._audit:
            self._audit.record(
                actor=str(envelope.traveler_id),
                action=f"assistant.{reply.intent.value}",
                entity=f"traveler:{envelope.traveler_id}",
                payload={"text": envelope.text, "channel": envelope.channel.value},
            )
        return reply

    def turn(self, envelope: MessageEnvelope) -> AssistantReply:
        intent, attributes = self.prepare(envelope)
        reply = self.route(intent, envelope, attributes)
        return self.finalize(envelope, reply)

    # -- routing -----------------------------------------------------------
    def route(self, intent: Intent, envelope: MessageEnvelope, attributes: dict) -> AssistantReply:
        match intent:
            case Intent.RECOMMEND:
                return self.recommend(envelope, attributes)
            case Intent.QUOTE:
                return self.quote(envelope, attributes)
            case Intent.BOOK:
                return self.book(envelope, attributes)
            case Intent.HUMAN:
                return self.handoff(envelope, attributes, "explicit request")
            case Intent.PROFILE:
                return self.recall(envelope)
            case _:
                return self.greet(envelope)

    # -- handlers ----------------------------------------------------------
    def greet(self, envelope: MessageEnvelope) -> AssistantReply:
        text = (
            "¡Hola! Soy el asistente de viajes de Andes Travel. Puedo recomendarte "
            "destinos, preparar una cotización y crear tu reserva. ¿Qué tipo de viaje "
            "estás buscando?"
        )
        return AssistantReply(text=text, intent=Intent.GREETING)

    def recall(self, envelope: MessageEnvelope) -> AssistantReply:
        traveler_id = envelope.traveler_id
        profile = self._profile.get(traveler_id)
        highlights = MemoryStore.highlights(self._memory.recent(traveler_id), limit=3)
        parts = []
        if profile and profile.attributes:
            parts.append(f"Esto es lo que recuerdo de ti: {profile.attributes}.")
        if highlights:
            parts.append("Contexto reciente: " + "; ".join(highlights) + ".")
        if not parts:
            parts.append("Todavía no tengo información tuya; cuéntame tu próximo viaje.")
        return AssistantReply(text=" ".join(parts), intent=Intent.PROFILE)

    def recommend(self, envelope: MessageEnvelope, attributes: dict) -> AssistantReply:
        self._consent.require(envelope.traveler_id, ConsentPurpose.PERSONALIZATION)
        recommendations = self._retriever.recommend(attributes, k=3)
        if not recommendations:
            return AssistantReply(
                text="Cuéntame destino, fechas y cuántos viajan para recomendarte.",
                intent=Intent.RECOMMEND,
            )
        lines = [
            f"{i + 1}. {s.destination} — {s.name} ({s.duration_days} días)"
            for i, s in enumerate(recommendations)
        ]
        text = "Estas son mis recomendaciones:\n" + "\n".join(lines)
        return AssistantReply(text=text, intent=Intent.RECOMMEND, recommendations=recommendations)

    def quote(self, envelope: MessageEnvelope, attributes: dict) -> AssistantReply:
        self._consent.require(envelope.traveler_id, ConsentPurpose.QUOTATION)
        package = self._select_package(attributes)
        if package is None:
            return AssistantReply(
                text="¿A qué destino quieres viajar y en qué fechas?", intent=Intent.QUOTE
            )
        travelers = int(attributes.get("party", DEFAULT_TRAVELERS))
        start, end = self._default_dates(package)
        result = quote_package(
            package["id"],
            travelers,
            start,
            end,
            {"include_insurance": True},
            store=self._store,
        )
        if "error" in result:
            return AssistantReply(
                text="No pude cotizar en este momento; inténtalo de nuevo.",
                intent=Intent.QUOTE,
            )
        self._last_quote[envelope.traveler_id] = result
        quote = Quote(
            id=UUID(result["quote_id"]),
            traveler_id=envelope.traveler_id,
            package_id=UUID(result["package_id"]),
            lines=[QuoteLine(**line) for line in result["lines"]],
            total_amount=result["total"]["amount"],
            currency=result["total"]["currency"],
            expires_at=datetime.fromisoformat(result["expires_at"]),
        )
        text = (
            f"Tu cotización para {package['destination']} ({package['name']}) es "
            f"{quote.total_amount:,} {quote.currency}. "
            f"Vigente hasta {quote.expires_at.isoformat()}."
        )
        return AssistantReply(text=text, intent=Intent.QUOTE, quote=quote)

    def book(self, envelope: MessageEnvelope, attributes: dict) -> AssistantReply:
        self._consent.require(envelope.traveler_id, ConsentPurpose.BOOKING)
        last = self._last_quote.get(envelope.traveler_id)
        if last is None:
            return AssistantReply(
                text="Primero necesito una cotización vigente. ¿Te la preparo?",
                intent=Intent.BOOK,
            )
        idempotency_key = f"{envelope.traveler_id}:{last['quote_id']}"
        result = create_reservation(
            last["quote_id"],
            str(envelope.traveler_id),
            idempotency_key,
            payment={"provider": "wompi", "reference": "sandbox"},
            store=self._store,
        )
        if "error" in result:
            code = result["error"]["code"]
            return AssistantReply(
                text=f"No pude crear la reserva ({code}). ¿Quieres que lo intente de nuevo?",
                intent=Intent.BOOK,
            )
        reservation = Reservation(
            id=UUID(result["reservation_id"]),
            traveler_id=envelope.traveler_id,
            quote_id=UUID(result["quote_id"]),
            status=ReservationStatus(result["status"]),
            total_amount=result["totals"]["amount"],
            currency=result["totals"]["currency"],
            commission_amount=result["totals"]["commission"],
            idempotency_key=idempotency_key,
        )
        text = (
            f"¡Reserva confirmada! {reservation.total_amount:,} "
            f"{reservation.currency}. Te enviaré el itinerario."
        )
        return AssistantReply(text=text, intent=Intent.BOOK, reservation=reservation)

    def handoff(self, envelope: MessageEnvelope, attributes: dict, reason: str) -> AssistantReply:
        highlights = MemoryStore.highlights(self._memory.recent(envelope.traveler_id))
        handoff = HandoffSummary(
            traveler_id=envelope.traveler_id,
            intent=Intent.HUMAN,
            reason=reason,
            profile=attributes,
            memory_highlights=highlights,
            open_question=envelope.text,
        )
        text = "Te estoy transfiriendo con un asesor humano que ya tiene tu contexto."
        return AssistantReply(text=text, intent=Intent.HUMAN, handoff=handoff)

    # -- helpers -----------------------------------------------------------
    def _select_package(self, attributes: dict) -> SeedPackage | None:
        if (destination := attributes.get("destination")) and (
            package := find_by_destination(str(destination))
        ):
            return package
        summaries = self._retriever.recommend(attributes, k=1)
        if not summaries:
            return None
        chosen = summaries[0].id
        return next((p for p in CATALOG if p["id"] == str(chosen)), None)

    @staticmethod
    def _default_dates(package: SeedPackage) -> tuple[str, str]:
        start = date.today() + timedelta(days=30)
        end = start + timedelta(days=package["duration_days"])
        return start.isoformat(), end.isoformat()


__all__ = ["Assistant", "AssistantReply", "ValidationError"]
