from __future__ import annotations

import pytest

from andes.core.enums import Channel, ConsentPurpose, Intent
from andes.core.schemas import MessageEnvelope

langgraph = pytest.importorskip("langgraph")

from andes.agents.graph import GraphRunner  # noqa: E402


def _env(traveler_id, text):
    return MessageEnvelope(traveler_id=traveler_id, channel=Channel.WEB, text=text)


def test_graph_greeting(assistant, traveler_id):
    runner = GraphRunner(assistant)
    reply = runner.run(_env(traveler_id, "hola"))
    assert reply.intent == Intent.GREETING


def test_graph_recommend(assistant, traveler_id, grant_consents):
    grant_consents(traveler_id, ConsentPurpose.PERSONALIZATION)
    runner = GraphRunner(assistant)
    reply = runner.run(_env(traveler_id, "recomiéndame playa en familia"))
    assert reply.intent == Intent.RECOMMEND
    assert reply.recommendations


def test_graph_full_flow(assistant, traveler_id, grant_consents):
    grant_consents(traveler_id)
    runner = GraphRunner(assistant)
    runner.run(_env(traveler_id, "hola"))
    quote = runner.run(_env(traveler_id, "cotiza Cartagena para 2"))
    assert quote.quote is not None
    book = runner.run(_env(traveler_id, "quiero reservar"))
    assert book.reservation is not None


def test_graph_matches_assistant_intent(assistant, traveler_id):
    runner = GraphRunner(assistant)
    text = "quiero hablar con un asesor"
    via_graph = runner.run(_env(traveler_id, text))
    via_assistant = assistant.turn(_env(traveler_id, text))
    assert via_graph.intent == via_assistant.intent
