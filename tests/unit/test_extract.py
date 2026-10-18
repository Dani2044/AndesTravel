from __future__ import annotations

from andes.agents.extract import extract_profile


def test_extract_destination_and_tags():
    profile = extract_profile("quiero viajar a Cartagena con toda la familia")
    assert profile["destination"] == "Cartagena"
    assert "familia" in profile["tags"]


def test_extract_party_size():
    assert extract_profile("somos 4 viajeros")["party"] == 4
    assert extract_profile("viajamos 2 personas")["party"] == 2


def test_extract_budget_millions():
    assert extract_profile("tengo un presupuesto de 6 millones")["budget"] == 6_000_000


def test_extract_empty_text():
    assert extract_profile("hola") == {}


def test_extract_amazonia_destination():
    assert extract_profile("quiero ecoturismo en la Amazonía")["destination"] == "Amazonía"
