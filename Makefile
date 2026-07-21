.PHONY: setup format lint typecheck test test-unit test-integration test-chaos security backtest simulate paper shadow shadow-smoke live-readiness live-preflight build deploy status logs backup restore-test

# Keep src-layout commands self-contained even when an editable-install .pth file is unavailable.
export PYTHONPATH := $(CURDIR)/src

setup:
	uv sync --all-groups --frozen

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80

test-unit:
	uv run pytest tests/unit tests/property -q

test-integration:
	uv run pytest tests/integration tests/replay tests/architecture tests/deployment -q

test-chaos:
	uv run pytest tests/chaos -q

security:
	uv run bandit -c pyproject.toml -r src
	uv run pip-audit

backtest:
	uv run trader backtest --config configs/backtest.yaml --seed 20260710

simulate:
	uv run trader simulate --config configs/simulation.yaml --seed 20260710

paper:
	uv run trader paper --config configs/paper.yaml --once

shadow:
	uv run trader shadow --config configs/shadow.yaml --once

shadow-smoke:
	uv run python scripts/run_shadow_smoke.py --config configs/shadow.yaml

live-readiness:
	uv run python scripts/live_readiness.py --config configs/micro_live.yaml --mode micro_live

live-preflight:
	uv run trader preflight --config configs/micro_live.yaml

build:
	uv run python scripts/verify_base_image.py .docker-base-image
	docker build --build-arg PYTHON_BASE_IMAGE="$$(cat .docker-base-image)" -t "$${TRADING_BOT_IMAGE:-trading-bot:local}" .

deploy:
	@test -n "$${TRADING_BOT_IMAGE:-}" || (echo "TRADING_BOT_IMAGE is required" >&2; exit 2)
	@test -n "$${DEPLOY_HOST:-}" || (echo "DEPLOY_HOST is required" >&2; exit 2)
	./infra/digitalocean/deploy.sh

status:
	uv run trader status

logs:
	docker compose logs --tail=200 trading-bot

backup:
	./infra/digitalocean/backup.sh

restore-test:
	uv run pytest tests/deployment/test_backup_restore.py -q
