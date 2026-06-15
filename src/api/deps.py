"""FastAPI dependency injection — Supabase DB client."""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from supabase import Client

from src.database import get_db


async def get_supabase() -> AsyncGenerator[Optional[Client], None]:
    """Yield the Supabase client or None if not configured."""
    try:
        db = get_db()
    except RuntimeError:
        db = None
    yield db
