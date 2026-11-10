"""FastAPI app: one route per watsonx Orchestrate tool.

Run locally (in-memory storage):  make api-run
Environment:
    TOOLS_API_KEY        required header value for X-API-Key (all routes but /health)
    TOOLS_DATABASE_URL   Supabase Postgres URL; unset = in-memory storage
"""

from __future__ import annotations

import hmac
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import APIKeyHeader

from andes.apps.tools_api import logic
from andes.apps.tools_api.logic import DomainError
from andes.apps.tools_api.repository import (
    MemoryRepository,
    PostgresRepository,
    Profile,
    Quote,
    Repository,
    Reservation,
)
from andes.apps.tools_api.schemas import (
    AvailabilityOut,
    ErrorInfo,
    HandoffIn,
    HandoffOut,
    Money,
    PackageInfo,
    ProfileIn,
    ProfileOut,
    QuoteIn,
    QuoteLine,
    QuoteOut,
    ReservationIn,
    ReservationOut,
    TravelerContext,
)

Clock = Callable[[], datetime]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _get_repo(request: Request) -> Repository:
    return request.app.state.repo


def _now(request: Request) -> datetime:
    return request.app.state.clock()


# Module-level so FastAPI can resolve them (annotations are strings here).
Repo = Annotated[Repository, Depends(_get_repo)]
Now = Annotated[datetime, Depends(_now)]


def _fail(model: type, exc: DomainError):
    return model(ok=False, error=ErrorInfo(code=exc.code, message=exc.message))


def _pkg(p: logic.Package) -> PackageInfo:
    return PackageInfo(**p.summary())


def create_app(
    repo: Repository | None = None,
    api_key: str | None = None,
    clock: Clock = _utcnow,
) -> FastAPI:
    if repo is None:
        url = os.environ.get("TOOLS_DATABASE_URL")
        repo = PostgresRepository(url) if url else MemoryRepository()
    if api_key is None:
        api_key = os.environ.get("TOOLS_API_KEY", "")
    storage = "postgres" if isinstance(repo, PostgresRepository) else "memory"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await repo.close()

    app = FastAPI(
        title="Andes Travel tools API",
        version="0.1.0",
        description="Tools used by the Andes Travel agents in watsonx Orchestrate.",
        lifespan=lifespan,
    )
    app.state.repo = repo
    app.state.clock = clock

    def require_key(key: Annotated[str | None, Depends(_api_key_header)]) -> None:
        if not api_key:
            raise HTTPException(status_code=503, detail="TOOLS_API_KEY is not configured")
        if not key or not hmac.compare_digest(key.encode(), api_key.encode()):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")

    auth = [Depends(require_key)]

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok", "storage": storage}

    # ----------------------------------------------------------------- travelers

    @app.get(
        "/travelers/{traveler_id}/context",
        operation_id="get_traveler_context",
        summary="Contexto del viajero",
        description=(
            "Look up a returning traveler by e-mail or mobile number. Call it once at the "
            "start of the conversation, after the traveler gives their e-mail or phone. "
            "Returns the personalization summary (persona_prompt) and preferences only if "
            "the traveler consented, plus their recent bookings."
        ),
        response_model=TravelerContext,
        dependencies=auth,
    )
    async def get_traveler_context(traveler_id: str, repo: Repo) -> TravelerContext:
        try:
            tid = logic.normalize_traveler_id(traveler_id)
        except DomainError as exc:
            return _fail(TravelerContext, exc)
        profile = await repo.get_profile(tid)
        reservations = await repo.recent_reservations(tid)
        consented = bool(profile and profile.consent_personalization)
        return TravelerContext(
            ok=True,
            traveler_id=tid,
            known_traveler=profile is not None or bool(reservations),
            consent_personalization=consented,
            persona_prompt=profile.persona_prompt if consented and profile else None,
            attributes=profile.attributes if consented and profile else {},
            recent_reservations=reservations,
        )

    @app.put(
        "/travelers/{traveler_id}/profile",
        operation_id="upsert_traveler_profile",
        summary="Guardar perfil del viajero",
        description=(
            "Save the traveler's preferences and personalization summary. Only call it "
            "after the traveler explicitly consented to storing preferences; send "
            "consent_personalization=false when they decline or withdraw consent, which "
            "erases the stored profile. Send the full profile each time (it replaces the "
            "previous one)."
        ),
        response_model=ProfileOut,
        dependencies=auth,
    )
    async def upsert_traveler_profile(
        traveler_id: str, body: ProfileIn, repo: Repo, at: Now
    ) -> ProfileOut:
        try:
            tid = logic.normalize_traveler_id(traveler_id)
            persona = logic.clean_persona_prompt(body.persona_prompt)
        except DomainError as exc:
            return _fail(ProfileOut, exc)
        if not body.consent_personalization:
            await repo.save_profile(Profile(traveler_id=tid, consent_personalization=False))
            return ProfileOut(
                ok=False,
                traveler_id=tid,
                stored=False,
                error=ErrorInfo(
                    code="consent_required",
                    message="Sin autorización no guardamos preferencias; borramos las anteriores.",
                ),
            )
        previous = await repo.get_profile(tid)
        consent_at = (
            previous.consent_at
            if previous and previous.consent_personalization and previous.consent_at
            else at
        )
        attributes = body.attributes.model_dump(exclude_none=True)
        if not attributes.get("interests"):
            attributes.pop("interests", None)
        await repo.save_profile(
            Profile(
                traveler_id=tid,
                consent_personalization=True,
                consent_at=consent_at,
                attributes=attributes,
                persona_prompt=persona,
            )
        )
        return ProfileOut(ok=True, traveler_id=tid, stored=True)

    @app.post(
        "/handoffs",
        operation_id="escalate_to_human",
        summary="Escalar a un asesor humano",
        description=(
            "Register a hand-off to a human travel advisor when the traveler asks for a "
            "person, is upset, or the request cannot be resolved. Include a short summary "
            "so the advisor does not have to ask again."
        ),
        response_model=HandoffOut,
        dependencies=auth,
    )
    async def escalate_to_human(body: HandoffIn, repo: Repo) -> HandoffOut:
        try:
            tid = logic.normalize_traveler_id(body.traveler_id)
        except DomainError as exc:
            return _fail(HandoffOut, exc)
        summary = " ".join(body.summary.split())[:2000]
        handoff_id = await repo.create_handoff(tid, body.reason.strip()[:100], summary)
        return HandoffOut(
            ok=True,
            handoff_id=handoff_id,
            status="queued",
            message=(
                "Un asesor de Andes Travel te contactará pronto por este mismo medio, "
                "con el resumen de esta conversación."
            ),
        )

    # ----------------------------------------------------------------- catalog

    @app.get(
        "/availability",
        operation_id="check_availability",
        summary="Consultar disponibilidad",
        description=(
            "Check whether a package can be sold for the given dates and number of "
            "travelers, and its rate per person. Call it before quote_package."
        ),
        response_model=AvailabilityOut,
        dependencies=auth,
    )
    async def check_availability(
        repo: Repo,
        at: Now,
        package: Annotated[str, Query(description="Package id, name or destination.")],
        start_date: Annotated[str, Query(description="Departure date, YYYY-MM-DD.")],
        end_date: Annotated[str, Query(description="Return date, YYYY-MM-DD.")],
        travelers: Annotated[int, Query(description="Number of travelers (1-20).")],
    ) -> AvailabilityOut:
        try:
            pkg = logic.match_package(package, await repo.list_packages())
            trip = logic.parse_trip(start_date, end_date, at.date())
            logic.check_travelers(travelers)
        except DomainError as exc:
            return _fail(AvailabilityOut, exc)
        return AvailabilityOut(
            ok=True,
            available=True,
            package=_pkg(pkg),
            rate_per_person=Money(amount=pkg.rate_per_person, currency=pkg.currency),
            nights=trip.nights,
        )

    @app.post(
        "/quotes",
        operation_id="quote_package",
        summary="Cotizar paquete",
        description=(
            "Create an itemized quote for a package, dates and number of travelers. The "
            "rate and the optional insurance are per person. Present only the lines, "
            "total and expiry returned here; never estimate prices."
        ),
        response_model=QuoteOut,
        dependencies=auth,
    )
    async def quote_package(body: QuoteIn, repo: Repo, at: Now) -> QuoteOut:
        try:
            tid = logic.normalize_traveler_id(body.traveler_id)
            pkg = logic.match_package(body.package, await repo.list_packages())
            trip = logic.parse_trip(body.start_date, body.end_date, at.date())
            n = logic.check_travelers(body.travelers)
        except DomainError as exc:
            return _fail(QuoteOut, exc)
        lines = logic.quote_lines(pkg, n, body.include_insurance)
        total = sum(line["amount"] for line in lines)
        quote = Quote(
            quote_id=str(uuid.uuid4()),
            traveler_id=tid,
            package=pkg,
            start_date=trip.start,
            end_date=trip.end,
            travelers=n,
            lines=lines,
            total_amount=total,
            currency=pkg.currency,
            expires_at=at + logic.QUOTE_TTL,
        )
        await repo.save_quote(quote)
        return _quote_out(quote)

    @app.post(
        "/reservations",
        operation_id="create_reservation",
        summary="Crear reserva",
        description=(
            "Book a quote the traveler explicitly accepted. Fails with quote_expired when "
            "the quote is past its expiry and with quote_not_found when the quote does not "
            "exist for this traveler. Reusing an idempotency_key never creates a second "
            "booking."
        ),
        response_model=ReservationOut,
        dependencies=auth,
    )
    async def create_reservation(body: ReservationIn, repo: Repo, at: Now) -> ReservationOut:
        try:
            tid = logic.normalize_traveler_id(body.traveler_id)
        except DomainError as exc:
            return _fail(ReservationOut, exc)
        key = body.idempotency_key.strip()
        if not key:
            return _fail(
                ReservationOut,
                DomainError("idempotency_key_required", "Falta la llave de idempotencia."),
            )
        quote = await repo.get_quote(body.quote_id.strip())
        if quote is None or quote.traveler_id != tid:
            return _fail(
                ReservationOut,
                DomainError("quote_not_found", "No encontré esa cotización para este viajero."),
            )
        candidate = Reservation(
            reservation_id=str(uuid.uuid4()),
            traveler_id=tid,
            quote_id=quote.quote_id,
            idempotency_key=key,
            status="confirmed",
            total_amount=quote.total_amount,
            currency=quote.currency,
            commission_amount=logic.commission(quote.total_amount),
        )
        if quote.expires_at < at:
            # A retry of a booking made before expiry must still return that booking.
            existing = await repo.find_reservation_by_key(key)
            if existing is None:
                return _fail(
                    ReservationOut,
                    DomainError("quote_expired", "La cotización venció; hay que cotizar de nuevo."),
                )
            reservation, created = existing, False
        else:
            reservation, created = await repo.insert_reservation(candidate)
        if reservation.traveler_id != tid or reservation.quote_id != quote.quote_id:
            return _fail(
                ReservationOut,
                DomainError(
                    "idempotency_conflict",
                    "Esa llave de idempotencia ya se usó para otra reserva.",
                ),
            )
        return ReservationOut(
            ok=True,
            reservation_id=reservation.reservation_id,
            status=reservation.status,
            quote_id=quote.quote_id,
            package=_pkg(quote.package),
            start_date=quote.start_date.isoformat(),
            end_date=quote.end_date.isoformat(),
            travelers=quote.travelers,
            total=Money(amount=reservation.total_amount, currency=reservation.currency),
            deduplicated=not created,
        )

    return app


def _quote_out(quote: Quote) -> QuoteOut:
    return QuoteOut(
        ok=True,
        quote_id=quote.quote_id,
        package=_pkg(quote.package),
        start_date=quote.start_date.isoformat(),
        end_date=quote.end_date.isoformat(),
        travelers=quote.travelers,
        lines=[QuoteLine(**line) for line in quote.lines],
        total=Money(amount=quote.total_amount, currency=quote.currency),
        expires_at=quote.expires_at.astimezone(UTC).isoformat(timespec="seconds"),
    )


app = create_app()
