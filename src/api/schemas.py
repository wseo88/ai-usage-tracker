"""Pydantic models for API request/response shapes."""

from __future__ import annotations

from datetime import date
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


# ── Envelope ──────────────────────────────────────────────────


class APIResponse(BaseModel, Generic[T]):
    """Consistent JSON envelope for all endpoints."""

    data: T | None = None
    error: str | None = None


# ── Summary ───────────────────────────────────────────────────


class SummaryResponse(BaseModel):
    """Aggregated usage and cost summary."""

    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_write_tokens: int
    total_cache_read_tokens: int
    period: str  # "day", "week", "month", "all"
    record_count: int


# ── Daily time series ─────────────────────────────────────────


class DailyDataPoint(BaseModel):
    """One day of usage/cost data."""

    date: date
    total_cost: float
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int


# ── By-model breakdown ────────────────────────────────────────


class ModelBreakdown(BaseModel):
    """Cost breakdown for a single model."""

    model: str
    model_display_name: str | None = None
    cost: float
    input_tokens: int
    output_tokens: int
    percentage: float


# ── Provider info ─────────────────────────────────────────────


class ProviderInfo(BaseModel):
    """Provider record with latest sync status."""

    id: str
    name: str
    slug: str
    enabled: bool
    latest_sync_status: str | None = None
    latest_sync_at: str | None = None
    records_fetched: int | None = None


# ── Sync info ─────────────────────────────────────────────────


class SyncInfo(BaseModel):
    """Latest sync execution info."""

    provider: str
    provider_id: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    records_fetched: int | None = None
    error_message: str | None = None
    sync_batch_id: str | None = None
