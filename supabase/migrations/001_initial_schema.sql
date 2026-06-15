-- AI Usage Tracker — Initial Schema
-- Providers: store connected AI API providers
-- Usage Records: raw token metrics per sync
-- Cost Entries: computed cost per record
-- Pricing Snapshots: historical pricing for accurate cost calculation

-- ============================================================
-- EXTENSIONS
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- TABLE: providers
-- ============================================================
CREATE TABLE providers (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,          -- 'anthropic', 'openai', etc.
    api_key_ref TEXT,                           -- encrypted label for the stored key
    enabled     BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TABLE: pricing_snapshots
-- Stores the per-model pricing at a point in time so cost
-- calculations are historically accurate even if prices change.
-- ============================================================
CREATE TABLE pricing_snapshots (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id           UUID NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model                 TEXT NOT NULL,          -- e.g. 'claude-sonnet-4-20250514'
    model_display_name    TEXT,                   -- e.g. 'Claude Sonnet 4'
    input_price_per_m     NUMERIC(10,6) NOT NULL, -- $ per 1M input tokens
    output_price_per_m    NUMERIC(10,6) NOT NULL, -- $ per 1M output tokens
    cache_write_price_per_m NUMERIC(10,6),        -- $ per 1M cache write tokens (nullable)
    cache_read_price_per_m  NUMERIC(10,6),        -- $ per 1M cache read tokens (nullable)
    effective_from        DATE NOT NULL,
    effective_until       DATE,                   -- NULL = currently active
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT unique_pricing UNIQUE (provider_id, model, effective_from)
);

-- ============================================================
-- TABLE: usage_records
-- Raw token usage pulled from provider APIs.
-- One row = one sync interval's data for one model.
-- ============================================================
CREATE TABLE usage_records (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id         UUID NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model               TEXT NOT NULL,
    input_tokens        BIGINT NOT NULL DEFAULT 0,
    output_tokens       BIGINT NOT NULL DEFAULT 0,
    cache_write_tokens  BIGINT NOT NULL DEFAULT 0,
    cache_read_tokens   BIGINT NOT NULL DEFAULT 0,
    recorded_at         DATE NOT NULL,            -- the date this usage applies to
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_response        JSONB,                    -- raw API response for audit
    sync_batch_id       UUID,                     -- groups records from the same sync run
    CONSTRAINT unique_usage UNIQUE (provider_id, model, recorded_at)
);

-- ============================================================
-- TABLE: cost_entries
-- Computed cost per usage record. Separated so we can
-- recalculate independently if pricing changes.
-- ============================================================
CREATE TABLE cost_entries (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usage_record_id     UUID NOT NULL REFERENCES usage_records(id) ON DELETE CASCADE,
    provider_id         UUID NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model               TEXT NOT NULL,
    input_cost          NUMERIC(12,6) NOT NULL DEFAULT 0,
    output_cost         NUMERIC(12,6) NOT NULL DEFAULT 0,
    cache_write_cost    NUMERIC(12,6) NOT NULL DEFAULT 0,
    cache_read_cost     NUMERIC(12,6) NOT NULL DEFAULT 0,
    total_cost          NUMERIC(12,6) NOT NULL DEFAULT 0,
    currency            TEXT NOT NULL DEFAULT 'USD',
    date                DATE NOT NULL,
    pricing_snapshot_id UUID REFERENCES pricing_snapshots(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT unique_cost_entry UNIQUE (usage_record_id)
);

-- ============================================================
-- TABLE: sync_log
-- Tracks sync execution runs for observability.
-- ============================================================
CREATE TABLE sync_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id     UUID REFERENCES providers(id),
    status          TEXT NOT NULL DEFAULT 'running',  -- 'running', 'success', 'failed'
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    records_fetched INTEGER DEFAULT 0,
    error_message   TEXT,
    sync_batch_id   UUID
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_usage_records_provider_date ON usage_records (provider_id, recorded_at DESC);
CREATE INDEX idx_usage_records_model ON usage_records (model);
CREATE INDEX idx_cost_entries_date ON cost_entries (date DESC);
CREATE INDEX idx_cost_entries_provider_date ON cost_entries (provider_id, date DESC);
CREATE INDEX idx_pricing_snapshots_active ON pricing_snapshots (provider_id, model, effective_from DESC);
CREATE INDEX idx_sync_log_provider ON sync_log (provider_id, started_at DESC);

-- ============================================================
-- AUTO-UPDATE updated_at TRIGGER
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_providers_updated_at
    BEFORE UPDATE ON providers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- ROW LEVEL SECURITY (multi-provider isolation ready)
-- ============================================================
ALTER TABLE providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE pricing_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_log ENABLE ROW LEVEL SECURITY;

-- Default policy: only authenticated users can read
CREATE POLICY "authenticated_read_providers" ON providers
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_read_usage" ON usage_records
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_read_costs" ON cost_entries
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_read_pricing" ON pricing_snapshots
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_read_sync_log" ON sync_log
    FOR SELECT USING (auth.role() = 'authenticated');
