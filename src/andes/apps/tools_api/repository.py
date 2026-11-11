"""Storage for the tools API: Postgres (Supabase) in deployment, memory locally.

Both implementations honour the same contract, and every read is scoped by
``traveler_id`` so one traveler can never see another traveler's data.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from andes.apps.tools_api.logic import CURRENCY, Package
from andes.core.seed import CATALOG


@dataclass
class Quote:
    quote_id: str
    traveler_id: str
    package: Package
    start_date: date
    end_date: date
    travelers: int
    lines: list[dict]
    total_amount: int
    currency: str
    expires_at: datetime


@dataclass
class Reservation:
    reservation_id: str
    traveler_id: str
    quote_id: str
    idempotency_key: str
    status: str
    total_amount: int
    currency: str
    commission_amount: int


@dataclass
class Profile:
    traveler_id: str
    consent_personalization: bool = False
    consent_at: datetime | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    persona_prompt: str | None = None
    updated_at: datetime | None = None


class Repository(Protocol):
    async def list_packages(self) -> list[Package]: ...

    async def get_profile(self, traveler_id: str) -> Profile | None: ...

    async def save_profile(self, profile: Profile) -> None: ...

    async def recent_reservations(self, traveler_id: str, limit: int = 3) -> list[dict]: ...

    async def create_handoff(self, traveler_id: str | None, reason: str, summary: str) -> str: ...

    async def save_quote(self, quote: Quote) -> None: ...

    async def get_quote(self, quote_id: str) -> Quote | None: ...

    async def insert_reservation(self, reservation: Reservation) -> tuple[Reservation, bool]:
        """Insert unless the idempotency key exists. Returns (reservation, created)."""
        ...

    async def find_reservation_by_key(self, idempotency_key: str) -> Reservation | None: ...

    async def find_reservation_for_quote(self, quote_id: str) -> Reservation | None: ...

    async def delete_profile(self, traveler_id: str) -> None:
        """Erase the stored profile (consent denied or withdrawn); creates nothing."""
        ...

    # test support: only travelers whose id starts with TEST_PREFIX
    async def delete_test_travelers(self, ids: list[str] | None) -> int: ...

    async def test_state(self, ids: list[str]) -> dict[str, dict]: ...

    async def quoted_amounts(self, since: datetime) -> set[int]:
        """Totals, line and unit amounts of every quote that expires after `since`."""
        ...

    async def close(self) -> None: ...


TEST_PREFIX = "test+"


def _test_ids(ids: list[str]) -> list[str]:
    return [i for i in ids if i.startswith(TEST_PREFIX)]


def catalog_packages() -> list[Package]:
    return [
        Package(
            id=p["id"],
            destination=p["destination"],
            name=p["name"],
            duration_days=p["duration_days"],
            rate_per_person=p["base_rate"],
        )
        for p in CATALOG
    ]


# --------------------------------------------------------------------------- memory


class MemoryRepository:
    """In-process storage for local runs and tests. Not shared between workers."""

    def __init__(self) -> None:
        self.packages = catalog_packages()
        self.profiles: dict[str, Profile] = {}
        self.quotes: dict[str, Quote] = {}
        self.reservations: dict[str, Reservation] = {}
        self.handoffs: list[dict] = []

    async def list_packages(self) -> list[Package]:
        return list(self.packages)

    async def get_profile(self, traveler_id: str) -> Profile | None:
        return self.profiles.get(traveler_id)

    async def save_profile(self, profile: Profile) -> None:
        self.profiles[profile.traveler_id] = profile

    async def delete_profile(self, traveler_id: str) -> None:
        self.profiles.pop(traveler_id, None)

    async def delete_test_travelers(self, ids: list[str] | None) -> int:
        known = (
            set(self.profiles)
            | {q.traveler_id for q in self.quotes.values()}
            | {h["traveler_id"] for h in self.handoffs if h["traveler_id"]}
        )
        doomed = {t for t in known if t.startswith(TEST_PREFIX)}
        if ids is not None:
            doomed &= set(_test_ids(ids))
        for t in doomed:
            self.profiles.pop(t, None)
        self.reservations = {
            k: r for k, r in self.reservations.items() if r.traveler_id not in doomed
        }
        self.quotes = {k: q for k, q in self.quotes.items() if q.traveler_id not in doomed}
        self.handoffs = [h for h in self.handoffs if h["traveler_id"] not in doomed]
        return len(doomed)

    async def test_state(self, ids: list[str]) -> dict[str, dict]:
        out = {}
        for tid in _test_ids(ids):
            p = self.profiles.get(tid)
            out[tid] = {
                "quotes": [
                    {
                        "id": q.quote_id,
                        "package_id": q.package.id,
                        "start_date": q.start_date.isoformat(),
                        "end_date": q.end_date.isoformat(),
                        "travelers": q.travelers,
                        "lines": q.lines,
                        "total_amount": q.total_amount,
                    }
                    for q in self.quotes.values()
                    if q.traveler_id == tid
                ],
                "reservations": [
                    {
                        "quote_id": r.quote_id,
                        "idempotency_key": r.idempotency_key,
                        "status": r.status,
                    }
                    for r in self.reservations.values()
                    if r.traveler_id == tid
                ],
                "profile": None
                if p is None
                else {
                    "consent_personalization": p.consent_personalization,
                    "attributes": p.attributes,
                    "persona_prompt": p.persona_prompt,
                },
                "handoffs": sum(1 for h in self.handoffs if h["traveler_id"] == tid),
            }
        return out

    async def recent_reservations(self, traveler_id: str, limit: int = 3) -> list[dict]:
        out = []
        for r in reversed(list(self.reservations.values())):
            if r.traveler_id != traveler_id:
                continue
            q = self.quotes[r.quote_id]
            out.append(_reservation_brief(r.reservation_id, q.package, q.start_date, q.end_date))
            if len(out) == limit:
                break
        return out

    async def create_handoff(self, traveler_id: str | None, reason: str, summary: str) -> str:
        handoff_id = str(uuid.uuid4())
        self.handoffs.append(
            {"id": handoff_id, "traveler_id": traveler_id, "reason": reason, "summary": summary}
        )
        return handoff_id

    async def save_quote(self, quote: Quote) -> None:
        self.quotes[quote.quote_id] = quote

    async def get_quote(self, quote_id: str) -> Quote | None:
        return self.quotes.get(quote_id)

    async def quoted_amounts(self, since: datetime) -> set[int]:
        return {
            a
            for q in self.quotes.values()
            if q.expires_at >= since
            for a in _quote_amounts(q.total_amount, q.lines)
        }

    async def insert_reservation(self, reservation: Reservation) -> tuple[Reservation, bool]:
        for existing in self.reservations.values():
            if (
                existing.idempotency_key == reservation.idempotency_key
                or existing.quote_id == reservation.quote_id
            ):
                return existing, False
        self.reservations[reservation.reservation_id] = reservation
        return reservation, True

    async def find_reservation_by_key(self, idempotency_key: str) -> Reservation | None:
        for existing in self.reservations.values():
            if existing.idempotency_key == idempotency_key:
                return existing
        return None

    async def find_reservation_for_quote(self, quote_id: str) -> Reservation | None:
        for existing in self.reservations.values():
            if existing.quote_id == quote_id:
                return existing
        return None

    async def close(self) -> None:
        return None


def _quote_amounts(total: int, lines: list[dict]) -> set[int]:
    out = {int(total)}
    for line in lines:
        out |= {int(line[k]) for k in ("amount", "unit_amount") if line.get(k) is not None}
    return out


def _reservation_brief(rid: str, package: Package, start: date, end: date) -> dict:
    return {
        "reservation_id": rid,
        "destination": package.destination,
        "package_name": package.name,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


# --------------------------------------------------------------------------- postgres


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


class PostgresRepository:
    """Supabase Postgres via SQLAlchemy + asyncpg.

    ``statement_cache_size=0`` keeps asyncpg compatible with Supabase's pooler
    (PgBouncer in transaction mode does not support prepared statements).
    """

    def __init__(self, url: str, engine: AsyncEngine | None = None) -> None:
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        self.engine = engine or create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"statement_cache_size": 0},
        )
        self._packages: list[Package] | None = None

    async def list_packages(self) -> list[Package]:
        if self._packages is None:
            async with self.engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "select id, destination, name, duration_days, rate_per_person, currency "
                        "from packages where active order by destination"
                    )
                )
                self._packages = [
                    Package(
                        str(r.id),
                        r.destination,
                        r.name,
                        r.duration_days,
                        int(r.rate_per_person),
                        r.currency,
                    )
                    for r in rows
                ]
        return list(self._packages)

    async def _package(self, package_id: str) -> Package:
        for p in await self.list_packages():
            if p.id == package_id:
                return p
        raise LookupError(package_id)

    async def get_profile(self, traveler_id: str) -> Profile | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "select traveler_id, consent_personalization, consent_at, attributes, "
                        "persona_prompt, updated_at from traveler_profiles "
                        "where traveler_id = :tid"
                    ),
                    {"tid": traveler_id},
                )
            ).first()
        if row is None:
            return None
        attrs = row.attributes if isinstance(row.attributes, dict) else json.loads(row.attributes)
        return Profile(
            traveler_id=row.traveler_id,
            consent_personalization=row.consent_personalization,
            consent_at=row.consent_at,
            attributes=attrs,
            persona_prompt=row.persona_prompt,
            updated_at=row.updated_at,
        )

    async def save_profile(self, profile: Profile) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("insert into travelers (id) values (:tid) on conflict (id) do nothing"),
                {"tid": profile.traveler_id},
            )
            await conn.execute(
                text(
                    "insert into traveler_profiles (traveler_id, consent_personalization, "
                    "consent_at, attributes, persona_prompt, updated_at) values (:tid, :consent, "
                    ":consent_at, cast(:attrs as jsonb), :persona, now()) "
                    "on conflict (traveler_id) do update set "
                    "consent_personalization = excluded.consent_personalization, "
                    "consent_at = excluded.consent_at, attributes = excluded.attributes, "
                    "persona_prompt = excluded.persona_prompt, updated_at = now()"
                ),
                {
                    "tid": profile.traveler_id,
                    "consent": profile.consent_personalization,
                    "consent_at": profile.consent_at,
                    "attrs": json.dumps(profile.attributes, ensure_ascii=False),
                    "persona": profile.persona_prompt,
                },
            )

    async def recent_reservations(self, traveler_id: str, limit: int = 3) -> list[dict]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "select r.id, q.package_id, q.start_date, q.end_date "
                        "from reservations r join quotes q on q.id = r.quote_id "
                        "where r.traveler_id = :tid order by r.created_at desc limit :lim"
                    ),
                    {"tid": traveler_id, "lim": limit},
                )
            ).all()
        out = []
        for r in rows:
            package = await self._package(str(r.package_id))
            out.append(_reservation_brief(str(r.id), package, r.start_date, r.end_date))
        return out

    async def create_handoff(self, traveler_id: str | None, reason: str, summary: str) -> str:
        handoff_id = uuid.uuid4()
        async with self.engine.begin() as conn:
            if traveler_id:
                await conn.execute(
                    text("insert into travelers (id) values (:tid) on conflict (id) do nothing"),
                    {"tid": traveler_id},
                )
            await conn.execute(
                text(
                    "insert into handoffs (id, traveler_id, reason, summary) "
                    "values (:id, :tid, :reason, :summary)"
                ),
                {"id": handoff_id, "tid": traveler_id, "reason": reason, "summary": summary},
            )
        return str(handoff_id)

    async def save_quote(self, quote: Quote) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("insert into travelers (id) values (:tid) on conflict (id) do nothing"),
                {"tid": quote.traveler_id},
            )
            await conn.execute(
                text(
                    "insert into quotes (id, traveler_id, package_id, start_date, end_date, "
                    "travelers, lines, total_amount, currency, expires_at) values (:id, :tid, "
                    ":pid, :start, :end, :n, cast(:lines as jsonb), :total, :cur, :exp)"
                ),
                {
                    "id": uuid.UUID(quote.quote_id),
                    "tid": quote.traveler_id,
                    "pid": uuid.UUID(quote.package.id),
                    "start": quote.start_date,
                    "end": quote.end_date,
                    "n": quote.travelers,
                    "lines": json.dumps(quote.lines, ensure_ascii=False),
                    "total": quote.total_amount,
                    "cur": quote.currency,
                    "exp": quote.expires_at,
                },
            )

    async def quoted_amounts(self, since: datetime) -> set[int]:
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text("select total_amount, lines from quotes where expires_at >= :since"),
                {"since": since},
            )
            out: set[int] = set()
            for total, lines in rows:
                out |= _quote_amounts(
                    total, lines if isinstance(lines, list) else json.loads(lines)
                )
            return out

    async def get_quote(self, quote_id: str) -> Quote | None:
        qid = _as_uuid(quote_id)
        if qid is None:
            return None
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "select id, traveler_id, package_id, start_date, end_date, travelers, "
                        "lines, total_amount, currency, expires_at from quotes where id = :id"
                    ),
                    {"id": qid},
                )
            ).first()
        if row is None:
            return None
        lines = row.lines if isinstance(row.lines, list) else json.loads(row.lines)
        return Quote(
            quote_id=str(row.id),
            traveler_id=row.traveler_id,
            package=await self._package(str(row.package_id)),
            start_date=row.start_date,
            end_date=row.end_date,
            travelers=row.travelers,
            lines=lines,
            total_amount=int(row.total_amount),
            currency=row.currency,
            expires_at=row.expires_at,
        )

    async def insert_reservation(self, reservation: Reservation) -> tuple[Reservation, bool]:
        params = {
            "id": uuid.UUID(reservation.reservation_id),
            "tid": reservation.traveler_id,
            "qid": uuid.UUID(reservation.quote_id),
            "key": reservation.idempotency_key,
            "status": reservation.status,
            "total": reservation.total_amount,
            "cur": reservation.currency,
            "commission": reservation.commission_amount,
        }
        async with self.engine.begin() as conn:
            created = (
                await conn.execute(
                    text(
                        "insert into reservations (id, traveler_id, quote_id, idempotency_key, "
                        "status, total_amount, currency, commission_amount) values (:id, :tid, "
                        ":qid, :key, :status, :total, :cur, :commission) "
                        "on conflict do nothing returning id"
                    ),
                    params,
                )
            ).first()
        if created is not None:
            return reservation, True
        # one booking per quote (unique quote_id) and per key (unique idempotency_key)
        existing = await self.find_reservation_for_quote(
            reservation.quote_id
        ) or await self.find_reservation_by_key(reservation.idempotency_key)
        if existing is None:  # pragma: no cover - conflict row vanished (deleted concurrently)
            raise RuntimeError("idempotency conflict without a stored reservation")
        return existing, False

    async def find_reservation_by_key(self, idempotency_key: str) -> Reservation | None:
        return await self._find_reservation("idempotency_key = :v", idempotency_key)

    async def find_reservation_for_quote(self, quote_id: str) -> Reservation | None:
        qid = _as_uuid(quote_id)
        return await self._find_reservation("quote_id = :v", qid) if qid else None

    async def _find_reservation(self, where: str, value: object) -> Reservation | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "select id, traveler_id, quote_id, idempotency_key, status, total_amount, "
                        "currency, commission_amount from reservations where " + where
                    ),
                    {"v": value},
                )
            ).first()
        if row is None:
            return None
        return Reservation(
            reservation_id=str(row.id),
            traveler_id=row.traveler_id,
            quote_id=str(row.quote_id),
            idempotency_key=row.idempotency_key,
            status=row.status,
            total_amount=int(row.total_amount),
            currency=row.currency,
            commission_amount=int(row.commission_amount),
        )

    async def delete_test_travelers(self, ids: list[str] | None) -> int:
        # profiles, quotes, reservations and handoffs cascade from travelers
        async with self.engine.begin() as conn:
            if ids is None:
                result = await conn.execute(
                    text("delete from travelers where id like :p"), {"p": TEST_PREFIX + "%"}
                )
            else:
                result = await conn.execute(
                    text("delete from travelers where id = any(:ids)"), {"ids": _test_ids(ids)}
                )
        return int(result.rowcount or 0)

    async def test_state(self, ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        async with self.engine.connect() as conn:
            for tid in _test_ids(ids):
                quotes = [
                    {
                        "id": str(r.id),
                        "package_id": str(r.package_id),
                        "start_date": r.start_date.isoformat(),
                        "end_date": r.end_date.isoformat(),
                        "travelers": r.travelers,
                        "lines": r.lines if isinstance(r.lines, list) else json.loads(r.lines),
                        "total_amount": int(r.total_amount),
                    }
                    for r in await conn.execute(
                        text(
                            "select id, package_id, start_date, end_date, travelers, lines, "
                            "total_amount from quotes where traveler_id = :tid"
                        ),
                        {"tid": tid},
                    )
                ]
                reservations = [
                    {
                        "quote_id": str(r.quote_id),
                        "idempotency_key": r.idempotency_key,
                        "status": r.status,
                    }
                    for r in await conn.execute(
                        text(
                            "select quote_id, idempotency_key, status from reservations "
                            "where traveler_id = :tid"
                        ),
                        {"tid": tid},
                    )
                ]
                prof = (
                    await conn.execute(
                        text(
                            "select consent_personalization, attributes, persona_prompt "
                            "from traveler_profiles where traveler_id = :tid"
                        ),
                        {"tid": tid},
                    )
                ).first()
                handoffs = (
                    await conn.execute(
                        text("select count(*) from handoffs where traveler_id = :tid"),
                        {"tid": tid},
                    )
                ).scalar_one()
                out[tid] = {
                    "quotes": quotes,
                    "reservations": reservations,
                    "profile": None
                    if prof is None
                    else {
                        "consent_personalization": prof.consent_personalization,
                        "attributes": prof.attributes
                        if isinstance(prof.attributes, dict)
                        else json.loads(prof.attributes),
                        "persona_prompt": prof.persona_prompt,
                    },
                    "handoffs": int(handoffs),
                }
        return out

    async def delete_profile(self, traveler_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("delete from traveler_profiles where traveler_id = :tid"), {"tid": traveler_id}
            )

    async def close(self) -> None:
        await self.engine.dispose()


__all__ = [
    "CURRENCY",
    "MemoryRepository",
    "PostgresRepository",
    "Profile",
    "Quote",
    "Repository",
    "Reservation",
    "catalog_packages",
]
