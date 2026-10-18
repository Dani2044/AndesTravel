# Production Integration Checklist

This project runs and tests entirely offline using mocks. The items below are the only
things that require a human with real accounts/credentials to move from local/demo to
production. Each has a `TODO(human):` marker in the code.

> Never commit real credentials. Provide them through the environment (`op://`,
> `/.env`, or a secret manager) and set `TODO(human)` → done in the corresponding adapter.

## 1. WhatsApp — Meta WhatsApp Cloud API

`src/andes/channels/whatsapp`

1. Create a Meta Business app and add the WhatsApp product.
2. Register the test number and copy: `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TOKEN`.
3. Set `WHATSAPP_VERIFY_TOKEN` (any random string) and configure the webhook URL to
   `POST /whatsapp/webhook` and `GET /whatsapp/webhook` (verification).
4. Subscribe the app to the `messages` field.
5. Set env vars and restart the gateway. Mocks are auto-used when vars are absent.

## 2. Voice — Twilio + faster-whisper + Piper

`src/andes/channels/voice`

1. Create a Twilio account and buy/assign a phone number.
2. Copy `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`.
3. Point the number's voice webhook to `POST /voice`.
4. (Optional) Configure a Deepgram key for higher-quality STT.
5. Set env vars; without them the voice pipeline runs on local audio fixtures.

## 3. Payments — Wompi sandbox

`src/andes/payments/wompi`

1. Create a Wompi sandbox account; copy public/private keys and integrity secret.
2. Set `WOMPI_PUBLIC_KEY`, `WOMPI_PRIVATE_KEY`, `WOMPI_INTEGRITY_SECRET`.
3. Configure the confirmation/event webhook to `POST /webhooks/wompi`
   (`WOMPI_EVENTS_SECRET` verifies the checksum; leave it unset to skip verification locally).
4. Without keys, a deterministic fake charge is used.

## 4. Local LLM — Ollama

1. `brew install ollama` (macOS) or follow the platform instructions.
2. `ollama serve` and `ollama pull qwen2.5:14b`.
3. Set `OLLAMA_HOST` and `OLLAMA_MODEL` if not default.
4. Unit tests use a scripted fake LLM and do not require Ollama.

## 5. Secrets and TLS

- Provide production secrets via a secret manager; never in the repo.
- Terminate TLS at the edge; the gateway listens on HTTP inside the network.
- Rotate the WhatsApp/Twilio/Wompi tokens on a schedule.

## 6. Checklist status

| Item | Owner | Status |
|---|---|---|
| WhatsApp credentials + webhook | TODO(human) | ☐ |
| Twilio number + webhook | TODO(human) | ☐ |
| Wompi sandbox keys | TODO(human) | ☐ |
| Ollama model pulled | dev | ☐ |
| Secrets in manager | TODO(human) | ☐ |
| TLS at edge | TODO(human) | ☐ |
