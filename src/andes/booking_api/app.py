"""FastAPI app exposing the mock business systems over HTTP."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from andes.booking_api.store import get_store

app = FastAPI(title="AndesTravel Booking API (mock)", version="0.1.0")


class AvailabilityRequest(BaseModel):
    package_id: str
    start_date: str
    end_date: str
    travelers: int


class QuoteRequest(BaseModel):
    package_id: str
    travelers: int
    start_date: str
    end_date: str
    options: dict | None = None


class ReservationRequest(BaseModel):
    quote_id: str
    traveler_id: str
    idempotency_key: str
    payment: dict | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/availability")
def availability(package_id: str, start_date: str, end_date: str, travelers: int) -> dict:
    return get_store().availability(package_id, start_date, end_date, travelers)


@app.post("/quotes")
def create_quote(req: QuoteRequest) -> dict:
    return get_store().quote(
        req.package_id, req.travelers, req.start_date, req.end_date, req.options
    )


@app.post("/reservations")
def create_reservation(req: ReservationRequest) -> dict:
    return get_store().create_reservation(
        req.quote_id, req.traveler_id, req.idempotency_key, req.payment
    )
