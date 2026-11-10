"""Pure rules of the tools API: ids, dates, packages, prices."""

from __future__ import annotations

from datetime import date

import pytest

from andes.apps.tools_api import logic
from andes.apps.tools_api.logic import DomainError
from andes.apps.tools_api.repository import catalog_packages

TODAY = date(2026, 11, 9)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Ana.Perez@Example.COM ", "ana.perez@example.com"),
        ("3001234567", "+573001234567"),
        ("300 123 4567", "+573001234567"),
        ("573001234567", "+573001234567"),
        ("+1 (415) 555-0100", "+14155550100"),
    ],
)
def test_normalize_traveler_id(raw: str, expected: str) -> None:
    assert logic.normalize_traveler_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "ana", "ana@", "12345", "1023456789", "+12"])
def test_normalize_traveler_id_rejects(raw: str) -> None:
    with pytest.raises(DomainError) as err:
        logic.normalize_traveler_id(raw)
    assert err.value.code == "invalid_traveler_id"


@pytest.mark.parametrize(
    "query", ["11111111-1111-1111-1111-111111111103", "San Andrés", "san andres", "SAN ANDRÉS"]
)
def test_match_package_by_id_name_or_destination(query: str) -> None:
    assert logic.match_package(query, catalog_packages()).destination == "San Andrés"


@pytest.mark.parametrize("query", ["Atlántida", "Marte", "", "Paris"])
def test_match_package_unknown(query: str) -> None:
    with pytest.raises(DomainError) as err:
        logic.match_package(query, catalog_packages())
    assert err.value.code == "unknown_package"


def test_parse_trip_ok() -> None:
    trip = logic.parse_trip("2026-12-01", "2026-12-06", TODAY)
    assert trip.nights == 5


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2027-02-30", "2027-03-03"),  # impossible date
        ("01/12/2026", "06/12/2026"),  # wrong format
        ("2026-11-01", "2026-11-05"),  # in the past
        ("2026-12-06", "2026-12-01"),  # return before departure
        ("2026-12-01", "2026-12-01"),  # zero nights
        ("2026-12-01", "2027-01-15"),  # longer than 30 days
        ("2029-01-01", "2029-01-05"),  # too far ahead
    ],
)
def test_parse_trip_rejects(start: str, end: str) -> None:
    with pytest.raises(DomainError) as err:
        logic.parse_trip(start, end, TODAY)
    assert err.value.code == "invalid_dates"


@pytest.mark.parametrize("n", [0, -1, 21, 3000])
def test_check_travelers_rejects(n: int) -> None:
    with pytest.raises(DomainError) as err:
        logic.check_travelers(n)
    assert err.value.code == "invalid_travelers"


def test_check_duration_is_inclusive() -> None:
    pkg = logic.match_package("Eje Cafetero", catalog_packages())  # 5 days
    logic.check_duration(pkg, logic.parse_trip("2026-12-20", "2026-12-24", TODAY))
    for end in ("2026-12-23", "2026-12-25"):
        with pytest.raises(DomainError) as err:
            logic.check_duration(pkg, logic.parse_trip("2026-12-20", end, TODAY))
        assert err.value.code == "invalid_duration" and "2026-12-24" in err.value.message


def test_quote_lines_multiply_by_travelers() -> None:
    pkg = logic.match_package("Cartagena", catalog_packages())
    lines = logic.quote_lines(pkg, 3, include_insurance=True)
    assert lines[0]["amount"] == pkg.rate_per_person * 3
    assert lines[1]["amount"] == logic.INSURANCE_PER_PERSON * 3
    assert all(line["quantity"] == 3 for line in lines)


def test_merge_attributes_keeps_earlier_facts() -> None:
    previous = {"interests": ["eje cafetero"], "budget_range": "medio"}
    new = {"interests": ["Eje Cafetero", "naturaleza"], "group_size": 3}
    assert logic.merge_attributes(previous, new) == {
        "budget_range": "medio",
        "group_size": 3,
        "interests": ["eje cafetero", "naturaleza"],
    }
    assert logic.merge_attributes({}, {"interests": []}) == {}


def test_persona_prompt_limits() -> None:
    assert logic.clean_persona_prompt("  Viaja   en familia ") == "Viaja en familia"
    assert logic.clean_persona_prompt("   ") is None
    with pytest.raises(DomainError):
        logic.clean_persona_prompt("x" * 601)


@pytest.mark.parametrize(
    "query",
    [
        "Eje Cafetero, Parque del Café",
        "paquete al eje cafetero",
        "Café y montaña en familia (4 pax)",
    ],
)
def test_match_package_accepts_one_destination_with_extras(query: str) -> None:
    assert logic.match_package(query, catalog_packages()).destination == "Eje Cafetero"


def test_match_package_rejects_text_naming_two_destinations() -> None:
    with pytest.raises(DomainError) as err:
        logic.match_package("Cartagena o San Andrés", catalog_packages())
    assert err.value.code == "unknown_package"


def test_local_today_is_bogota_date() -> None:
    from datetime import UTC, datetime

    # 02:00 UTC on Nov 10 is still Nov 9 in Bogotá (UTC-5).
    assert logic.local_today(datetime(2026, 11, 10, 2, 0, tzinfo=UTC)) == date(2026, 11, 9)
    assert logic.local_today(datetime(2026, 11, 10, 6, 0, tzinfo=UTC)) == date(2026, 11, 10)
