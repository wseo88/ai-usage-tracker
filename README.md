# AI Usage Tracker

Monitor your spending across different AI APIs in one place.

## Architecture

- **Backend:** Python (FastAPI) — fetches usage data from provider APIs, serves dashboard data via REST
- **Frontend:** React + TypeScript + Vite — web dashboard with cost graphs
- **Database:** Supabase (Postgres) — stores usage records, cost entries, pricing snapshots
- **Sync:** Scheduled via GitHub Actions daily

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A Supabase project
- An Anthropic Admin API key

### Setup

```bash
# Clone the repo
git clone https://github.com/wseo88/ai-usage-tracker.git
cd ai-usage-tracker

# Install dependencies
make install

# Copy and configure environment
cp .env.example .env
# Edit .env with your Supabase credentials and Anthropic Admin API key

# Run migrations (requires Supabase CLI)
supabase link --project-ref your-project-ref
make migrate
make seed

# Start the dev server
make dev
```

### Run Syncing

```bash
# Sync the last 7 days of Anthropic usage
uv run python -m src.sync --days 7
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /api/v1/summary` | Total cost, total tokens, summary |
| `GET /api/v1/daily?days=30` | Daily cost time series |
| `GET /api/v1/by-model?days=30` | Cost breakdown by model |
| `GET /api/v1/providers` | Connected providers and sync status |
| `GET /api/v1/latest-sync` | Last successful sync timestamp |

## Deployment

The sync service runs via GitHub Actions on a daily schedule. For the backend API, deploy to any platform that supports FastAPI (Railway, Fly.io, Render, etc.).

## Adding a New Provider

1. Create a new provider class in `src/providers/` implementing `BaseProvider`
2. Add pricing data to `pricing_snapshots` table
3. Register the provider in the provider registry
4. Add the API key to your environment
