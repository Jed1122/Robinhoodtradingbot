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
COPY configs /app/configs
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIVE_TRADING_ENABLED=false \
    PREDICTION_LIVE_ENABLED=false
USER 10001:10001
ENTRYPOINT ["python", "-m", "trading_bot.cli.main"]
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).close()"]
CMD ["serve", "--config", "/app/configs/shadow.yaml", "--mode", "shadow", "--paused"]
