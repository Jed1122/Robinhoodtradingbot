"""One-shot authenticated, read-only ETF research collection and rejection evidence."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from trading_bot.brokers.robinhood_equity_evidence import (
    authenticated_equity_manifest,
    validate_read_tool_declarations,
)
from trading_bot.brokers.robinhood_equity_mapping import account_fingerprint
from trading_bot.brokers.robinhood_equity_mcp import build_equity_read_adapter
from trading_bot.brokers.robinhood_mcp_sdk import (
    READ_ONLY_EQUITY_MCP_TOOLS,
    RobinhoodMcpSdkConnection,
)
from trading_bot.brokers.robinhood_mcp_transport import (
    OFFICIAL_MCP_ENDPOINT,
    RobinhoodMcpTransport,
)
from trading_bot.clock import SystemClock
from trading_bot.config import LoadedConfig, load_config
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import (
    Bar,
    BarInterval,
    CodeHash,
    ConfigHash,
    DataHash,
    ExecutionMode,
    InstrumentId,
)
from trading_bot.market_data import content_hash
from trading_bot.market_data.robinhood_equity_mcp import RobinhoodEquityMarketData
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.migrations import migrate_sqlite_ledger
from trading_bot.persistence.research import SqlResearchEvidenceStore
from trading_bot.research.artifacts import persist_research_report
from trading_bot.research.engine import assess_and_persist
from trading_bot.research.equity_comparison import (
    EquityComparisonRequest,
    EquityResearchDataset,
    run_equity_candidate_comparison,
)
from trading_bot.research.validation import (
    ResearchAcceptancePolicy,
    assess_research,
)
from trading_bot.runtime.connected_shadow import (
    deployment_code_hash,
    read_account_fingerprint,
)

_DEPENDENCY_LOG_DISABLE_LEVEL = logging.CRITICAL
_CONNECTED_RESEARCH_READ_TOOLS = frozenset(
    {
        "get_accounts",
        "get_equity_historicals",
        "get_equity_orders",
        "get_equity_positions",
        "get_equity_quotes",
        "get_equity_tradability",
        "get_portfolio",
    }
)


class ConnectedResearchNotReady(RuntimeError):
    pass


@contextmanager
def _suppress_dependency_logs() -> Iterator[None]:
    previous_level = logging.root.manager.disable
    logging.disable(_DEPENDENCY_LOG_DISABLE_LEVEL)
    try:
        yield
    finally:
        logging.disable(previous_level)


def _seconds(value: Decimal) -> timedelta:
    microseconds = value * Decimal("1000000")
    if microseconds != microseconds.to_integral_value():
        raise ValueError("duration exceeds microsecond precision")
    return timedelta(microseconds=int(microseconds))


def _summary_attempts(report_hash: str, attempts: tuple[object, ...]) -> dict[str, object]:
    from trading_bot.research.report import ResearchAttempt

    typed = tuple(item for item in attempts if isinstance(item, ResearchAttempt))
    families: list[dict[str, object]] = []
    for family in sorted({item.family for item in typed}):
        candidates = tuple(item for item in typed if item.family == family)
        observed = tuple(
            item
            for item in candidates
            if item.stressed_metrics is not None
            and isinstance(item.stressed_metrics.total_return_pct.value, Decimal)
        )
        highest = (
            None
            if not observed
            else max(
                observed,
                key=lambda item: (
                    item.stressed_metrics.total_return_pct.value,  # type: ignore[union-attr]
                    item.parameter_hash,
                ),
            )
        )
        families.append(
            {
                "candidate_count": len(candidates),
                "family": family,
                "highest_observed_parameter_hash": (
                    None if highest is None else highest.parameter_hash
                ),
                "highest_observed_stressed_total_return_pct": (
                    None
                    if highest is None or highest.stressed_metrics is None
                    else str(highest.stressed_metrics.total_return_pct.value)
                ),
                "passing_candidate_count": sum(
                    item.status == "accepted" for item in candidates
                ),
            }
        )
    return {"families": families, "report_hash": report_hash}


def _validate_connected_read_scope() -> None:
    """Keep runtime read authority independent from the SDK declaration table."""

    manifest = authenticated_equity_manifest()
    manifest_operations = frozenset(
        record.operation
        for record in manifest.records
        if record.operation_kind.value == "read"
    )
    if (
        READ_ONLY_EQUITY_MCP_TOOLS != _CONNECTED_RESEARCH_READ_TOOLS
        or manifest_operations != _CONNECTED_RESEARCH_READ_TOOLS
        or len(manifest.records) != len(_CONNECTED_RESEARCH_READ_TOOLS)
    ):
        raise ConnectedResearchNotReady(
            "connected research read capability contract changed"
        )


def run_connected_equity_research_once(
    *,
    loaded: LoadedConfig,
    repository_root: str | Path,
    oauth_store: str | Path,
    account_fingerprint_file: str | Path,
    ledger: str | Path,
    artifact_dir: str | Path,
    image_digest: str,
) -> dict[str, object]:
    """Collect the configured ETF data and persist a non-activating assessment."""

    try:
        root = Path(repository_root).resolve(strict=True)
        approved = load_config(
            root / "configs/base.yaml",
            root / "configs/shadow.yaml",
            root / "configs/safety-envelope.yaml",
            {},
        )
        _validate_connected_read_scope()
        canonical, config_hash = hash_loaded_config(
            loaded.config,
            loaded.safety_envelope,
        )
    except ConnectedResearchNotReady:
        raise
    except Exception as exc:
        raise ConnectedResearchNotReady(
            "connected research release scope could not be verified"
        ) from exc
    if (
        canonical != loaded.canonical_json
        or config_hash != loaded.config_hash
        or loaded.config_hash != approved.config_hash
        or loaded.canonical_json != approved.canonical_json
    ):
        raise ConnectedResearchNotReady(
            "connected research configuration differs from the approved release scope"
        )
    config = loaded.config
    if (
        config.mode is not ExecutionMode.SHADOW
        or config.live_trading_enabled
        or not config.runtime.start_paused
        or not config.equities.enabled
        or config.crypto.enabled
        or config.equity_strategies.bar_interval is not BarInterval.ONE_DAY
    ):
        raise ConnectedResearchNotReady("connected research configuration is unsafe")
    if config.equity_strategies.research_universe_symbols != (
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
    ):
        raise ConnectedResearchNotReady("connected research universe is not the approved scope")

    previous_umask = os.umask(0o077)
    engine = None
    try:
        expected_account_fingerprint = read_account_fingerprint(account_fingerprint_file)
        config_hash = ConfigHash(str(loaded.config_hash))
        code_hash = CodeHash(deployment_code_hash(image_digest))
        database_url = migrate_sqlite_ledger(
            ledger,
            alembic_ini=root / "alembic.ini",
            migrations_dir=root / "migrations",
        )
        engine = create_engine(database_url)
        session_factory = async_session_factory(engine)
        store = SqlResearchEvidenceStore(session_factory)
        clock = SystemClock()

        async def collect_and_assess() -> dict[str, object]:
            try:
                as_of = clock.now()
                collection_reasons: set[str] = set()
                bars_by_symbol: list[tuple[str, tuple[Bar, ...]]] = []
                raw_hashes: list[DataHash] = []
                async with RobinhoodMcpSdkConnection(
                    oauth_store_dir=oauth_store,
                ) as connection:
                    declarations = await connection.session.list_tools()
                    provider_evidence_hash = str(
                        validate_read_tool_declarations(declarations)
                    )
                    transport = RobinhoodMcpTransport(
                        connection.session,
                        endpoint=OFFICIAL_MCP_ENDPOINT,
                        oauth_store_dir=oauth_store,
                        allowed_tools=READ_ONLY_EQUITY_MCP_TOOLS,
                    )
                    broker = build_equity_read_adapter(
                        authenticated_equity_manifest(),
                        transport,
                        clock=clock,
                        expected_account_fingerprint=expected_account_fingerprint,
                    )
                    health = await broker.health_check()
                    accounts = await broker.get_accounts()
                    if not health.healthy or len(accounts) != 1:
                        raise ConnectedResearchNotReady(
                            "authenticated account reads are unhealthy"
                        )
                    account = accounts[0]
                    if (
                        account_fingerprint(account.account_id)
                        != expected_account_fingerprint
                        or account.restricted
                    ):
                        raise ConnectedResearchNotReady(
                            "allowlisted account is unavailable or restricted"
                        )
                    market = RobinhoodEquityMarketData(
                        transport,
                        clock,
                        maximum_quote_age=_seconds(
                            config.freshness.max_executable_quote_age_seconds
                        ),
                    )
                    start = as_of - timedelta(
                        days=config.research.history_calendar_days
                    )
                    for symbol in config.equity_strategies.research_universe_symbols:
                        instrument = InstrumentId(symbol)
                        try:
                            tradability = await market.get_tradability(
                                account.account_id,
                                account_type="individual",
                                instrument_id=instrument,
                            )
                            if not tradability.tradeable:
                                collection_reasons.add(
                                    f"current_tradability_unverified_{symbol}"
                                )
                            historical = await market.get_research_bars(
                                instrument,
                                BarInterval.ONE_DAY,
                                start,
                                as_of,
                            )
                            if historical.interpolation_status != "verified_clear":
                                collection_reasons.add(
                                    f"interpolation_status_{historical.interpolation_status}_{symbol}"
                                )
                            bars_by_symbol.append((symbol, historical.bars))
                            raw_hashes.append(
                                DataHash(historical.raw_response_hash)
                            )
                        except Exception:
                            collection_reasons.add(
                                f"historical_collection_failed_{symbol}"
                            )

                dataset = EquityResearchDataset(
                    as_of=as_of,
                    requested_start=start,
                    requested_end=as_of,
                    bars_by_symbol=tuple(
                        (symbol, tuple(bars))
                        for symbol, bars in bars_by_symbol
                    ),
                    raw_hashes=tuple(raw_hashes),
                    provider_evidence_hash=provider_evidence_hash,
                    collection_reason_codes=tuple(sorted(collection_reasons)),
                )
                run_id = str(
                    content_hash(
                        {
                            "as_of": as_of,
                            "code_hash": code_hash,
                            "config_hash": config_hash,
                            "provider_evidence_hash": provider_evidence_hash,
                            "raw_hashes": tuple(raw_hashes),
                            "type": "connected_equity_candidate_comparison",
                        }
                    )
                )
                report = run_equity_candidate_comparison(
                    EquityComparisonRequest(
                        loaded=loaded,
                        code_hash=str(code_hash),
                        code_clean=False,
                        run_id=run_id,
                        dataset=dataset,
                    )
                )
                artifact = persist_research_report(artifact_dir, report)
                policy = ResearchAcceptancePolicy(
                    minimum_independent_opportunities=(
                        config.research.minimum_independent_opportunities
                    ),
                    maximum_stressed_drawdown_pct=(
                        config.research.maximum_stressed_drawdown_pct
                    ),
                    minimum_positive_walk_forward_folds=(
                        config.research.minimum_positive_walk_forward_folds
                    ),
                    maximum_single_opportunity_profit_contribution_pct=(
                        config.research.maximum_single_opportunity_profit_contribution_pct
                    ),
                    maximum_monte_carlo_loss_probability_pct=(
                        config.research.maximum_monte_carlo_loss_probability_pct
                    ),
                    minimum_benchmark_excess_return_pct=(
                        config.research.minimum_benchmark_excess_return_pct
                    ),
                    research_assumptions_validated=(
                        config.research.assumptions_validated
                    ),
                    research_evidence_promotable=(
                        config.research.evidence_promotable
                    ),
                )
                assessment = assess_research(report, policy)
                attestation = await assess_and_persist(
                    report,
                    policy,
                    observed_at=clock.now(),
                    store=store,
                )
                evidence_hash = str(
                    content_hash(
                        {
                            "assessment": assessment,
                            "attestation": attestation,
                        }
                    )
                )
                return {
                    "artifact": str(artifact),
                    "authenticated_reads": True,
                    "code_identity_verified": False,
                    "comparison": _summary_attempts(
                        report.report_hash,
                        report.attempts,
                    ),
                    "evidence_hash": evidence_hash,
                    "ineligible_reasons": assessment.reason_codes,
                    "live_enabled": False,
                    "persisted": True,
                    "promotion_eligible": attestation.eligible,
                    "status": "connected_research_recorded",
                    "write_capabilities_present": False,
                }
            finally:
                if engine is not None:
                    await engine.dispose()

        with _suppress_dependency_logs():
            return asyncio.run(collect_and_assess())
    except ConnectedResearchNotReady:
        raise
    except Exception as exc:
        raise ConnectedResearchNotReady(
            "connected equity research failed closed"
        ) from exc
    finally:
        os.umask(previous_umask)


__all__ = ["ConnectedResearchNotReady", "run_connected_equity_research_once"]
