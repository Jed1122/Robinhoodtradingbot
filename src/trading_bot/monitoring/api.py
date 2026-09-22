from dataclasses import asdict

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse

from trading_bot.monitoring.health import HealthService
from trading_bot.monitoring.metrics import MetricsRegistry
from trading_bot.monitoring.readiness import ReadinessService


class AdminBindPolicy:
    @staticmethod
    def validate(host: str, container_loopback_publish: bool) -> None:
        if host == "127.0.0.1" or (
            host == "0.0.0.0" and container_loopback_publish  # nosec B104
        ):
            return
        raise ValueError("monitoring API must remain host-loopback-only")


def build_monitoring_app(
    health: HealthService, readiness: ReadinessService, metrics: MetricsRegistry
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        snapshot = health.snapshot()
        return JSONResponse(
            jsonable_encoder(asdict(snapshot)), status_code=200 if snapshot.healthy else 503
        )

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        snapshot = readiness.snapshot()
        return JSONResponse(
            jsonable_encoder(asdict(snapshot)), status_code=200 if snapshot.ready else 503
        )

    @app.get("/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics() -> str:
        return metrics.render()

    return app


__all__ = ["AdminBindPolicy", "build_monitoring_app"]
