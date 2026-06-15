-- Seed data: default provider + current pricing snapshots
-- Run after migrations are applied.

-- Insert the Anthropic provider
INSERT INTO providers (name, slug, api_key_ref)
VALUES ('Anthropic', 'anthropic', 'ANTHROPIC_ADMIN_API_KEY')
ON CONFLICT (slug) DO NOTHING;

-- Current Claude model pricing (as of June 2026)
-- Source: https://docs.anthropic.com/en/docs/about-claude/pricing
-- Prices per 1M tokens in USD

-- We assume the Anthropic provider got id from the insert above.
-- Use a DO block to reference by slug rather than hardcoding the UUID.
DO $$
DECLARE
    anthropic_id UUID;
BEGIN
    SELECT id INTO anthropic_id FROM providers WHERE slug = 'anthropic';
    IF anthropic_id IS NULL THEN
        RAISE EXCEPTION 'Anthropic provider not found — seed providers first';
    END IF;

    -- Claude Opus 4
    INSERT INTO pricing_snapshots (provider_id, model, model_display_name, input_price_per_m, output_price_per_m, cache_write_price_per_m, cache_read_price_per_m, effective_from)
    VALUES
        (anthropic_id, 'claude-opus-4-20250514', 'Claude Opus 4', 15.00, 75.00, 18.75, 1.50, '2025-05-14')
    ON CONFLICT (provider_id, model, effective_from) DO NOTHING;

    -- Claude Sonnet 4
    INSERT INTO pricing_snapshots (provider_id, model, model_display_name, input_price_per_m, output_price_per_m, cache_write_price_per_m, cache_read_price_per_m, effective_from)
    VALUES
        (anthropic_id, 'claude-sonnet-4-20250514', 'Claude Sonnet 4', 3.00, 15.00, 3.75, 0.30, '2025-05-14')
    ON CONFLICT (provider_id, model, effective_from) DO NOTHING;

    -- Claude 3.5 Sonnet
    INSERT INTO pricing_snapshots (provider_id, model, model_display_name, input_price_per_m, output_price_per_m, cache_write_price_per_m, cache_read_price_per_m, effective_from)
    VALUES
        (anthropic_id, 'claude-3-5-sonnet-20241022', 'Claude 3.5 Sonnet', 3.00, 15.00, 3.75, 0.30, '2024-10-22')
    ON CONFLICT (provider_id, model, effective_from) DO NOTHING;

    -- Claude 3.5 Haiku
    INSERT INTO pricing_snapshots (provider_id, model, model_display_name, input_price_per_m, output_price_per_m, cache_write_price_per_m, cache_read_price_per_m, effective_from)
    VALUES
        (anthropic_id, 'claude-3-5-haiku-20241022', 'Claude 3.5 Haiku', 0.80, 4.00, 1.00, 0.08, '2024-10-22')
    ON CONFLICT (provider_id, model, effective_from) DO NOTHING;

    -- Claude 3 Haiku
    INSERT INTO pricing_snapshots (provider_id, model, model_display_name, input_price_per_m, output_price_per_m, cache_write_price_per_m, cache_read_price_per_m, effective_from)
    VALUES
        (anthropic_id, 'claude-3-haiku-20240307', 'Claude 3 Haiku', 0.25, 1.25, 0.30, 0.025, '2024-03-07')
    ON CONFLICT (provider_id, model, effective_from) DO NOTHING;
END $$;
