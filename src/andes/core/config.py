"""Application settings, loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "postgresql+asyncpg://andes:andes@localhost:5432/andes"

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"
    llm_provider: Literal["ollama", "fake"] = "ollama"

    embeddings_provider: Literal["fake", "bge-m3"] = "fake"
    embeddings_model: str = "BAAI/bge-m3"
    embeddings_dim: int = 1024

    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "http://localhost:3000"

    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str | None = None
    whatsapp_token: str | None = None
    whatsapp_verify_token: str = "change-me"
    whatsapp_app_secret: str | None = None

    voice_enabled: bool = False
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_phone_number: str | None = None
    deepgram_api_key: str | None = None

    email_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "assistant@andes.travel"

    payments_enabled: bool = False
    wompi_public_key: str | None = None
    wompi_private_key: str | None = None
    wompi_integrity_secret: str | None = None
    wompi_events_secret: str | None = None

    booking_api_url: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
