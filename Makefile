.PHONY: format lint typecheck test security

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest --cov=trading_bot --cov-branch

security:
	uv run bandit -c pyproject.toml -r src
	uv run pip-audit
