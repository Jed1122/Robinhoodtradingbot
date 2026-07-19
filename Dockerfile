ARG PYTHON_BASE_IMAGE
FROM ${PYTHON_BASE_IMAGE} AS builder
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.11.28 && uv sync --frozen --no-dev --no-install-project
FROM ${PYTHON_BASE_IMAGE} AS runtime
RUN groupadd --system --gid 10001 tradingbot && useradd --system --uid 10001 --gid tradingbot tradingbot
WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY src /app/src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["python", "-m", "trading_bot.cli.main"]
CMD ["run", "--config", "/etc/trading-bot/base.yaml", "--mode", "shadow", "--paused"]
