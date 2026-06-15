"""Supabase client initialization and helpers."""

from __future__ import annotations

from supabase import Client, create_client

from src.config import settings

_client: Client | None = None


def get_db() -> Client:
    """Get or create the Supabase client singleton."""
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError(
                "Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY."
            )
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client
