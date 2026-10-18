from __future__ import annotations

from andes.channels import ADAPTERS
from andes.channels.base import traveler_id_from
from andes.channels.text import EmailAdapter, SmsAdapter
from andes.channels.voice import VoiceAdapter
from andes.channels.web import WebAdapter
from andes.channels.whatsapp import WhatsAppAdapter
from andes.core.enums import Channel


def test_traveler_id_from_is_stable():
    assert traveler_id_from("+57 300 000 0000") == traveler_id_from("+57 300 000 0000")
    assert traveler_id_from("a@b.com") != traveler_id_from("c@d.com")


def test_web_adapter_parse_and_render():
    adapter = WebAdapter()
    envelope = adapter.parse({"text": "hola", "handle": "web-1"})
    assert envelope.channel == Channel.WEB
    assert envelope.text == "hola"
    assert adapter.address({"handle": "web-1"}) == "web-1"


def test_whatsapp_adapter_parse():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "573001112233",
                                    "id": "wamid.1",
                                    "type": "text",
                                    "text": {"body": "quiero viajar a Cartagena"},
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }
    adapter = WhatsAppAdapter()
    envelope = adapter.parse(payload)
    assert envelope.channel == Channel.WHATSAPP
    assert envelope.text == "quiero viajar a Cartagena"
    assert adapter.address(payload) == "573001112233"
    rendered = adapter.render(_reply(), "573001112233")
    assert rendered["messaging_product"] == "whatsapp"
    assert rendered["to"] == "573001112233"


def test_voice_adapter_parse_and_twiml():
    payload = {"From": "+573004445566", "SpeechResult": "hola quiero reservar"}
    adapter = VoiceAdapter()
    envelope = adapter.parse(payload)
    assert envelope.channel == Channel.VOICE
    twiml = adapter.render(_reply(), payload["From"])
    assert twiml.startswith("<?xml")
    assert "<Say" in twiml


def test_text_adapters():
    for adapter_cls, channel in ((EmailAdapter, Channel.EMAIL), (SmsAdapter, Channel.SMS)):
        adapter = adapter_cls()
        envelope = adapter.parse({"from": "a@b.com", "text": "hola"})
        assert envelope.channel == channel
        assert adapter.render(_reply(), "a@b.com")["body"]


def test_registry_covers_all_channels():
    assert set(ADAPTERS) == {"web", "whatsapp", "voice", "email", "sms"}


def _reply():
    from andes.agents.assistant import AssistantReply
    from andes.core.enums import Intent

    return AssistantReply(text="Hola viajero", intent=Intent.GREETING)
