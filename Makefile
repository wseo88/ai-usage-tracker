.PHONY: install dev lint migrate seed clean

install:
	uv sync

dev:
	uv run python -m src.main

lint:
	uv run ruff check src/
	uv run mypy src/

migrate:
	supabase db push

seed:
	supabase db execute --file supabase/seed.sql

clean:
	rm -rf .venv/ __pycache__/ */__pycache__/ dist/
