"""Shared catalog seed data.

Used by both the mock business API (availability, rates, reservations) and the
knowledge ingestor (RAG index), so the two never drift apart.
"""

from __future__ import annotations

from typing import TypedDict


class SeedPackage(TypedDict):
    id: str
    destination: str
    name: str
    description: str
    duration_days: int
    tags: list[str]
    base_rate: int


CATALOG: list[SeedPackage] = [
    {
        "id": "11111111-1111-1111-1111-111111111101",
        "destination": "Eje Cafetero",
        "name": "Café y montaña en familia",
        "description": (
            "Recorrido por fincas cafeteras, termales y miradores de Salento y "
            "Valle de Cocora. Ideal para familias con niños. Clima templado de montaña."
        ),
        "duration_days": 5,
        "tags": ["familia", "montaña", "café", "naturaleza"],
        "base_rate": 5_200_000,
    },
    {
        "id": "11111111-1111-1111-1111-111111111102",
        "destination": "Cartagena",
        "name": "Caribe histórico en familia",
        "description": (
            "Ciudad amurallada, playas de Bocagrande e islas del Rosario. "
            "Plan familiar con actividades para todas las edades y playa."
        ),
        "duration_days": 4,
        "tags": ["familia", "playa", "cultura", "caribe"],
        "base_rate": 4_800_000,
    },
    {
        "id": "11111111-1111-1111-1111-111111111103",
        "destination": "San Andrés",
        "name": "Paraíso de arrecifes",
        "description": (
            "Buceo, snorkel y playas de arena blanca. Escapada de playa para "
            "parejas y viajeros que buscan descanso junto al mar."
        ),
        "duration_days": 5,
        "tags": ["playa", "pareja", "buceo", "mar"],
        "base_rate": 6_500_000,
    },
    {
        "id": "11111111-1111-1111-1111-111111111104",
        "destination": "Amazonía",
        "name": "Selva y comunidades",
        "description": (
            "Expedición de ecoturismo por el río Amazonas, avistamiento de fauna "
            "y visita a comunidades locales. Aventura y naturaleza."
        ),
        "duration_days": 6,
        "tags": ["aventura", "ecoturismo", "selva", "naturaleza"],
        "base_rate": 7_200_000,
    },
    {
        "id": "11111111-1111-1111-1111-111111111105",
        "destination": "Tayrona",
        "name": "Playas y senderos",
        "description": (
            "Parque Nacional Tayrona: playas, caminatas y campamento. "
            "Aventura y playa para viajeros activos."
        ),
        "duration_days": 4,
        "tags": ["aventura", "playa", "senderismo", "naturaleza"],
        "base_rate": 3_900_000,
    },
    {
        "id": "11111111-1111-1111-1111-111111111106",
        "destination": "Caño Cristales",
        "name": "El río de los cinco colores",
        "description": (
            "Temporada del río de colores en la Macarena. Ecoturismo y aventura "
            "con senderos, saltos y paisajes únicos."
        ),
        "duration_days": 4,
        "tags": ["ecoturismo", "aventura", "naturaleza"],
        "base_rate": 5_600_000,
    },
    {
        "id": "11111111-1111-1111-1111-111111111107",
        "destination": "Medellín",
        "name": "Ciudad de la eterna primavera",
        "description": (
            "Cultura, historia y gastronomía paisa. Recorridos urbanos, comuna 13 "
            "y planes de ciudad."
        ),
        "duration_days": 3,
        "tags": ["cultural", "ciudad", "gastronomía"],
        "base_rate": 2_800_000,
    },
    {
        "id": "11111111-1111-1111-1111-111111111108",
        "destination": "Bogotá",
        "name": "Capital cultural",
        "description": ("Museos, Monserrate y centro histórico. Escapada cultural de ciudad."),
        "duration_days": 3,
        "tags": ["cultural", "ciudad", "museos"],
        "base_rate": 2_500_000,
    },
]

COMMISSION_RATE = 0.12


def find_package(package_id: str) -> SeedPackage | None:
    for package in CATALOG:
        if package["id"] == package_id:
            return package
    return None


def find_by_destination(destination: str) -> SeedPackage | None:
    wanted = destination.strip().lower()
    for package in CATALOG:
        if package["destination"].lower() == wanted:
            return package
    return None
