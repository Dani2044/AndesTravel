from andes.channels.base import ChannelAdapter, traveler_id_from
from andes.channels.text import EmailAdapter, SmsAdapter
from andes.channels.voice import VoiceAdapter
from andes.channels.web import WebAdapter
from andes.channels.whatsapp import WhatsAppAdapter

ADAPTERS: dict[str, type[ChannelAdapter]] = {
    "web": WebAdapter,
    "whatsapp": WhatsAppAdapter,
    "voice": VoiceAdapter,
    "email": EmailAdapter,
    "sms": SmsAdapter,
}

__all__ = [
    "ChannelAdapter",
    "WebAdapter",
    "WhatsAppAdapter",
    "VoiceAdapter",
    "EmailAdapter",
    "SmsAdapter",
    "ADAPTERS",
    "traveler_id_from",
]
