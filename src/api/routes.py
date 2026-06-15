"""FastAPI router — all /api/v1 endpoints."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from supabase import Client

from src.api.deps import get_supabase
from src.api.schemas import (
    APIResponse,
    DailyDataPoint,
    ModelBreakdown,
    ProviderInfo,
    SummaryResponse,
    SyncInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Dashboard"])


# ── Helpers ───────────────────────────────────────────────────


def _ok(data: Any) -> APIResponse:
    return APIResponse(data=data, error=None)


def _err(message: str) -> APIResponse:
    return APIResponse(data=None, error=message)


def _date_range(days: int) -> tuple[str, str]:
    """Return (start_date, end_date) ISO strings for last N days."""
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


# ── 1. Summary ────────────────────────────────────────────────


@router.get("/summary", response_model=APIResponse[SummaryResponse])
async def get_summary(
    period: str = Query("month", description="Aggregation period: day, week, month, all"),
    db: Client | None = Depends(get_supabase),
) -> APIResponse[SummaryResponse]:
    """Aggregated totals: cost, tokens, record count for the given period."""
    if db is None:
        return _err("Supabase not configured")

    today = date.today()
    if period == "day":
        start_date = today.isoformat()
    elif period == "week":
        start_date = (today - timedelta(days=7)).isoformat()
    elif period == "month":
        start_date = (today - timedelta(days=30)).isoformat()
    elif period == "all":
        start_date = "1970-01-01"
    else:
        return _err(f"Invalid period '{period}'. Use: day, week, month, all")

    end_date = today.isoformat()

    try:
        resp = (
            db.table("cost_entries")
            .select("total_cost, input_cost, output_cost, cache_write_cost, cache_read_cost, date")
            .gte("date", start_date)
            .lte("date", end_date)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to query cost_entries: %s", exc)
        return _err("Failed to query cost data")

    costs = resp.data or []

    total_cost = 0.0
    for c in costs:
        total_cost += float(c.get("total_cost", 0))

    # Get token totals from usage_records for the same period
    try:
        usage_resp = (
            db.table("usage_records")
            .select("input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, recorded_at")
            .gte("recorded_at", start_date)
            .lte("recorded_at", end_date)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to query usage_records: %s", exc)
        usage_resp.data = []

    records = usage_resp.data or []
    total_input = sum(int(r.get("input_tokens", 0)) for r in records)
    total_output = sum(int(r.get("output_tokens", 0)) for r in records)
    total_cache_write = sum(int(r.get("cache_write_tokens", 0)) for r in records)
    total_cache_read = sum(int(r.get("cache_read_tokens", 0)) for r in records)

    summary = SummaryResponse(
        total_cost=round(total_cost, 6),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cache_write_tokens=total_cache_write,
        total_cache_read_tokens=total_cache_read,
        period=period,
        record_count=len(costs),
    )
    return _ok(summary)


# ── 2. Daily time series ──────────────────────────────────────


@router.get("/daily", response_model=APIResponse[list[DailyDataPoint]])
async def get_daily(
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    db: Client | None = Depends(get_supabase),
) -> APIResponse[list[DailyDataPoint]]:
    """Daily time series: date, cost, and tokens for the last N days."""
    if db is None:
        return _err("Supabase not configured")

    start_date, end_date = _date_range(days)

    try:
        resp = (
            db.table("cost_entries")
            .select(
                "date, total_cost, "
                "usage_record:usage_record_id(input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)"
            )
            .gte("date", start_date)
            .lte("date", end_date)
            .order("date", desc=False)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to query daily data: %s", exc)
        return _err("Failed to query daily data")

    rows = resp.data or []
    points: list[DailyDataPoint] = []
    for row in rows:
        usage = row.get("usage_record") or {}
        points.append(
            DailyDataPoint(
                date=row["date"] if isinstance(row["date"], date) else date.fromisoformat(row["date"]),
                total_cost=float(row.get("total_cost", 0)),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                cache_write_tokens=int(usage.get("cache_write_tokens", 0)),
                cache_read_tokens=int(usage.get("cache_read_tokens", 0)),
            )
        )

    return _ok(points)


# ── 3. By-model breakdown ─────────────────────────────────────


@router.get("/by-model", response_model=APIResponse[list[ModelBreakdown]])
async def get_by_model(
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    db: Client | None = Depends(get_supabase),
) -> APIResponse[list[ModelBreakdown]]:
    """Cost and token breakdown grouped by model."""
    if db is None:
        return _err("Supabase not configured")

    start_date, end_date = _date_range(days)

    try:
        cost_resp = (
            db.table("cost_entries")
            .select("model, total_cost, input_cost, output_cost, cache_write_cost, cache_read_cost")
            .gte("date", start_date)
            .lte("date", end_date)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to query by-model data: %s", exc)
        return _err("Failed to query model breakdown")

    rows = cost_resp.data or []

    # Aggregate by model in Python
    model_agg: dict[str, dict[str, float]] = {}
    for row in rows:
        model = row.get("model", "unknown")
        if model not in model_agg:
            model_agg[model] = {
                "cost": 0.0,
                "input_tokens": 0.0,
                "output_tokens": 0.0,
            }
        model_agg[model]["cost"] += float(row.get("total_cost", 0))
        model_agg[model]["input_cost"] = model_agg[model].get("input_cost", 0) + float(row.get("input_cost", 0))
        model_agg[model]["output_cost"] = model_agg[model].get("output_cost", 0) + float(row.get("output_cost", 0))

    total_cost = sum(v["cost"] for v in model_agg.values())

    # Get token counts from usage_records by model
    try:
        usage_resp = (
            db.table("usage_records")
            .select("model, input_tokens, output_tokens")
            .gte("recorded_at", start_date)
            .lte("recorded_at", end_date)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to query usage_records for model breakdown: %s", exc)
        usage_resp.data = []

    for row in usage_resp.data or []:
        model = row.get("model", "unknown")
        if model in model_agg:
            model_agg[model]["input_tokens"] += int(row.get("input_tokens", 0))
            model_agg[model]["output_tokens"] += int(row.get("output_tokens", 0))

    # Try to get display names from pricing_snapshots
    try:
        pricing_resp = (
            db.table("pricing_snapshots")
            .select("model, model_display_name")
            .execute()
        )
    except Exception:
        pricing_resp.data = []

    display_names: dict[str, str] = {}
    for row in pricing_resp.data or []:
        if row.get("model_display_name"):
            display_names[row["model"]] = row["model_display_name"]

    breakdown = [
        ModelBreakdown(
            model=model,
            model_display_name=display_names.get(model),
            cost=round(v["cost"], 6),
            input_tokens=int(v["input_tokens"]),
            output_tokens=int(v["output_tokens"]),
            percentage=round((v["cost"] / total_cost * 100) if total_cost > 0 else 0, 2),
        )
        for model, v in sorted(model_agg.items(), key=lambda x: x[1]["cost"], reverse=True)
    ]

    return _ok(breakdown)


# ── 4. Providers ──────────────────────────────────────────────


@router.get("/providers", response_model=APIResponse[list[ProviderInfo]])
async def get_providers(
    db: Client | None = Depends(get_supabase),
) -> APIResponse[list[ProviderInfo]]:
    """List all connected providers with their latest sync status."""
    if db is None:
        return _err("Supabase not configured")

    try:
        prov_resp = (
            db.table("providers")
            .select("*")
            .order("name")
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to query providers: %s", exc)
        return _err("Failed to query providers")

    providers_data = prov_resp.data or []
    result: list[ProviderInfo] = []

    for prov in providers_data:
        provider_id = prov["id"]
        latest_sync_status: str | None = None
        latest_sync_at: str | None = None
        records_fetched: int | None = None

        try:
            sync_resp = (
                db.table("sync_log")
                .select("status, finished_at, records_fetched")
                .eq("provider_id", provider_id)
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )
            if sync_resp.data:
                sync = sync_resp.data[0]
                latest_sync_status = sync.get("status")
                latest_sync_at = sync.get("finished_at")
                records_fetched = sync.get("records_fetched")
        except Exception:
            logger.debug("No sync log for provider %s", provider_id)

        result.append(
            ProviderInfo(
                id=provider_id,
                name=prov["name"],
                slug=prov["slug"],
                enabled=prov.get("enabled", True),
                latest_sync_status=latest_sync_status,
                latest_sync_at=latest_sync_at,
                records_fetched=records_fetched,
            )
        )

    return _ok(result)


# ── 5. Latest sync ────────────────────────────────────────────


@router.get("/latest-sync", response_model=APIResponse[list[SyncInfo]])
async def get_latest_sync(
    provider: str | None = Query(None, description="Filter by provider slug"),
    db: Client | None = Depends(get_supabase),
) -> APIResponse[list[SyncInfo]]:
    """Get the latest sync run per provider (or for a specific provider)."""
    if db is None:
        return _err("Supabase not configured")

    try:
        query = (
            db.table("sync_log")
            .select("*")
            .order("started_at", desc=True)
        )

        if provider:
            # Resolve provider slug to ID
            prov_resp = (
                db.table("providers")
                .select("id, slug, name")
                .eq("slug", provider)
                .limit(1)
                .execute()
            )
            if not prov_resp.data:
                return _err(f"Provider '{provider}' not found")
            prov = prov_resp.data[0]
            query = query.eq("provider_id", prov["id"])

        resp = query.limit(10).execute()
    except Exception as exc:
        logger.error("Failed to query sync log: %s", exc)
        return _err("Failed to query sync log")

    rows = resp.data or []
    syncs: list[SyncInfo] = []
    for row in rows:
        syncs.append(
            SyncInfo(
                provider=row.get("provider_id", ""),
                provider_id=row.get("provider_id", ""),
                status=row.get("status", "unknown"),
                started_at=row.get("started_at"),
                finished_at=row.get("finished_at"),
                records_fetched=row.get("records_fetched"),
                error_message=row.get("error_message"),
                sync_batch_id=row.get("sync_batch_id"),
            )
        )

    # If we didn't filter by provider, resolve provider names
    if not provider and syncs:
        provider_ids = {s.provider_id for s in syncs}
        try:
            prov_resp = (
                db.table("providers")
                .select("id, slug")
                .in_("id", list(provider_ids))
                .execute()
            )
            slug_map = {p["id"]: p["slug"] for p in (prov_resp.data or [])}
            for s in syncs:
                s.provider = slug_map.get(s.provider_id, s.provider)
        except Exception:
            pass

    return _ok(syncs)


# ── Explicit OPTIONS handler for CORS preflight ───────────────
# FastAPI handles OPTIONS via CORSMiddleware, but we add this
# as a safety net for any preflight requests that might bypass it.


@router.options("/{full_path:path}")
async def options_handler():
    """Handle CORS preflight requests."""
    from fastapi.responses import Response
    return Response(status_code=204)
