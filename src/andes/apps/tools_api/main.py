"""FastAPI app: one route per watsonx Orchestrate tool.

Run locally (in-memory storage):  make api-run
Environment:
    TOOLS_API_KEY        required header value for X-API-Key (all routes but /health)
    TOOLS_DATABASE_URL   Supabase Postgres URL; unset = in-memory storage
    WEBCHAT_PRIVATE_KEY  PEM RSA key that signs the landing page's chat tokens (optional)
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.security import APIKeyHeader

from andes.apps.tools_api import logic, price_guard, webchat
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
    PluginIn,
    PluginOut,
    ProfileIn,
    ProfileOut,
    QuoteIn,
    QuoteLine,
    QuoteOut,
    ReservationIn,
    ReservationOut,
    TestTravelersIn,
    TravelerContext,
)

Clock = Callable[[], datetime]
log = logging.getLogger("andes.price_guard")
# Quotes whose amounts the answer may repeat: still valid or expired within the last hour
# (created in the last ~2 hours), so a booking confirmation can repeat its total. The
# plug-in does not know the traveler, so a short window limits cross-traveler matches.
QUOTED_WINDOW = timedelta(hours=1)

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


# Only the landing page (Cloudflare Pages project andes-travel-poc, its previews) and a
# local preview may call the browser-facing routes.
WEBCHAT_ORIGINS = r"^https://([a-z0-9-]+\.)?andes-travel-poc\.pages\.dev$|^http://localhost(:\d+)?$"


def create_app(
    repo: Repository | None = None,
    api_key: str | None = None,
    clock: Clock = _utcnow,
    webchat_key: str | None = None,
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
    pem = webchat_key if webchat_key is not None else os.environ.get("WEBCHAT_PRIVATE_KEY", "")
    signing_key = webchat.load_private_key(pem.replace("\\n", "\n")) if pem else None
    app.add_middleware(
        CORSMiddleware, allow_origin_regex=WEBCHAT_ORIGINS, allow_methods=["GET"], max_age=3600
    )

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
            "the traveler consented, plus their recent bookings, and today's date in "
            "Colombia (today), to resolve relative dates such as 'este año' or 'el próximo mes'."
        ),
        response_model=TravelerContext,
        dependencies=auth,
    )
    async def get_traveler_context(traveler_id: str, repo: Repo, at: Now) -> TravelerContext:
        today = logic.local_today(at).isoformat()
        try:
            tid = logic.normalize_traveler_id(traveler_id)
        except DomainError as exc:
            return _fail(TravelerContext, exc).model_copy(update={"today": today})
        profile = await repo.get_profile(tid)
        reservations = await repo.recent_reservations(tid)
        consented = bool(profile and profile.consent_personalization)
        return TravelerContext(
            ok=True,
            traveler_id=tid,
            known_traveler=consented or bool(reservations),
            consent_personalization=consented,
            persona_prompt=profile.persona_prompt if consented and profile else None,
            attributes=profile.attributes if consented and profile else {},
            recent_reservations=reservations,
            today=today,
        )

    @app.put(
        "/travelers/{traveler_id}/profile",
        operation_id="upsert_traveler_profile",
        summary="Guardar perfil del viajero",
        description=(
            "Save the traveler's preferences and personalization summary. Only call it "
            "after the traveler explicitly consented to storing preferences; send "
            "consent_personalization=false when they decline or withdraw consent, which "
            "erases the stored profile. Attributes are merged into the stored ones "
            "(interests accumulate). persona_prompt replaces the stored one, so rewrite it "
            "with everything known; leave it out to keep the stored one."
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
            # Without consent nothing is kept: erase any stored profile and create no row
            # (a refusal must not make the traveler "known").
            await repo.delete_profile(tid)
            return ProfileOut(ok=True, traveler_id=tid, stored=False, erased=True)
        previous = await repo.get_profile(tid)
        consent_at = (
            previous.consent_at
            if previous and previous.consent_personalization and previous.consent_at
            else at
        )
        kept = previous if previous and previous.consent_personalization else None
        attributes = logic.merge_attributes(
            kept.attributes if kept else {}, body.attributes.model_dump(exclude_none=True)
        )
        if persona is None and kept:
            persona = kept.persona_prompt
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
            "so the advisor does not have to ask again. traveler_id is optional: never wait "
            "for it. Tell the traveler the returned message."
        ),
        response_model=HandoffOut,
        dependencies=auth,
    )
    async def escalate_to_human(body: HandoffIn, repo: Repo) -> HandoffOut:
        # Escalate even without (or with a malformed) traveler id: an upset traveler must
        # not be asked for an e-mail first. The id is kept only when it is valid.
        try:
            tid = logic.normalize_traveler_id(body.traveler_id) if body.traveler_id else None
        except DomainError:
            tid = None
        summary = " ".join(body.summary.split())[:2000]
        handoff_id = await repo.create_handoff(tid, body.reason.strip()[:100], summary)
        return HandoffOut(
            ok=True,
            handoff_id=handoff_id,
            status="queued",
            message=(
                "Listo, pasé tu caso a un asesor de Andes Travel con el resumen de esta "
                "conversación. Atendemos de lunes a viernes de 8:00 a. m. a 6:00 p. m. y "
                "sábados de 9:00 a. m. a 1:00 p. m. (hora de Colombia)."
                + ("" if tid else " Si quieres que te contacten, compárteme tu correo o celular.")
            ),
        )

    # ----------------------------------------------------------------- catalog

    @app.get(
        "/availability",
        operation_id="check_availability",
        summary="Consultar disponibilidad",
        description=(
            "Check whether a package can be sold for the given dates and number of "
            "travelers. Packages have a fixed length: leave end_date out and the package "
            "length sets it; a different end_date fails with invalid_duration and a message "
            "with the right return date. quote_package runs the same checks, so it can be "
            "called directly."
        ),
        response_model=AvailabilityOut,
        dependencies=auth,
    )
    async def check_availability(
        repo: Repo,
        at: Now,
        package: Annotated[str, Query(description="Package id, name or destination.")],
        start_date: Annotated[str, Query(description="Departure date, YYYY-MM-DD.")],
        travelers: Annotated[int, Query(description="Number of travelers (1-20).")],
        end_date: Annotated[
            str | None,
            Query(description="Return date, YYYY-MM-DD. Leave it out to use the package length."),
        ] = None,
    ) -> AvailabilityOut:
        try:
            pkg = logic.match_package(package, await repo.list_packages())
            trip = logic.parse_trip(start_date, end_date, logic.local_today(at), pkg.duration_days)
            logic.check_duration(pkg, trip)
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
            "Create an itemized quote for a package, departure date and number of travelers. "
            "Leave end_date out unless the traveler gave one: the package length sets it. "
            "The rate and the optional insurance are per person. Present only the lines, "
            "total and expiry returned here; never estimate prices."
        ),
        response_model=QuoteOut,
        dependencies=auth,
    )
    async def quote_package(body: QuoteIn, repo: Repo, at: Now) -> QuoteOut:
        try:
            tid = logic.normalize_traveler_id(body.traveler_id)
            pkg = logic.match_package(body.package, await repo.list_packages())
            trip = logic.parse_trip(
                body.start_date, body.end_date, logic.local_today(at), pkg.duration_days
            )
            logic.check_duration(pkg, trip)
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
            "exist for this traveler. A quote is booked at most once: a retry returns the same "
            "booking (deduplicated=true)."
        ),
        response_model=ReservationOut,
        dependencies=auth,
    )
    async def create_reservation(body: ReservationIn, repo: Repo, at: Now) -> ReservationOut:
        try:
            tid = logic.normalize_traveler_id(body.traveler_id)
        except DomainError as exc:
            return _fail(ReservationOut, exc)
        quote = await repo.get_quote(body.quote_id.strip())
        if quote is None or quote.traveler_id != tid:
            return _fail(
                ReservationOut,
                DomainError("quote_not_found", "No encontré esa cotización para este viajero."),
            )
        # The key is derived here, never by the agent: one quote can only be booked once,
        # and any retry returns the same booking.
        key = f"res-{quote.quote_id}"
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
            existing = await repo.find_reservation_for_quote(quote.quote_id)
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

    # ----------------------------------------------------------------- webchat

    @app.get("/webchat/token", include_in_schema=False, response_class=PlainTextResponse)
    async def webchat_token(at: Now, user_id: str | None = None) -> str:
        """JWT for the embedded chat (no API key: the browser calls it). See webchat.py."""
        if signing_key is None:
            raise HTTPException(status_code=503, detail="webchat is not configured")
        return webchat.visitor_token(user_id, signing_key, at)

    # ----------------------------------------------------------------- test support
    # Used by scripts/golden.py so the golden stories can reset and judge their own test
    # travelers over HTTPS (no direct database access needed). Only ids that start with
    # "test+" are touched; not part of the OpenAPI spec, so no agent ever sees them.

    @app.post("/test-support/reset", include_in_schema=False, dependencies=auth)
    async def test_reset(body: TestTravelersIn, repo: Repo) -> dict:
        return {"deleted": await repo.delete_test_travelers(body.traveler_ids)}

    @app.post("/test-support/state", include_in_schema=False, dependencies=auth)
    async def test_state(body: TestTravelersIn, repo: Repo) -> dict:
        packages = [
            {
                "id": p.id,
                "name": p.name,
                "duration_days": p.duration_days,
                "rate_per_person": p.rate_per_person,
            }
            for p in await repo.list_packages()
        ]
        return {"packages": packages, "travelers": await repo.test_state(body.traveler_ids or [])}

    # ----------------------------------------------------------------- plug-ins

    @app.post(
        "/plugins/price_guard",
        operation_id="price_guard",
        summary="Guardia de precios",
        description=(
            "Post-invoke plug-in for the supervisor: replaces the answer when it shows an "
            "amount that no recent stored quote backs."
        ),
        response_model=PluginOut,
        response_model_exclude_none=True,
        dependencies=auth,
        openapi_extra={"x-ibm-orchestrate-plugin": {"hook": "agent_post_invoke"}},
    )
    async def price_guard_plugin(body: PluginIn, repo: Repo, at: Now) -> PluginOut:
        shown = price_guard.amounts_in(price_guard.answer_text(body.payload))
        if not shown:
            if not price_guard.answer_text(body.payload):
                # unknown payload format: change nothing, log its structure (no content)
                log.warning(
                    "price_guard: no answer text; shape=%s",
                    json.dumps(price_guard.shape(body.payload))[:1500],
                )
            return PluginOut()
        try:
            quoted = await repo.quoted_amounts(at - QUOTED_WINDOW)
        except Exception:  # cannot verify: do not let an amount through
            log.exception("price_guard: could not load quoted amounts")
            quoted = set()
        missing = price_guard.unbacked(body.payload, quoted)
        if not missing:
            return PluginOut()
        log.warning("price_guard: replaced an answer with %d unquoted amount(s)", len(missing))
        return PluginOut(modified_payload=price_guard.replace_answer(body.payload))

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
