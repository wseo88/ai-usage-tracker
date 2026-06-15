"""Anthropic Usage API client.

Polls the Anthropic Usage & Cost API and stores results in Supabase.

API docs: https://platform.claude.com/docs/en/manage-claude/usage-cost-api
Uses the /v1/organizations/usage_report/messages endpoint.
Requires an Admin API key (sk-ant-admin...), not a regular API key.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

from src.config import settings
from src.database import get_db

logger = logging.getLogger(__name__)

ANTHROPIC_USAGE_URL = "https://api.anthropic.com/v1/organizations/usage_report/messages"
DEFAULT_DAYS = 7

# Fallback pricing (USD per 1M tokens), used if pricing_snapshots is unavailable.
FALLBACK_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-20250514": {
        "input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.5
    },
    "claude-sonnet-4-20250514": {
        "input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.3
    },
    "claude-3-5-sonnet-20241022": {
        "input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.3
    },
    "claude-3-5-haiku-20241022": {
        "input": 0.8, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08
    },
    "claude-3-haiku-20240307": {
        "input": 0.25, "output": 1.25, "cache_write": 0.3, "cache_read": 0.025
    },
}


class AnthropicSyncError(Exception):
    """Raised when Anthropic sync fails."""


def _get_headers() -> dict[str, str]:
    if not settings.anthropic_admin_api_key:
        raise AnthropicSyncError("ANTHROPIC_ADMIN_API_KEY is not configured")

    return {
        "x-api-key": settings.anthropic_admin_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "User-Agent": "ai-usage-tracker/0.1.0 (https://github.com/wseo88/ai-usage-tracker)",
    }


def _get_pricing_from_db() -> dict[str, dict[str, float]]:
    """Query pricing_snapshots from Supabase as the primary pricing source.

    Returns a dict like FALLBACK_PRICING, keyed by model. Falls back to
    FALLBACK_PRICING if the DB is unreachable or has no data.
    """
    try:
        db = get_db()
        resp = (
            db.table("pricing_snapshots")
            .select(
                "model, input_price_per_m, output_price_per_m, "
                "cache_write_price_per_m, cache_read_price_per_m"
            )
            .is_("effective_until", "null")
            .execute()
        )

        if not resp.data:
            logger.info("No active pricing snapshots in DB, using fallback pricing")
            return dict(FALLBACK_PRICING)

        prices: dict[str, dict[str, float]] = {}
        for row in resp.data:
            prices[row["model"]] = {
                "input": float(row.get("input_price_per_m", 0)),
                "output": float(row.get("output_price_per_m", 0)),
                "cache_write": float(row.get("cache_write_price_per_m", 0) or 0),
                "cache_read": float(row.get("cache_read_price_per_m", 0) or 0),
            }
        return prices
    except Exception:
        logger.warning("Failed to query pricing_snapshots, using fallback pricing", exc_info=True)
        return dict(FALLBACK_PRICING)


def fetch_usage(start_date: date, end_date: date) -> list[dict[str, Any]]:
    """Fetch usage data from the Anthropic Usage API for a date range.

    Uses the /v1/organizations/usage_report/messages endpoint with
    bucket_width=1d and group_by=model. Handles pagination automatically.

    Returns a list of parsed usage buckets, each containing tokens by model.
    """
    logger.info("Fetching Anthropic usage %s to %s ...", start_date, end_date)

    params = {
        "starting_at": start_date.isoformat() + "T00:00:00Z",
        "ending_at": end_date.isoformat() + "T23:59:59Z",
        "bucket_width": "1d",
        "group_by[]": "model",
    }

    all_buckets: list[dict[str, Any]] = []
    page = None

    with httpx.Client(timeout=60.0) as client:
        while True:
            current_params = dict(params)
            if page:
                current_params["page"] = page

            response = client.get(
                ANTHROPIC_USAGE_URL, headers=_get_headers(), params=current_params
            )

            if response.status_code == 403:
                raise AnthropicSyncError(
                    "403 Forbidden — your API key may not have admin access. "
                    "Use an Admin API key (sk-ant-admin...) from console.anthropic.com/settings/keys"
                )
            if response.status_code == 401:
                raise AnthropicSyncError("401 Unauthorized — check your ANTHROPIC_ADMIN_API_KEY")
            if response.status_code == 429:
                raise AnthropicSyncError("429 Rate limited — try again later")
            if response.status_code != 200:
                raise AnthropicSyncError(
                    f"Anthropic API returned {response.status_code}: {response.text[:500]}"
                )

            data = response.json()
            all_buckets.extend(data.get("data", []))

            if not data.get("has_more"):
                break

            page = data.get("next_page")
            if not page:
                break

            logger.info("Fetching next page of usage data...")

    return _flatten_buckets(all_buckets)


def _flatten_buckets(buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten grouped API response into per-model-per-day records.

    The API returns time buckets, each containing results for each model.
    This flattens them into individual records we can upsert.
    """
    records: list[dict[str, Any]] = []

    for bucket in buckets:
        bucket_date_str = bucket.get("starting_at", "")
        if not bucket_date_str:
            continue

        try:
            bucket_date = date.fromisoformat(bucket_date_str[:10])
        except (ValueError, TypeError):
            logger.warning("Invalid date in bucket: %s", bucket_date_str)
            continue

        results = bucket.get("results", [])
        for result in results:
            model = result.get("model") or "unknown"
            token_counts = result.get("token_counts", {})

            input_tokens = token_counts.get("uncached_input", 0) + token_counts.get(
                "cached_input", 0
            )
            output_tokens = token_counts.get("output", 0)
            cache_write_tokens = token_counts.get("cache_creation", 0)
            cache_read_tokens = (
                token_counts.get("cached_input", 0) if "cached_input" in token_counts else 0
            )

            records.append(
                {
                    "date": bucket_date,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_write_tokens": cache_write_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "raw": result,
                }
            )

    return records


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int,
    cache_read_tokens: int,
    pricing: dict[str, dict[str, float]] | None = None,
) -> dict[str, float]:
    """Calculate cost in USD for a given model and token counts.

    Uses the provided pricing dict (from DB), falling back to FALLBACK_PRICING.
    """
    prices = (pricing or FALLBACK_PRICING).get(
        model, FALLBACK_PRICING.get("claude-sonnet-4-20250514", {})
    )

    return {
        "input_cost": round(input_tokens / 1_000_000 * prices.get("input", 0), 6),
        "output_cost": round(output_tokens / 1_000_000 * prices.get("output", 0), 6),
        "cache_write_cost": round(cache_write_tokens / 1_000_000 * prices.get("cache_write", 0), 6),
        "cache_read_cost": round(cache_read_tokens / 1_000_000 * prices.get("cache_read", 0), 6),
    }


def sync(days: int = DEFAULT_DAYS) -> dict[str, Any]:
    """Run the Anthropic sync for the last N days.

    1. Fetch usage from Anthropic API
    2. Calculate costs using pricing_snapshots from DB
    3. Upsert into Supabase
    """
    db = get_db()

    provider_resp = (
        db.table("providers").select("id", "enabled").eq("slug", "anthropic").execute()
    )
    if not provider_resp.data:
        raise AnthropicSyncError("Anthropic provider not found in database. Run seed.sql first.")

    provider = provider_resp.data[0]
    if not provider.get("enabled", True):
        logger.warning("Anthropic provider is disabled — skipping sync")
        return {"status": "skipped", "reason": "provider disabled"}

    provider_id = provider["id"]
    sync_batch_id = str(uuid4())

    sync_log_resp = (
        db.table("sync_log")
        .insert(
            {
                "provider_id": provider_id,
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
                "sync_batch_id": sync_batch_id,
            }
        )
        .execute()
    )
    sync_log_id = sync_log_resp.data[0]["id"] if sync_log_resp.data else None

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    pricing = _get_pricing_from_db()

    try:
        usage_data = fetch_usage(start_date, end_date)

        records_inserted = 0
        for record in usage_data:
            model = record["model"]
            bucket_date = record["date"]
            input_tokens = record["input_tokens"]
            output_tokens = record["output_tokens"]
            cache_write = record["cache_write_tokens"]
            cache_read = record["cache_read_tokens"]

            costs = calculate_cost(
                model, input_tokens, output_tokens, cache_write, cache_read, pricing
            )
            total_cost = round(sum(costs.values()), 6)

            usage_payload = {
                "provider_id": provider_id,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_write_tokens": cache_write,
                "cache_read_tokens": cache_read,
                "recorded_at": bucket_date.isoformat(),
                "raw_response": record["raw"],
                "sync_batch_id": sync_batch_id,
            }

            usage_resp = (
                db.table("usage_records")
                .upsert(usage_payload, on_conflict="provider_id, model, recorded_at")
                .execute()
            )
            if not usage_resp.data:
                continue

            usage_id = usage_resp.data[0]["id"]
            records_inserted += 1

            cost_payload = {
                "usage_record_id": usage_id,
                "provider_id": provider_id,
                "model": model,
                "input_cost": costs["input_cost"],
                "output_cost": costs["output_cost"],
                "cache_write_cost": costs["cache_write_cost"],
                "cache_read_cost": costs["cache_read_cost"],
                "total_cost": total_cost,
                "currency": "USD",
                "date": bucket_date.isoformat(),
            }

            db.table("cost_entries").upsert(cost_payload, on_conflict="usage_record_id").execute()

        if sync_log_id:
            db.table("sync_log").update(
                {
                    "status": "success",
                    "finished_at": datetime.utcnow().isoformat(),
                    "records_fetched": records_inserted,
                }
            ).eq("id", sync_log_id).execute()

        logger.info("Anthropic sync complete: %d records for %d days", records_inserted, days)

        return {
            "status": "success",
            "provider": "anthropic",
            "days_synced": days,
            "records_inserted": records_inserted,
            "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "sync_batch_id": sync_batch_id,
        }

    except AnthropicSyncError as e:
        if sync_log_id:
            db.table("sync_log").update(
                {
                    "status": "failed",
                    "finished_at": datetime.utcnow().isoformat(),
                    "error_message": str(e),
                }
            ).eq("id", sync_log_id).execute()
        raise
