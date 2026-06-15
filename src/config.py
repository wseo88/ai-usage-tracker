"""Configuration management via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────
    app_name: str = "AI Usage Tracker"
    debug: bool = False
    log_level: str = "INFO"

    # ── Supabase ─────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_key: str = ""

    # ── Anthropic ────────────────────────────────────────────────
    anthropic_admin_api_key: str = ""

    # ── CORS ─────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
