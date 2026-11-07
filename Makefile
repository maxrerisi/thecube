.PHONY: install test lint fmt report dev seed demo

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

report:
	uv run python -m dukedining data/receipts_raw.txt data/eaccounts_raw.csv out/

dev:
	uv run uvicorn app.main:app --reload --port 8000

seed:
	uv run python scripts/seed_demo.py

demo: seed dev
