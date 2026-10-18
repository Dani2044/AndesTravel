from __future__ import annotations

from andes.analytics.metrics import compute_funnel


def test_handle_web_greeting(conversation):
    result = conversation.handle("web", {"text": "hola", "handle": "web-1"})
    assert result["intent"] == "greeting"


def test_handle_emits_turn_event(conversation, events):
    conversation.handle("web", {"text": "hola", "handle": "web-1"})
    metrics = compute_funnel(events.events())
    assert metrics.turns == 1


def test_handle_full_funnel(conversation, events):
    handle = "web-flow"
    conversation.handle("web", {"text": "recomiéndame playa", "handle": handle})
    conversation.handle("web", {"text": "cotiza Cartagena para 2", "handle": handle})
    conversation.handle("web", {"text": "quiero reservar", "handle": handle})
    metrics = compute_funnel(events.events())
    assert metrics.quotes == 1
    assert metrics.reservations == 1


def test_handle_voice_returns_twiml(conversation):
    result = conversation.handle("voice", {"From": "+5730011", "SpeechResult": "hola"})
    assert isinstance(result, str)
    assert result.startswith("<?xml")


def test_handle_whatsapp(conversation):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "57300", "type": "text", "text": {"body": "hola"}}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    result = conversation.handle("whatsapp", payload)
    assert result["messaging_product"] == "whatsapp"
