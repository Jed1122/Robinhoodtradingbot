"""Private receipt-bound stock evidence reports; no broker calls or investment authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.clock import require_utc
from trading_bot.market_data.recording import canonical_json
from trading_bot.market_data.stock_events import (
    StockEarningsCollection,
    StockFilingCollection,
    normalize_earnings_results,
    normalize_filing_index,
)
from trading_bot.market_data.stock_facts import (
    StockFactCollection,
    StockFinancialPeriod,
    StockFundamentals,
    normalize_financials,
    normalize_fundamentals,
)
from trading_bot.market_data.stock_filing_facts import (
    StockFilingCatalog,
    StockFilingEvidence,
    StockFilingFacts,
    bind_filing_evidence,
    normalize_filing_catalog,
    normalize_filing_facts,
)
from trading_bot.market_data.stock_history_projection import (
    StockHistoryProjectionBatch,
    normalize_history_by_symbol,
)
from trading_bot.research.stock_dossiers import build_stock_dossiers, stock_dossier_document
from trading_bot.research.stock_technicals import compute_stock_technicals
from trading_bot.runtime.stock_archive import _read, read_stock_observations
from trading_bot.runtime.stock_capture import _duplicate_directory, _private_directory, _publish

_MAX_REPORT_BYTES = 9_000_000


def _filing_chains(
    filings: list[StockFilingCollection],
    catalogs: list[StockFilingCatalog],
    facts: list[StockFilingFacts],
    cutoff: datetime,
) -> tuple[tuple[StockFilingEvidence, ...], list[dict[str, object]]]:
    evidence: list[StockFilingEvidence] = []
    denials: list[dict[str, object]] = []
    requested = {row.requested_filing_id for row in catalogs} | {
        identity for row in facts for identity in row.requested_filing_ids
    }
    for identity in sorted(requested):
        indexes = [row for row in filings if any(f.filing_id == identity for f in row.records)]
        # A second index collection for the same company is also ambiguous even
        # when it contains a different ID. Never select its preferred vintage.
        symbols = {row.requested_symbol for row in indexes}
        indexes = [row for row in filings if row.requested_symbol in symbols]
        selected_catalogs = [row for row in catalogs if row.requested_filing_id == identity]
        selected_facts = [row for row in facts if identity in row.requested_filing_ids]
        sources: tuple[StockFilingCollection | StockFilingCatalog | StockFilingFacts, ...] = (
            *indexes,
            *selected_catalogs,
            *selected_facts,
        )
        lengths = (len(indexes), len(selected_catalogs), len(selected_facts))
        reason = "stock_filing_evidence_incomplete"
        if any(length > 1 for length in lengths):
            reason = "stock_filing_evidence_ambiguous"
        elif lengths == (1, 1, 1):
            try:
                evidence.append(
                    bind_filing_evidence(
                        indexes[0], selected_catalogs[0], selected_facts[0], as_of=cutoff
                    )
                )
                continue
            except (ValueError, TypeError, OverflowError):
                reason = "stock_filing_evidence_binding_denied"
        denials.append(
            {
                "reason": reason,
                "observation_sha256s": tuple(row.receipt.observation_sha256 for row in sources),
            }
        )
    return tuple(evidence), denials


def compile_stock_dossier_report(
    *, observations: tuple[dict[str, Any], ...], as_of: datetime
) -> dict[str, Any]:
    """Compose normalized evidence from archive-verified observations.

    This function does not authenticate arbitrary supplied dictionaries. Production
    callers use publish_stock_dossier_report, which rehashes the committed archive.
    Invalid collections are explicitly denied; valid sibling observations survive.
    Duplicate receipt identities and contradictory dossier joins fail the report.
    """
    try:
        cutoff = require_utc(as_of)
        if type(observations) is not tuple or not 1 <= len(observations) <= 32:
            raise ValueError
        facts: list[
            StockFactCollection[StockFundamentals] | StockFactCollection[StockFinancialPeriod]
        ] = []
        history: list[StockHistoryProjectionBatch] = []
        earnings: list[StockEarningsCollection] = []
        filings: list[StockFilingCollection] = []
        catalogs: list[StockFilingCatalog] = []
        filing_facts: list[StockFilingFacts] = []
        filing_aware = False
        denials = []
        skipped: list[dict[str, str]] = []
        future = 0
        seen: set[str] = set()
        visible = []
        for row in observations:
            digest = row["observation_sha256"]
            if (
                type(digest) is not str
                or re.fullmatch("[0-9a-f]{64}", digest) is None
                or digest in seen
                or type(row["transport_authenticated"]) is not bool
            ):
                raise ValueError
            seen.add(digest)
            received = require_utc(datetime.fromisoformat(row["received_at"]))
            if received > cutoff:
                future += 1
                continue
            visible.append(row)
            tool, arguments, payload = row["tool"], row["arguments"], row["payload"]
            if tool in ("get_sec_filing_facts_catalog", "get_sec_filing_facts"):
                filing_aware = True
            common: dict[str, Any] = {"received_at": received, "observation_sha256": digest}
            try:
                if tool == "get_equity_fundamentals":
                    facts.append(
                        normalize_fundamentals(
                            payload, **common, requested_symbols=tuple(arguments["symbols"])
                        )
                    )
                elif tool == "get_financials":
                    facts.append(
                        normalize_financials(
                            payload, **common, requested_symbols=tuple(arguments["symbols"])
                        )
                    )
                elif tool == "get_equity_historicals":
                    # Conservative caller declaration excludes the current UTC day.
                    # It does not establish exchange-calendar coverage or vendor basis.
                    history.append(
                        normalize_history_by_symbol(
                            payload,
                            **common,
                            requested_symbols=tuple(arguments["symbols"]),
                            request_adjustment_type=(
                                "none" if arguments.get("adjustment_type") == "none" else None
                            ),
                            completed_before=received.replace(
                                hour=0, minute=0, second=0, microsecond=0
                            ),
                        )
                    )
                elif tool == "get_earnings_results":
                    earnings.append(
                        normalize_earnings_results(
                            payload, **common, requested_symbol=arguments["symbol"]
                        )
                    )
                elif tool == "get_sec_filing_index":
                    filings.append(
                        normalize_filing_index(
                            payload, **common, requested_symbol=arguments["symbol"]
                        )
                    )
                elif tool == "get_sec_filing_facts_catalog":
                    catalogs.append(
                        normalize_filing_catalog(
                            payload,
                            **common,
                            requested_filing_id=arguments["filing_id"],
                            requested_offset=arguments.get("offset", 0),
                        )
                    )
                elif tool == "get_sec_filing_facts":
                    filing_facts.append(
                        normalize_filing_facts(
                            payload,
                            **common,
                            requested_filing_ids=tuple(arguments["filing_ids"]),
                            requested_concepts=tuple(arguments["concepts"]),
                        )
                    )
                else:
                    skipped.append({"tool": tool, "observation_sha256": digest})
            except (ValueError, KeyError, TypeError, OverflowError):
                denials.append(
                    {
                        "tool": tool,
                        "observation_sha256": digest,
                        "reason": "stock_observation_normalization_denied",
                    }
                )
        evidence, filing_denials = _filing_chains(filings, catalogs, filing_facts, cutoff)
        index_counts = Counter(row.requested_symbol for row in filings)
        dossier_filings = tuple(
            row for row in filings if not filing_aware or index_counts[row.requested_symbol] == 1
        )
        dossiers = build_stock_dossiers(
            as_of=cutoff,
            facts=tuple(facts),
            history=tuple(history),
            earnings=tuple(earnings),
            filings=dossier_filings,
            filing_evidence=evidence,
        )
        technical_summaries = []
        for feature in compute_stock_technicals(as_of=cutoff, history=tuple(history)):
            summary = asdict(feature)
            # Dossiers already retain the complete normalized history. Keep metrics
            # and exact source/projection identities without duplicating every bar.
            summary.pop("outcome")
            summary["projection_context"] = feature.outcome.context
            summary["history_status"] = feature.outcome.status
            summary["feature_sha256"] = feature.feature_hash
            technical_summaries.append(summary)
        # Shared canonical codec handles Decimal/date without float conversion.
        result: dict[str, Any] = json.loads(
            canonical_json(
                {
                    "schema_version": 3 if filing_aware else 2,
                    "status": "descriptive_evidence_with_gaps",
                    "as_of": cutoff,
                    "company_count": len(dossiers),
                    "source_observation_hashes": tuple(
                        row["observation_sha256"] for row in visible
                    ),
                    "source_transport_authenticated": bool(visible)
                    and all(row["transport_authenticated"] for row in visible),
                    "normalization_denials": denials,
                    "unprojected_observations": skipped,
                    "future_observations_excluded": future,
                    "dossiers": tuple(
                        stock_dossier_document(row, include_empty_filing_evidence=filing_aware)
                        for row in dossiers
                    ),
                    "dossier_hashes": tuple(row.dossier_hash for row in dossiers),
                    "technical_features": technical_summaries,
                    "native_http_wire_receipt": False,
                    "source_qualified": False,
                    "strategy_qualified": False,
                    "investment_eligible": False,
                    "live_enabled": False,
                }
            )
        )
        if filing_aware:
            result["filing_evidence_denials"] = json.loads(canonical_json(filing_denials))
        return result
    except (ValueError, KeyError, TypeError, OverflowError):
        raise ValueError("stock_dossier_report_invalid") from None


def publish_stock_dossier_report(
    *, root: Path, manifest_file: str, as_of: datetime, _directory_fd: int | None = None
) -> dict[str, object]:
    """Rehash committed archive, then privately publish idempotent evidence output."""
    directory = -1
    cleanup = ExitStack()
    try:
        if re.fullmatch(r"[0-9a-f]{64}\.stock-capture\.json", manifest_file) is None:
            raise ValueError
        directory = (
            _private_directory(root)
            if _directory_fd is None
            else _duplicate_directory(_directory_fd)
        )
        if _directory_fd is None:
            from trading_bot.runtime.stock_archive_lease import StockArchiveLease

            cleanup.enter_context(StockArchiveLease(root, _directory_fd=directory))
        observations = read_stock_observations(root, manifest_file, _directory_fd=directory)
        report = compile_stock_dossier_report(observations=observations, as_of=as_of)
        report["source_manifest_sha256"] = manifest_file[:64]
        body = canonical_json(report).encode()
        if len(body) > _MAX_REPORT_BYTES:
            raise ValueError("stock_dossier_report_too_large")
        digest = hashlib.sha256(body).hexdigest()
        name = digest + ".stock-dossiers.json"
        try:
            _publish(directory, body, ".stock-dossiers.json")
        except FileExistsError:
            if _read(directory, name, ".stock-dossiers.json") != report:
                raise ValueError from None
        return {
            "status": "stock_dossier_report_published",
            "report_file": name,
            "report_sha256": digest,
            "company_count": report["company_count"],
            "normalization_denial_count": len(report["normalization_denials"]),
            "live_enabled": False,
        }
    except Exception:
        raise ValueError("stock_dossier_report_invalid") from None
    finally:
        try:
            try:
                if directory >= 0:
                    os.close(directory)
            finally:
                cleanup.close()
        except Exception:
            raise ValueError("stock_dossier_report_invalid") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--as-of", type=datetime.fromisoformat, default=datetime.now(UTC))
    args = parser.parse_args()
    try:
        result = publish_stock_dossier_report(
            root=args.archive_root, manifest_file=args.manifest, as_of=args.as_of
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('{"status":"stock_dossier_report_failed","live_enabled":false}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
