.PHONY: install test lint fmt report

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
