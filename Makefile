.PHONY: install test lint format-check typecheck check init-db bot web

install:
	python -m pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check .

format-check:
	ruff format --check .

typecheck:
	mypy src

check: lint format-check typecheck test

init-db:
	finance-assistant init-db

bot:
	finance-assistant bot

web:
	finance-assistant web
