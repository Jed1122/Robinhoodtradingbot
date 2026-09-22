"""Causal SPY acquisition shortlist, without prices for execution or order capability."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, localcontext
from typing import cast
from zoneinfo import ZoneInfo

from trading_bot.config.models import OptionsShortlistSettings
from trading_bot.domain import BarInterval, DataHash
from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    _require_sha256_hex,
)
from trading_bot.domain.options import (
    ExerciseStyle,
    OptionContract,
    OptionKind,
    SettlementKind,
    SettlementTiming,
)
from trading_bot.market_data.options_records import ChainSnapshot, point_in_time, select_chain
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_shortlist_models import (
    OptionsShortlistCandidate,
    OptionsShortlistResult,
    ShortlistAction,
    ShortlistClose,
    ShortlistEvidence,
    ShortlistSessionInput,
    _check,
)


def _covered(evidence: ShortlistEvidence | None, start: datetime, end: datetime) -> bool:
    return (
        evidence is not None
        and evidence.available_at <= end
        and evidence.covers_from <= start
        and evidence.covers_through >= end
    )


def _calendar(case: ShortlistSessionInput, evidence: dict[str, object]) -> bool:
    current, prior, calendar = case.current_session, case.prior_session, case.calendar
    if prior is None or calendar is None:
        return False
    if calendar.evidence.available_at <= current.opens_at:
        evidence["calendar_evidence"] = calendar.evidence
    if not _covered(calendar.evidence, prior.opens_at, current.opens_at):
        return False
    if prior.trading_date >= current.trading_date or prior.closes_at >= current.opens_at:
        return False
    days = tuple(
        sorted(
            (
                d
                for d in calendar.days
                if prior.trading_date <= d.trading_date <= current.trading_date
            ),
            key=lambda d: d.trading_date,
        )
    )
    evidence["calendar_days"] = days
    count = (current.trading_date - prior.trading_date).days + 1
    # Check the length before constructing a potentially large date range.
    if len(days) != count:
        return False
    if any(d.trading_date != prior.trading_date + timedelta(days=i) for i, d in enumerate(days)):
        return False
    sessions = tuple(d.regular_session for d in days if d.regular_session is not None)
    if sessions != (prior, current):
        return False
    zone = ZoneInfo("America/New_York")
    return all(
        s.exchange_timezone == "America/New_York"
        and s.opens_at.astimezone(zone).date() == s.trading_date
        and s.closes_at.astimezone(zone).date() == s.trading_date
        for s in sessions
    )


def _close(case: ShortlistSessionInput) -> ShortlistClose | None:
    prior = case.prior_session
    if prior is None:
        return None
    visible = [
        c
        for c in case.closes
        if c.available_at <= case.current_session.opens_at
        and c.evidence.available_at <= case.current_session.opens_at
        and c.bar.instrument_id == "SPY"
        and c.bar.starts_at == prior.opens_at
        and c.bar.ends_at == prior.closes_at
    ]
    by_time: dict[datetime, ShortlistClose] = {}
    for row in visible:
        previous = by_time.get(row.available_at)
        _check(previous is None or previous == row)
        by_time[row.available_at] = row
    if not visible:
        return None
    selected = max(visible, key=lambda c: c.available_at)
    # Never fall back to an older revision if the most recent visible one is unsuitable.
    if (
        selected.bar.interval is not BarInterval.ONE_DAY
        or selected.bar.interpolated
        or selected.evidence.covers_from > prior.opens_at
        or selected.evidence.covers_through < prior.closes_at
    ):
        return None
    return selected


def _actions(case: ShortlistSessionInput) -> tuple[ShortlistAction, ...]:
    latest: dict[tuple[str, str, date], ShortlistAction] = {}
    seen: dict[tuple[str, str, date, datetime, datetime], ShortlistAction] = {}
    for row in case.actions:
        action = row.action
        if (
            action.instrument_id != "SPY"
            or max(row.available_at, action.announced_at) > case.current_session.opens_at
        ):
            continue
        key = (action.instrument_id, action.action_type, action.effective_date)
        stamp = (action.announced_at, row.available_at)
        duplicate = seen.get((*key, *stamp))
        _check(duplicate is None or duplicate == row)
        seen[(*key, *stamp)] = row
        previous = latest.get(key)
        if previous is None or stamp > (previous.action.announced_at, previous.available_at):
            latest[key] = row
    return tuple(latest[key] for key in sorted(latest))


def _eligible(contract: OptionContract, as_of: datetime) -> bool:
    return (
        contract.underlying == "SPY"
        and contract.currency == "USD"
        and not contract.adjusted
        and contract.premium_multiplier == 100
        and contract.deliverable_units == 100
        and contract.deliverable_symbol == "SPY"
        and contract.exercise_style is ExerciseStyle.AMERICAN
        and contract.settlement_kind is SettlementKind.SHARES
        and contract.settlement_timing is SettlementTiming.PM
        and contract.available_at <= as_of < contract.last_trading_at
        and any(s.opens_at <= as_of < s.closes_at for s in contract.eligible_sessions)
    )


def _rank(
    contracts: tuple[OptionContract, ...],
    close: Decimal,
    day: date,
    settings: OptionsShortlistSettings,
) -> tuple[OptionContract, ...]:
    by_expiry: dict[date, dict[OptionKind, list[OptionContract]]] = {}
    for contract in contracts:
        dte = (contract.expiration - day).days
        if settings.min_dte <= dte <= settings.max_dte:
            by_expiry.setdefault(contract.expiration, {}).setdefault(contract.kind, []).append(
                contract
            )
    common = [
        expiry
        for expiry, sides in by_expiry.items()
        if sides.get(OptionKind.CALL) and sides.get(OptionKind.PUT)
    ]
    if not common:
        return ()
    expiry = min(common, key=lambda d: (abs((d - day).days - settings.target_dte), d))
    return tuple(
        min(by_expiry[expiry][kind], key=lambda c: (abs(c.strike - close), c.strike))
        for kind in (OptionKind.CALL, OptionKind.PUT)
    )


def _contract_identities(contracts: tuple[OptionContract, ...]) -> None:
    seen: set[tuple[object, ...]] = set()
    for contract in contracts:
        strike_code = contract.strike * 1000
        _check(strike_code == strike_code.to_integral_value() and 0 < strike_code <= 99999999)
        expected = (
            f"SPY   {contract.expiration:%y%m%d}{contract.kind.value[0].upper()}"
            f"{int(strike_code):08d}"
        )
        _check(contract.standardized_id == expected)
        identity = (
            contract.underlying,
            contract.expiration,
            contract.kind,
            contract.strike,
            contract.premium_multiplier,
            contract.deliverable_units,
            contract.deliverable_symbol,
            contract.exercise_style,
            contract.settlement_kind,
            contract.settlement_timing,
            contract.currency,
        )
        _check(identity not in seen)
        seen.add(identity)


def _selection(
    case: ShortlistSessionInput, settings: OptionsShortlistSettings, evidence: dict[str, object]
) -> tuple[tuple[OptionsShortlistCandidate, ...], str | None]:
    as_of = case.current_session.opens_at
    if not settings.enabled:
        return (), "shortlist_disabled"
    if case.source_kind != "synthetic" or case.chain_evidence is None:
        return (), "source_evidence_unverified"
    if not _calendar(case, evidence):
        return (), "calendar_unverified"
    close = _close(case)
    if close is None:
        return (), "prior_close_unavailable"
    evidence["prior_close"] = close
    prior = case.prior_session
    _check(prior is not None)
    if prior is None:  # Type narrowing; missing prior already denied by _calendar.
        return (), "calendar_unverified"
    if not _covered(case.action_evidence, prior.closes_at, as_of):
        return (), "action_coverage_unverified"
    actions = _actions(case)
    evidence["action_coverage"] = case.action_evidence
    evidence["actions"] = actions
    if any(a.action.action_type == "unknown" for a in actions):
        return (), "action_coverage_unverified"
    if any(
        a.action.action_type != "dividend"
        and prior.trading_date <= a.action.effective_date <= case.current_session.trading_date
        for a in actions
    ):
        return (), "reference_discontinuity"
    if not _covered(case.chain_evidence, as_of, as_of):
        return (), "chain_unavailable"
    evidence["chain_coverage"] = case.chain_evidence
    visible = point_in_time(case.records, as_of=as_of)
    chain_row = next(
        (r for r in visible if type(r.value) is ChainSnapshot and r.value.underlying == "SPY"), None
    )
    if chain_row is None or not isinstance(chain_row.value, ChainSnapshot):
        return (), "chain_unavailable"
    chain = replace(
        chain_row,
        value=replace(chain_row.value, contract_ids=tuple(sorted(chain_row.value.contract_ids))),
    )
    evidence["chain"] = chain
    definitions = {r.value.contract_id: r for r in visible if type(r.value) is OptionContract}
    if any(
        ident not in definitions
        or cast(OptionContract, definitions[ident].value).underlying != "SPY"
        for ident in chain_row.value.contract_ids
    ):
        return (), "chain_unavailable"
    contracts = select_chain(visible, source=case.option_source, underlying="SPY", as_of=as_of)
    evidence["definitions"] = tuple(
        definitions[c.contract_id] for c in sorted(contracts, key=lambda c: c.contract_id)
    )
    _contract_identities(contracts)
    eligible = tuple(c for c in contracts if _eligible(c, as_of))
    chosen = _rank(eligible, close.bar.close, case.current_session.trading_date, settings)
    if not chosen:
        return (), "no_common_eligible_expiry"
    hashes = {
        "calendar": content_hash((evidence["calendar_evidence"], evidence["calendar_days"])),
        "chain": content_hash(chain),
        "prior_close": content_hash(close),
        "action_coverage": content_hash(case.action_evidence),
    }
    for index, action in enumerate(actions):
        hashes[f"action:{index:05d}"] = content_hash(action)
    result = []
    for contract in chosen:
        selected_hashes = tuple(
            sorted({**hashes, "contract": content_hash(definitions[contract.contract_id])}.items())
        )
        result.append(
            OptionsShortlistCandidate(
                case.current_session.session_id,
                as_of,
                contract.kind,
                contract.contract_id,
                contract.standardized_id,
                contract.expiration,
                contract.strike,
                content_hash(close),
                selected_hashes,
            )
        )
    return tuple(result), None


def select_options_shortlist(
    session: ShortlistSessionInput,
    *,
    settings: OptionsShortlistSettings,
    config_hash: DataHash,
    code_hash: DataHash,
    input_hash: DataHash,
) -> OptionsShortlistResult:
    """Return only research candidates; imported source evidence cannot be unlocked here."""
    _check(type(session) is ShortlistSessionInput and type(settings) is OptionsShortlistSettings)
    session.__post_init__()
    settings = OptionsShortlistSettings.model_validate(settings.model_dump())
    for digest in (config_hash, code_hash, input_hash):
        _require_sha256_hex(digest, "shortlist digest")
    _check(session.record_count <= settings.max_input_records)
    # Bounded canonical decimals fit this fixed context even at opposite exponent extremes.
    with localcontext(Context(prec=MAX_CANONICAL_DECIMAL_TEXT_LENGTH * 2)):
        evidence: dict[str, object] = {}
        candidates, reason = _selection(session, settings, evidence)
        reasons = () if reason is None else (reason,)
        decision_hash = content_hash(
            {
                "version": settings.version,
                "config_hash": config_hash,
                "code_hash": code_hash,
                "policy": settings.model_dump(),
                "session": session.current_session,
                "source_kind": session.source_kind,
                "source": session.option_source,
                "evidence": evidence,
                "reasons": reasons,
                "candidates": candidates,
            }
        )
    return OptionsShortlistResult(
        settings.version,
        session.current_session.session_id,
        session.current_session.opens_at,
        session.source_kind,
        config_hash,
        code_hash,
        input_hash,
        decision_hash,
        "selected" if candidates else "no_candidate",
        reasons,
        candidates,
        session.record_count,
    )
