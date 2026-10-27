"""One source-verified current-stock planning cycle, with no broker transport.

Schedule this after collection in the external runtime. It reads committed
research and independently publishes a private decision/proposal report. Adding
credentials, calling this function or obtaining eligible candidates cannot
activate trading. Actual execution and owned ledger ingestion remain separate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.domain import CodeHash
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.portfolio.stock_allocation import StockAllocationContext, StockAllocationLimits
from trading_bot.research.stock_investment_decisions import CurrentInvestmentPolicy
from trading_bot.runtime.stock_dashboard_export import _policy
from trading_bot.runtime.stock_investment_evidence import PROFILE
from trading_bot.runtime.stock_investment_inputs import load_current_stock_research_inputs
from trading_bot.runtime.stock_investment_plan import (
    CurrentStockPlan,
    StockIssuerIdentity,
    StockPlanningControls,
    compile_current_stock_plan,
)
from trading_bot.runtime.stock_research_controls import (
    StockResearchControlError,
    StockResearchControls,
)
from trading_bot.runtime.stock_research_worker import (
    _existing_private_ledger,
    load_stock_worker_identity,
)

if TYPE_CHECKING:
    from trading_bot.runtime.stock_investment_holdings import StockOwnedHoldingContext
    from trading_bot.runtime.stock_portfolio_proposals import StockProfitProposalRequest


def _assert_publication_fresh(
    plan: CurrentStockPlan,
    *,
    at: datetime,
    started: datetime,
    controls: StockPlanningControls,
    account: StockAllocationContext | None,
    issuers: tuple[StockIssuerIdentity, ...],
) -> None:
    """A successful receipt may not advertise an expired current proposal."""
    now = require_utc(at)
    if not (
        plan.as_of <= now < started + timedelta(minutes=5)
        and controls.as_of <= now < controls.expires_at
    ):
        raise ValueError
    if plan.rankings is not None:
        for decision in plan.rankings.assessments:
            if decision.analytically_eligible and (
                decision.expires_at is None or not decision.as_of <= now < decision.expires_at
            ):
                raise ValueError
    proposals = plan.portfolio_proposals
    if proposals is not None and (
        proposals.reviewed_at > now
        or (proposals.expires_at is not None and now >= proposals.expires_at)
    ):
        raise ValueError
    if plan.allocation is not None:
        if account is None or not account.as_of <= now < account.expires_at:
            raise ValueError
        identities = {x.symbol: x for x in issuers}
        for proposal in plan.allocation.proposals:
            identity = identities.get(proposal.symbol)
            if identity is None or not (
                identity.instrument_id == proposal.instrument_id
                and identity.issuer_id == proposal.issuer_id
                and identity.as_of <= now < identity.expires_at
            ):
                raise ValueError


async def run_current_stock_planning_cycle(
    *,
    loaded: LoadedConfig,
    acquisition_code_hash: CodeHash,
    analysis_code_hash: str,
    factory: object,
    archive_dir: Path,
    output_dir: Path,
    decision_export_dir: Path | None = None,
    watch_output_dir: Path | None = None,
    watch_symbols: tuple[str, ...] = (),
    controls: StockResearchControls,
    policy: CurrentInvestmentPolicy | None = None,
    allocation_context: StockAllocationContext | None = None,
    issuers: tuple[StockIssuerIdentity, ...] = (),
    held_sleeves: tuple[tuple[str, Literal["long_term", "tactical"]], ...] = (),
    planning_controls: StockPlanningControls | None = None,
    limits: StockAllocationLimits | None = None,
    owned_holding_contexts: tuple[StockOwnedHoldingContext, ...] = (),
    profit_requests: tuple[StockProfitProposalRequest, ...] = (),
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Rebuild current evidence and reports; never connect, reserve cash or trade."""
    try:
        # Importing the report owner does not construct a provider or credential.
        from trading_bot.runtime.stock_investment_reports import publish_current_stock_plan

        worker = _policy(loaded)
        if worker.stock_worker.policy_id != PROFILE:
            raise ValueError
        roots = [archive_dir, output_dir]
        for optional_root in (decision_export_dir, watch_output_dir):
            if optional_root is not None:
                if (
                    not optional_root.is_absolute()
                    or optional_root.resolve(strict=True) != optional_root
                ):
                    raise ValueError
                if any(
                    optional_root.is_relative_to(root) or root.is_relative_to(optional_root)
                    for root in roots
                ):
                    raise ValueError
                roots.append(optional_root)
        _require_sha256_hex(analysis_code_hash, "stock_analysis_code")
        _require_sha256_hex(acquisition_code_hash, "stock_acquisition_code")
        if type(controls) is not StockResearchControls:
            raise ValueError
        grant = controls.grant(
            config_hash=str(loaded.config_hash), code_hash=str(acquisition_code_hash)
        )
        started = require_utc(clock())
        watch = None
        if watch_output_dir is not None:
            from trading_bot.runtime.stock_investment_watch import (
                stock_research_watch_from_portfolio,
            )

            if allocation_context is None:
                raise ValueError
            watch = stock_research_watch_from_portfolio(
                allocation_context,
                now=started,
                maximum_symbols=worker.stock_research.shortlist_count,
                watch_symbols=watch_symbols,
            )
            if set(watch.held_symbols) != {symbol for symbol, _ in held_sleeves}:
                raise ValueError
        source = await load_current_stock_research_inputs(
            loaded=loaded,
            acquisition_code_hash=acquisition_code_hash,
            factory=factory,
            archive_dir=archive_dir,
            held_symbols=tuple(x[0] for x in held_sleeves),
            clock=clock,
        )
        if started > source.as_of:
            raise ValueError
        # This is an explicitly local planning deadline, not a broker expiry.
        # Without a portfolio-risk owner's snapshot, tactical entries stay
        # suspended while both research rankings remain visible.
        effective_controls = planning_controls or StockPlanningControls(
            research_enabled=True,
            kill_switch_active=False,
            tactical_entries_suspended=True,
            as_of=started,
            expires_at=started + timedelta(minutes=5),
            source_hash=grant.state.sha256,
        )
        selected_policy = policy or CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        )
        with controls.permit(grant):
            plan = compile_current_stock_plan(
                source,
                worker_profile_id=worker.stock_worker.policy_id,
                policy=selected_policy,
                analysis_code_hash=analysis_code_hash,
                controls=effective_controls,
                allocation_context=allocation_context,
                issuers=issuers,
                held_sleeves=held_sleeves,
                limits=limits,
                owned_holding_contexts=owned_holding_contexts,
                profit_requests=profit_requests,
                reviewed_at=clock(),
            )
            checked_at = require_utc(clock())
            _assert_publication_fresh(
                plan,
                at=checked_at,
                started=started,
                controls=effective_controls,
                account=allocation_context,
                issuers=issuers,
            )
            artifact = publish_current_stock_plan(
                plan, output_dir=output_dir, archive_dir=archive_dir
            )
            publication_observed_at = require_utc(clock())
            if publication_observed_at < checked_at:
                raise ValueError
            _assert_publication_fresh(
                plan,
                at=publication_observed_at,
                started=started,
                controls=effective_controls,
                account=allocation_context,
                issuers=issuers,
            )
            decision_export = None
            watch_receipt = None
            if decision_export_dir is not None:
                from trading_bot.runtime.stock_decision_export import (
                    project_current_stock_decisions,
                    publish_stock_decisions,
                )

                if artifact.report_evidence_hash != plan.evidence_hash:
                    raise ValueError
                projection = project_current_stock_decisions(
                    plan, report_body_sha256=artifact.body_sha256
                )
                decision_export = publish_stock_decisions(
                    root=decision_export_dir, export=projection
                )
                after_export = require_utc(clock())
                if after_export < publication_observed_at:
                    raise ValueError
                _assert_publication_fresh(
                    plan,
                    at=after_export,
                    started=started,
                    controls=effective_controls,
                    account=allocation_context,
                    issuers=issuers,
                )
                publication_observed_at = after_export
            if watch_output_dir is not None and watch is not None:
                from trading_bot.runtime.stock_research_watch import publish_stock_research_watch

                watch_receipt = publish_stock_research_watch(
                    root=watch_output_dir, watch=watch, clock=clock
                )
                after_watch = require_utc(clock())
                if after_watch < publication_observed_at:
                    raise ValueError
                _assert_publication_fresh(
                    plan,
                    at=after_watch,
                    started=started,
                    controls=effective_controls,
                    account=allocation_context,
                    issuers=issuers,
                )
                publication_observed_at = after_watch
        rankings, allocation = plan.rankings, plan.allocation
        portfolio_proposals = plan.portfolio_proposals
        result: dict[str, object] = {
            "status": "current_stock_plan_published",
            "artifact_file": artifact.file,
            "artifact_sha256": artifact.body_sha256,
            "report_evidence_hash": plan.evidence_hash,
            "publication_observed_at": publication_observed_at.isoformat(),
            "long_term_candidates": 0 if rankings is None else len(rankings.long_term),
            "tactical_candidates": 0 if rankings is None else len(rankings.tactical),
            "proposed_entries": 0 if allocation is None else len(allocation.proposals),
            "holding_reviews": 0
            if portfolio_proposals is None or portfolio_proposals.holding_reviews is None
            else len(portfolio_proposals.holding_reviews.reviews),
            "proposed_reductions": 0
            if portfolio_proposals is None
            else sum(item.status == "proposed" for item in portfolio_proposals.profit_reductions),
            "needs": list(plan.needs),
            "live_enabled": False,
        }
        if decision_export is not None:
            result["decision_export_status"] = decision_export["status"]
            result["decision_export_sha256"] = decision_export["sha256"]
        if watch_receipt is not None:
            result["watch_status"] = "published"
            result["watch_sha256"] = watch_receipt.body_sha256
        return result
    except StockResearchControlError:
        return {"status": "blocked", "reason": "research_control_denied", "live_enabled": False}
    except Exception:
        return {
            "status": "blocked",
            "reason": "current_stock_planning_unavailable",
            "live_enabled": False,
        }


def main(argv: list[str] | None = None) -> int:
    """Offline planning command; intentionally accepts no credential or live flag."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--decision-export-dir", type=Path)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--image-digest")
    parser.add_argument("--image-attestation", type=Path)
    args = parser.parse_args(argv)
    try:
        loaded, code_hash = load_stock_worker_identity(
            args.config_root,
            image_digest=args.image_digest,
            image_attestation=args.image_attestation,
        )
        if _policy(loaded).stock_worker.policy_id != PROFILE:
            raise ValueError

        async def execute() -> dict[str, object]:
            with _existing_private_ledger(args.database) as descriptor:
                engine = create_engine(
                    f"sqlite+aiosqlite:///{args.database}", existing_file_descriptor=descriptor
                )
                try:
                    return await run_current_stock_planning_cycle(
                        loaded=loaded,
                        acquisition_code_hash=code_hash,
                        analysis_code_hash=str(code_hash),
                        factory=async_session_factory(engine),
                        archive_dir=args.archive_dir,
                        output_dir=args.output_dir,
                        decision_export_dir=args.decision_export_dir,
                        controls=StockResearchControls(args.control_dir),
                    )
                finally:
                    await engine.dispose()

        result = asyncio.run(execute())
    except Exception:
        result = {
            "status": "blocked",
            "reason": "stock_planning_startup_blocked",
            "live_enabled": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "current_stock_plan_published" else 2


if __name__ == "__main__":
    raise SystemExit(main())
