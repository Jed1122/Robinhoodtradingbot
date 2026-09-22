# SPY Options Research Shortlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, deterministic acquisition shortlist containing one SPY call and one put per requested session, or an explicit no-candidate result, without acquiring data or enabling trading.

**Architecture:** Add immutable research inputs and a pure selector to the existing options architecture. Extend the canonical configuration and release envelope; use existing point-in-time selection, strict codecs and private artifact storage through narrow wrappers. Compose only in the separate options research CLI, without broker, account, persistence or live-runtime dependencies.

**Tech Stack:** Existing Python 3.12–3.14, frozen dataclasses, Decimal, Pydantic, Typer, Pytest, Ruff and Mypy. No added dependencies, services or database migrations.

**Spec:** [Approved shortlist design](../specs/2026-09-22-options-research-shortlist-design.md). Read both documents before execution.

## Global Constraints

- Version `spy-prior-close-atm-30d-v1`; SPY only; previous completed regular-session unadjusted close; inclusive 21–45 calendar DTE; target 30 DTE; earlier expiry and lower strike win ties.
- One common expiry, independently selected call/put strikes, output call then put; exactly two candidates or zero. This is a data universe, not a straddle, signal, order or capital allocation.
- UTC instants; `America/New_York` trading dates; source-bound underlying regular sessions, including explicit closures and early closes. Never infer a weekday calendar or use an options close as the underlying close.
- Standard USD, American, PM, physically settled, unadjusted contracts delivering exactly 100 SPY shares with multiplier 100; only point-in-time visible definitions and explicit chain membership.
- 25,000 input records, 16 MiB decoded input bytes, JSON depth 16, one decision session per invocation. Reject excess; never truncate. Here decoded input bytes means the uncompressed UTF-8 JSON byte stream, not the Python heap size. Compressed inputs are not supported.
- `options.research_shortlist` is disabled by default. Only explicit BACKTEST/SIMULATION research composition may enable it; PAPER, SHADOW, MICRO_LIVE and LIVE must reject it.
- No quote, return, liquidity, Greek, outcome, account balance or affordability ranking. No later replacement of an unavailable selected contract.
- `production_eligible`, `evidence_promotable`, `download_authorized`, `live_authorized` are permanently false, not input flags.
- Preserve $100 capital assumption, $150 live-account ceiling, 0.5% per-trade risk, $50 outer per-trade ceiling, $50 non-replenishing cumulative trial-loss ceiling and every stricter existing limit.
- Preserve existing Bar/options serialization, historical hashes, synthetic-only replay and research thresholds. No data acquisition, credentials, provider/broker calls, subscriptions, orders, deployment or live activation.
- Local synthetic fixtures only in Git and delegated prompts. Imported data stays private. A shape, digest or caller assertion does not establish source completeness, availability semantics or economic evidence.

## Review Focus

1. **Future revisions and ordering:** appending future records or reordering equivalent inputs must not change an earlier decision or its decision hash; full input integrity hashes may change.
2. **Calendar and price discontinuities:** holidays, DST, early closes and intervening corporate actions must not permit stale-day, UTC-daily or options-session substitution.
3. **Untrusted evidence:** internally consistent hashes, forged verification flags and imported/synthetic mixing must not certify real data or grant any authority.
4. **Resource and filesystem attacks:** nested/oversized JSON, unsafe filenames, symlinks, non-private roots and conflicting output bytes must fail closed without overwriting data or exposing paths.
5. **Accidental execution coupling:** config overrides, credentials, network availability and downstream missing quotes must not turn a research shortlist into an order source or change the selected pair.

---

## Execution boundary, baseline and ownership

Planning base: `ba12d7d44465f531db7bd90a7128c4a79add0328`, branch
`codex/continue-implementation-from-commit-7c4dcd1`, worktree
`/Users/jedweinstein/Documents/robinhood-multi-asset-trading-system/worktrees/robinhood-system-implementation`.
This plan and the spec approval-status update are documentation, not implementation.
Execution starts only after operator review of this plan and an execution-method choice.

Subsystem status: existing point-in-time/codec/config primitives implemented; selector,
shortlist codec and command unimplemented; native normalization and imported-evidence
verification unresolved. Critical path: input/config contract → pure selector → bounded
private artifact path → CLI/integration verification. No external access is needed.

The primary coordinator owns configuration, policy, selection and integration. **Native
execution is recommended** because these four tasks share causal identity contracts and
the repository reserves selection/configuration decisions to the coordinator. After each
interface is committed, independent credential-free fixture/parser tests and read-only
audits may be delegated on an exact commit with explicit file ownership. A separate final
review is required. Subagent-driven execution, if selected, must still respect these
ownership limits; it cannot delegate the selector or safety-envelope decisions.

The current dirty worktree includes pre-staged `uv.lock`, modified `cli/main.py`, README,
research/architecture/limitations documents and SBOM, plus unrelated untracked equity
replay files. Preserve all of them. Do not edit the Polymarket workspace at
`/Users/jedweinstein/Documents/New project`. Do not stage a directory or use `git add .`.
Use explicit path lists and `git commit --only -- <owned paths>`; recheck the index after
each task. New untracked files require path-scoped `git add` before that commit.

Before implementation capture `git rev-parse HEAD`, `git status --short`,
`git diff --cached --name-status` and the hashes of `uv.lock` and `docs/sbom.cdx.json`.
Re-read AGENTS.md, Codex.md and the relevant risk/research/architecture documents. If any
owned source/config path has newly overlapping changes, stop and reconcile ownership;
do not overwrite them. No production state or historical artifact is regenerated.

## File and responsibility map

| Path | Responsibility / owner |
| --- | --- |
| `src/trading_bot/config/models.py` | New strict settings and composition guard; coordinator |
| `src/trading_bot/config/loader.py` | Existing envelope enforcement extended, not replaced; coordinator |
| `configs/base.yaml`, `configs/safety-envelope.yaml` | Disabled default and permitted fixed policy/resource ceilings; coordinator |
| `configs/options/shortlist.yaml` | Explicit offline research composition; coordinator |
| `src/trading_bot/research/options_shortlist_models.py` | Frozen research envelopes, explicit validation and immutable false flags; coordinator |
| `src/trading_bot/research/options_shortlist.py` | Point-in-time policy, reason precedence and causal hashes; coordinator |
| `src/trading_bot/research/options_shortlist_wire.py` | Strict versioned JSON, no IO; coordinator or bounded parser task after interface freeze |
| `src/trading_bot/research/options_shortlist_io.py` | Private bounded IO and code identity; coordinator |
| `src/trading_bot/cli/options_research.py` | New offline command only; leave existing loader/commands unchanged |
| `tests/unit/research/_options_shortlist_fixtures.py` | Fabricated common inputs, never provider payloads |
| `tests/unit/config/test_options_shortlist_config.py` | Config/envelope/mode regressions |
| `tests/unit/research/test_options_shortlist_models.py` | Exact types, immutability, envelope invariants |
| `tests/unit/research/test_options_shortlist.py` | Selection, causality, calendars and refusal reasons |
| `tests/unit/research/test_options_shortlist_wire.py` | Strict decoding and bounds |
| `tests/unit/research/test_options_shortlist_io.py` | Private storage, collision and fault tests |
| `tests/integration/cli/test_options_shortlist.py` | CLI end-to-end and non-capability proof |
| `tests/integration/cli/test_options_research_cli.py` | Extend existing AST import-boundary check to new modules |
| `docs/options-research-shortlist.md` | Operator usage, schema, limits, actual verification and unresolved dependencies |

No edits to broker, execution, risk, runtime, persistence, native provider normalization,
general CLI, old evidence serialization or existing replay are planned.

## Task 1: Canonical research settings and immutable input contract

**Files:** Create the profile, models, fixture helper, model tests and config tests above;
modify only `config/models.py`, `config/loader.py`, base and envelope YAML.

**Interfaces consumed:** `LoadedConfig`, existing `load_config(base_path, mode_path,
safety_path, environ)`, `StrictModel`,
`StrictBool`, `StrictInt`, `OptionSession`, `OptionContract`, `OptionsDataRecord`, `Bar`,
`CorporateAction`, `DataHash`, `require_utc`, exact Decimal/hash/tuple validators and
`content_hash(value: object) -> DataHash`.

**Interfaces produced:** the records below; `OptionsShortlistSettings` reachable only
through `LoadedConfig.config.options.research_shortlist`; test-only
`make_case(*, dtes: tuple[int, ...] = (30,), current: OptionSession | None = None,
prior: OptionSession | None = None) -> ShortlistSessionInput` and
`load_shortlist() -> LoadedConfig`.

- [ ] **1.1 Write failing configuration tests.** Use the canonical loader with an
  explicit empty environment; do not instantiate a second config graph.

```python
from pathlib import Path

import pytest

from trading_bot.config import load_config

CONFIGS = Path("configs")


def load_shortlist():
    return load_config(
        CONFIGS / "base.yaml", CONFIGS / "options/shortlist.yaml",
        CONFIGS / "safety-envelope.yaml", {},
    )


def test_explicit_research_profile_only_and_unchanged_risk():
    loaded = load_shortlist()
    settings = loaded.config.options.research_shortlist
    assert settings.enabled is True
    assert (settings.min_dte, settings.target_dte, settings.max_dte) == (21, 30, 45)
    assert settings.max_input_records == 25_000
    assert settings.max_input_bytes == 16 * 1024 * 1024
    assert settings.max_json_depth == 16
    assert settings.max_decision_sessions == 1
    assert loaded.config.options.live_supported is False
    assert loaded.config.options.max_per_trade_loss_usd == 50
    assert loaded.config.options.cumulative_trial_loss_limit_usd == 50


@pytest.mark.parametrize("mode", ["paper", "shadow", "micro_live", "live"])
def test_shortlist_cannot_enable_in_operating_modes(mode):
    with pytest.raises(ValueError):
        load_config(
            CONFIGS / "base.yaml", CONFIGS / "options/shortlist.yaml",
            CONFIGS / "safety-envelope.yaml", {"TRADING_BOT__MODE": mode},
        )


@pytest.mark.parametrize("field,value", [
    ("MIN_DTE", "20"), ("TARGET_DTE", "31"), ("MAX_DTE", "46"),
    ("MAX_INPUT_RECORDS", "25001"), ("MAX_INPUT_BYTES", "16777217"),
    ("MAX_JSON_DEPTH", "17"), ("MAX_DECISION_SESSIONS", "2"),
    ("MAX_INPUT_RECORDS", "true"), ("MAX_INPUT_BYTES", "16.0"),
    ("UNDERLYING", "QQQ"), ("VERSION", "custom-v2"),
])
def test_fixed_policy_and_resource_ceiling_cannot_be_overridden(field, value):
    with pytest.raises(ValueError):
        load_config(
            CONFIGS / "base.yaml", CONFIGS / "options/shortlist.yaml",
            CONFIGS / "safety-envelope.yaml",
            {f"TRADING_BOT__OPTIONS__RESEARCH_SHORTLIST__{field}": value},
        )
```

Also assert base and ordinary `options/simulation.yaml` remain shortlist-disabled;
lower positive resource caps change the resolved config hash; zero/negative/bool
limits fail; options-disabled + shortlist-enabled fails; policy and tie enums cannot
change. Existing historical hashes/readers are not rewritten to match the new graph.

- [ ] **1.2 Run RED.**

```sh
uv run pytest tests/unit/config/test_options_shortlist_config.py -q
```

Expected: new profile/settings missing, not an unrelated import/environment failure.

- [ ] **1.3 Add exact configuration, envelope checks and research records.**

```python
class OptionsShortlistSettings(StrictModel):
    enabled: StrictBool = False
    underlying: Literal["SPY"] = "SPY"
    version: Literal["spy-prior-close-atm-30d-v1"] = "spy-prior-close-atm-30d-v1"
    reference: Literal["previous_regular_session_close"] = "previous_regular_session_close"
    strike_tie: Literal["lower_strike"] = "lower_strike"
    expiry_tie: Literal["earlier_expiry"] = "earlier_expiry"
    min_dte: StrictInt = Field(default=21, ge=21, le=21)
    target_dte: StrictInt = Field(default=30, ge=30, le=30)
    max_dte: StrictInt = Field(default=45, ge=45, le=45)
    max_input_records: StrictInt = Field(default=25_000, ge=1, le=25_000)
    max_input_bytes: StrictInt = Field(default=16_777_216, ge=1, le=16_777_216)
    max_json_depth: StrictInt = Field(default=16, ge=1, le=16)
    max_decision_sessions: StrictInt = Field(default=1, ge=1, le=1)
```

Add `research_shortlist: OptionsShortlistSettings = Field(default_factory=OptionsShortlistSettings)`
to `OptionsSettings`. The default preserves construction of older programmatic config
objects, not their newly computed hashes. Add the AppConfig model validator guard:

```python
if self.options.research_shortlist.enabled and (
    not self.options.enabled
    or self.mode not in {ExecutionMode.BACKTEST, ExecutionMode.SIMULATION}
):
    raise ValueError("shortlist requires an explicit offline options research mode")
```

Keep the existing paused/live/options mode checks. In `enforce_safety_envelope`, use
existing `_require_not_enabled` for shortlist enabled, `_require_at_most` for the four
resource bounds, and exact equality for underlying/version/reference/ties/DTE.
Do not weaken the envelope or change any existing option/risk field. Record all
settings explicitly under `options.research_shortlist` in base/envelope YAML; only
envelope `enabled` is true. The research profile is:

```yaml
mode: simulation
live_trading_enabled: false
options:
  enabled: true
  research_shortlist:
    enabled: true
equities:
  enabled: false
crypto:
  enabled: false
prediction_markets:
  simulation_enabled: false
```

Define these frozen, slotted dataclasses in `options_shortlist_models.py`. All shown
fields are required except the four non-init result flags. Literal annotations require
explicit runtime checks; dataclass type hints alone are not validation.

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from trading_bot.domain import Bar, CorporateAction, DataHash
from trading_bot.domain.options import OptionKind, OptionSession
from trading_bot.market_data.options_records import OptionsDataRecord

type SourceKind = Literal["synthetic", "imported"]


@dataclass(frozen=True, slots=True)
class ShortlistEvidence:
    source: str
    source_kind: SourceKind
    raw_hash: DataHash
    available_at: datetime
    covers_from: datetime
    covers_through: datetime
    semantics: Literal["synthetic-shortlist-v1", "unverified-import-v1"]


@dataclass(frozen=True, slots=True)
class ShortlistCalendarDay:
    trading_date: date
    regular_session: OptionSession | None  # None explicitly declares a closure.


@dataclass(frozen=True, slots=True)
class ShortlistCalendar:
    evidence: ShortlistEvidence
    days: tuple[ShortlistCalendarDay, ...]


@dataclass(frozen=True, slots=True)
class ShortlistClose:
    bar: Bar
    available_at: datetime
    price_basis: Literal["unadjusted"]
    coverage_label: Literal["source_last_trade", "official_consolidated_close"]
    evidence: ShortlistEvidence


@dataclass(frozen=True, slots=True)
class ShortlistDiscontinuity:
    instrument_id: str
    action_type: Literal["merger", "denomination_change", "deliverable_change", "unknown"]
    effective_date: date
    announced_at: datetime
    data_hash: DataHash


@dataclass(frozen=True, slots=True)
class ShortlistAction:
    action: CorporateAction | ShortlistDiscontinuity
    available_at: datetime


@dataclass(frozen=True, slots=True)
class ShortlistSessionInput:
    current_session: OptionSession
    prior_session: OptionSession | None
    calendar: ShortlistCalendar | None
    closes: tuple[ShortlistClose, ...]
    action_evidence: ShortlistEvidence | None
    actions: tuple[ShortlistAction, ...]
    option_source: str
    chain_evidence: ShortlistEvidence | None
    records: tuple[OptionsDataRecord, ...]
    source_kind: SourceKind


@dataclass(frozen=True, slots=True)
class OptionsShortlistCandidate:
    session_id: str
    as_of: datetime
    kind: OptionKind
    contract_id: str
    standardized_id: str
    expiration: date
    strike: Decimal
    reference_close_hash: DataHash
    selected_input_hashes: tuple[tuple[str, DataHash], ...]


@dataclass(frozen=True, slots=True)
class OptionsShortlistResult:
    version: str
    session_id: str
    as_of: datetime
    source_kind: SourceKind
    config_hash: DataHash
    code_hash: DataHash
    input_hash: DataHash
    decision_hash: DataHash
    status: Literal["selected", "no_candidate"]
    reasons: tuple[str, ...]
    candidates: tuple[OptionsShortlistCandidate, ...]
    input_record_count: int
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
```

Keep validation local and explicit. Reuse existing exact validators and domain
constructors; never mutate an existing frozen instance. Enforce exact nested classes,
tuple members, nonempty identifiers, SHA-256 lowercase hex, finite bounded Decimal,
exact dates/UTC datetimes, Literal values and exact nonnegative integers. Reject
duplicate calendar dates; evidence start <= end; availability >= bar end/action
announcement; source kind and semantics must agree. All nested evidence and records
must match the envelope's origin; chain record sources must equal `option_source`.
Allow only chain/contract records in `records`; quotes, sessions and actions cannot
be smuggled through that collection. Actions use the explicit `actions` wrapper.
The existing CorporateAction accepts only `split` and `dividend`; retain that
validator unchanged. The new research-only ShortlistDiscontinuity represents merger,
denomination/deliverable changes and an explicitly unclassified event (`unknown`).
It is not a second trading corporate-action model and cannot enter legacy records.
Validate its exact date, UTC announcement, instrument and digest at the wrapper.

Missing evidence (`None`), empty closes/chain, gaps in calendar declarations and
future observations are representable inputs for a no-candidate decision. Malformed
types, inconsistent identities or mixed origins are input errors. A sorted calendar
may have missing dates, but the selector denies those gaps rather than guessing.
Normalize order only for comparison/hashing; preserve full input integrity separately.

Results validate `selected` iff exactly `(CALL, PUT)` at one expiry with no reasons;
`no_candidate` iff empty candidates and a nonempty recognized reason tuple. Candidates
carry no order side, price, quantity, account or execution instruction. Result counts
are derived for reporting: one decision session, `len(candidates)` candidates and
zero/one denied sessions. All source-evidence combinations are checked again at the
selection boundary; direct Python calls must not bypass validation.

**Imported lane resolution:** This milestone has no authenticated/reviewed native
normalizer or trusted evidence registry. Therefore structurally valid imported inputs
are accepted for inspection but return `source_evidence_unverified`, never candidates.
No `verified=true`, signature-shaped string or user-supplied hash can unlock that lane.
This implements the spec's unresolved-evidence denial; it does not claim to complete
the real-data dependency. Synthetic success is permanently labeled synthetic.

- [ ] **1.4 Create fabricated shared fixtures and RED model tests.** In the test-only
  helper use default target `2024-01-02` 09:30–16:00 New York and prior `2023-12-29`
  09:30–16:00; explicitly include Dec 30/31 and Jan 1 as closed calendar days. Build
  custom-session fixture calendars from the supplied endpoints, declaring intermediate
  dates closed in that fabricated case; this convenience must never enter production.
  Evidence is source `synthetic-shortlist`, origin synthetic, known before prior open,
  covers prior open through target close, and uses `content_hash` of a labeled fixture.

```python
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_bot.domain.options import OptionSession


def fixture_session(day: date, close: time = time(16)) -> OptionSession:
    zone = ZoneInfo("America/New_York")
    return OptionSession(
        f"synthetic-regular-{day.isoformat()}",
        datetime.combine(day, time(9, 30), zone).astimezone(UTC),
        datetime.combine(day, close, zone).astimezone(UTC),
        day, "America/New_York",
    )
```

`make_case` creates a `Bar(SPY, ONE_DAY, prior.open, prior.close, 100, 101, 99,
100, 1000, synthetic-shortlist, fixture_hash, interpolated=False)` using Decimal
and existing typed identifiers. Bar availability is prior close + one minute.
For each DTE create call and put definitions at strikes 99 and 101 with explicit
target eligible sessions. Expiry is target date + DTE, last trading is expiry
16:00 New York, settlement last trading + one day, availability prior open - one day.
Use the standard fields American/shares/PM, multiplier/deliverable100, SPY, USD,
unadjusted and tick0.01. Stable IDs include kind/expiry/strike; standardized IDs use
`SPY   YYMMDDC/P` plus eight-digit strike*1000, without float conversion. Wrap each
definition in `OptionsDataRecord` and create one ChainSnapshot containing all IDs,
both known before target open. No bid/ask or return values exist in the fixture.

```python
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from trading_bot.domain.decimal_utils import DomainValidationError


@pytest.mark.parametrize("bad", [True, 100.0, Decimal("NaN"), Decimal("Infinity")])
def test_close_rejects_inexact_or_nonfinite_money(bad):
    case = make_case()
    with pytest.raises(DomainValidationError):
        replace(case.closes[0].bar, close=bad)


def test_input_is_frozen_and_import_origin_cannot_be_mixed():
    case = make_case()
    with pytest.raises(FrozenInstanceError):
        case.option_source = "changed"
    with pytest.raises(DomainValidationError):
        replace(case, source_kind="imported")
```

Also test exact OptionKind/date/session classes; mutated availability/source/basis;
boolean counts; malformed hashes; unknown semantics; unauthorized result constructor
flags; adjusted contract rejection by the unchanged domain class. Do not use
`object.__setattr__` or `model_construct` to manufacture nominally valid fixtures.

- [ ] **1.5 Run GREEN and review.**

```sh
uv run pytest tests/unit/config/test_options_shortlist_config.py tests/unit/config/test_options_config.py tests/unit/research/test_options_shortlist_models.py tests/unit/domain/test_options.py -q
uv run ruff check src/trading_bot/config src/trading_bot/research/options_shortlist_models.py tests/unit/config/test_options_shortlist_config.py tests/unit/research
uv run mypy src
git diff --check
```

Require unchanged live locks and legacy options tests; review policy/envelope equality
and exact numeric handling before the commit.

- [ ] **1.6 Commit only Task 1 paths**, message `feat: define offline options shortlist inputs and settings`.

## Task 2: Pure causal selector with explicit refusals

**Files:** Create `research/options_shortlist.py` and
`tests/unit/research/test_options_shortlist.py`; extend the shared fixture helper only
as needed for the concrete cases below. Do not modify point-in-time/domain primitives.

**Interfaces consumed:** Task 1 records/settings; existing
`point_in_time(records: tuple[OptionsDataRecord, ...], *, as_of: datetime)` and
`select_chain(records, *, source: str, underlying: str, as_of: datetime)`.

**Interface produced:**
`select_options_shortlist(session: ShortlistSessionInput, *, settings: OptionsShortlistSettings,
config_hash: DataHash, code_hash: DataHash, input_hash: DataHash) -> OptionsShortlistResult`.
Invalid shapes or contradictory economic identities raise `DomainValidationError`;
well-formed unselectable data returns `no_candidate` with stable reason codes.

- [ ] **2.1 Write RED policy/causality tests**, with this test helper locally defined:

```python
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from itertools import permutations

import pytest

from trading_bot.domain import DataHash
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_shortlist import select_options_shortlist
from tests.unit.research._options_shortlist_fixtures import make_case, load_shortlist


def select(case):
    loaded = load_shortlist()
    return select_options_shortlist(
        case, settings=loaded.config.options.research_shortlist,
        config_hash=loaded.config_hash, code_hash=DataHash("b" * 64),
        input_hash=content_hash(case),
    )


@pytest.mark.parametrize("dtes,chosen", [
    ((20,), None), ((21,), 21), ((30,), 30), ((45,), 45),
    ((46,), None), ((29, 31), 29), ((21, 30, 45), 30),
])
def test_exact_dte_boundaries_and_earlier_expiry_tie(dtes, chosen):
    case = make_case(dtes=dtes)
    result = select(case)
    if chosen is None:
        assert result.status == "no_candidate"
        assert result.candidates == ()
    else:
        assert tuple(x.kind.value for x in result.candidates) == ("call", "put")
        assert {x.expiration for x in result.candidates} == {
            case.current_session.trading_date + timedelta(days=chosen)
        }
        assert [x.strike for x in result.candidates] == [Decimal("99"), Decimal("99")]


def test_future_rows_do_not_change_decision_or_candidates():
    case = make_case()
    before = select(case)
    future = replace(
        case.records[0],
        event_at=case.current_session.opens_at + timedelta(minutes=1),
        available_at=case.current_session.opens_at + timedelta(minutes=1),
    )
    after = select(replace(case, records=case.records + (future,)))
    assert after.candidates == before.candidates
    assert after.decision_hash == before.decision_hash
    assert after.input_hash != before.input_hash


def test_record_order_does_not_change_decision_hash():
    case = make_case()
    before = select(case)
    # Five records in the default fixture: all 120 permutations remain bounded.
    for rows in permutations(case.records):
        result = select(replace(case, records=rows))
        assert result.candidates == before.candidates
        assert result.decision_hash == before.decision_hash
```

Use record type, not an assumed tuple index, when targeting a specific chain or
contract revision in additional tests. Add future chain, definition, bar and action
revisions independently, including conflicting future rows that must be ignored.
Same-time conflicting visible rows deny; later available visible revisions supersede
earlier ones using the existing PIT semantics. A future-only prior close yields no
candidate, not a previous-day fallback.

- [ ] **2.2 Run RED.**

```sh
uv run pytest tests/unit/research/test_options_shortlist.py -q
```

Expected: missing selector; then failing causal/policy assertions as cases are added.

- [ ] **2.3 Implement the selection pipeline and hash contract.** Validate exact types
  and resource record count before selection. Settings disabled returns
  `shortlist_disabled`. Apply one deterministic first-failure reason in this order:

| Priority | Check | Reason |
| --- | --- | --- |
| 1 | Entire imported lane; missing/unknown chain semantics | `source_evidence_unverified` |
| 2 | Missing, late, uncovered or gapped calendar; current/prior not adjacent eligible regular sessions | `calendar_unverified` |
| 3 | Missing immediate-prior bar, wrong bounds/source, interpolated or unavailable | `prior_close_unavailable` |
| 4 | Missing/late/insufficient corporate-action coverage or unknown visible action type | `action_coverage_unverified` |
| 5 | Visible intervening split/merger/denomination/deliverable change | `reference_discontinuity` |
| 6 | Missing/late/incomplete chain membership or definitions | `chain_unavailable` |
| 7 | No expiry in range with eligible call AND put | `no_common_eligible_expiry` |

Contradictory visible definitions with duplicate economic identity, inconsistent OCC
identity or conflicting simultaneous revisions are invalid inputs, not recoverable
sorting ties. At the CLI they become a sanitized nonzero input denial. Mixed origins,
invalid shapes and oversized documents are likewise not ordinary `no_candidate`.

Calendar verification compares current/prior identities and all inclusive calendar
dates between them; each date must be declared once, with no intervening open session.
All regular sessions must be `America/New_York`. Calendar evidence must be available
at decision and cover prior open through target open. Validate supplied bounds; do not
hard-code the daily UTC offset or invent a holiday calendar. Future calendar evidence
does not certify an earlier decision.

Among visible close revisions for the exact prior session select the latest
`available_at`; two unequal observations at that same availability are invalid.
Require ONE_DAY classification plus exact regular-session bounds, matching SPY/source,
positive unadjusted non-interpolated close and evidence available at decision covering
the whole prior session. Bars with different boundaries cannot supply the reference.
Wrong-day/UTC-daily rows do not become an older fallback. Preserve coverage labels.

Action evidence must cover prior close through target open. Select only announced
and available actions at decision; preserve visible cash dividends as context without
adjusting the close. Because CorporateAction has date precision, conservatively treat
events dated from prior trading date through target trading date inclusive as possibly
intervening. Deny the named discontinuity types; unknown visible types deny coverage.
Document this deliberate conservative treatment, not fabricated intraday timing.

Use `point_in_time` and `select_chain` for one explicit SPY source. Bind the latest
visible ChainSnapshot and every member's visible definition before eligibility/ranking.
Ignore unused nonmembers for selection/hash, but never omit a missing declared member.
Contract eligibility covers `opens_at <= decision < closes_at`, with contract and
record availability <= decision and last trading after decision. A standard OCC
symbol must agree with SPY/expiry/kind/strike (three root-padding spaces, six date
digits, C/P and eight strike digits at 1/1000 units); a conflicting identity is an
input error. Do not import a diagnostics/provider module to validate this identity.

Check duplicate economic identities `(underlying, expiration, kind, strike,
premium_multiplier, deliverable_units, deliverable_symbol, exercise_style,
settlement_kind, settlement_timing, currency)` among visible declared members before
ranking. Distinct IDs cannot disguise the same instrument; no contract-ID tiebreaker.

The ranking kernel consumes only eligible contracts, the Decimal reference close and
the explicit trading date. Use this ordering; do not rank by costs or results:

```python
by_expiry: dict[date, dict[OptionKind, list[OptionContract]]] = {}
for contract in eligible_contracts:
    dte = (contract.expiration - trading_date).days
    if settings.min_dte <= dte <= settings.max_dte:
        sides = by_expiry.setdefault(contract.expiration, {})
        sides.setdefault(contract.kind, []).append(contract)
common = [
    expiry for expiry, sides in by_expiry.items()
    if sides.get(OptionKind.CALL) and sides.get(OptionKind.PUT)
]
# If common is empty, return the no_common_eligible_expiry result above.
if common:
    expiry = min(common, key=lambda day: (
        abs((day - trading_date).days - settings.target_dte), day,
    ))
    chosen = tuple(
        min(by_expiry[expiry][kind], key=lambda item: (
            abs(item.strike - reference_close), item.strike,
        ))
        for kind in (OptionKind.CALL, OptionKind.PUT)
    )
```

Define `input_record_count` as options records + close observations + action
observations + calendar day declarations. Count even future observations; exceeding
the configured cap is input failure before selection. The single session itself and
fixed evidence wrappers do not add records. Bound all collections under this sum.

**Decision hash:** canonical content hash of version, resolved config hash, code
hash, decision identity, ordered reasons, selected effective evidence, full visible
declared chain member set with definitions, reference close, visible action context
and ordered winning IDs. Sort calendar days, chain member IDs, records by logical
identity and hash, action context and named evidence roles. Preserve original raw
hashes in audit output but canonicalize member-order meaning for the decision
fingerprint; permutations of the same declared member set must not change selection.
Never include the full input hash, raw collection length, irrelevant future values,
file path, wall clock or invocation randomness in the decision hash. On denials,
hash the examined visible evidence and reason, not inaccessible future payloads.

Candidate `selected_input_hashes` uses fixed sorted roles `calendar`, `chain`,
`contract`, `prior_close`, `action_coverage` plus visible action hashes indexed by
canonical action identity. Its `reference_close_hash` is the selected wrapper's
canonical hash, including source/availability/basis. No decision-hash/candidate-hash
cycle: compute candidate evidence first, then decision hash, then result.
The `chain` role is the canonical hash of source, origin, raw hash, event/availability,
underlying and **sorted member IDs**, not the order-sensitive legacy record hash.
Do not change the original record or its legacy hash. Thus reordering membership
with unchanged provenance does not leak input ordering through a candidate hash.

- [ ] **2.4 Add calendar/discontinuity/adversarial tests before their implementation.**

```python
from datetime import date, time
from tests.unit.research._options_shortlist_fixtures import fixture_session


@pytest.mark.parametrize("prior_day,target_day,prior_close", [
    (date(2024, 1, 5), date(2024, 1, 8), time(16)),
    (date(2023, 12, 29), date(2024, 1, 2), time(16)),
    (date(2024, 3, 8), date(2024, 3, 11), time(16)),
    (date(2024, 11, 1), date(2024, 11, 4), time(16)),
    (date(2024, 11, 29), date(2024, 12, 2), time(13)),
])
def test_explicit_regular_sessions_survive_closures_and_dst(prior_day, target_day, prior_close):
    case = make_case(
        current=fixture_session(target_day), prior=fixture_session(prior_day, prior_close),
    )
    result = select(case)
    assert result.status == "selected"
    assert all(row.as_of == case.current_session.opens_at for row in result.candidates)


@pytest.mark.parametrize("field,value,reason", [
    ("calendar", None, "calendar_unverified"),
    ("closes", (), "prior_close_unavailable"),
    ("action_evidence", None, "action_coverage_unverified"),
    ("chain_evidence", None, "source_evidence_unverified"),
    ("records", (), "chain_unavailable"),
])
def test_missing_inputs_deny_without_fallback(field, value, reason):
    result = select(replace(make_case(), **{field: value}))
    assert result.status == "no_candidate"
    assert result.reasons == (reason,)
    assert result.candidates == ()
```

Concrete additional cases: move the bar start to UTC midnight; extend its close to
16:15 New York; delete a declared closed date; insert an intervening open session;
make chain coverage too short or available one microsecond after decision; remove a
declared member's definition; provide only calls at 30 DTE and puts at 31 DTE; provide
calls at99/101 and puts at102/104 and assert chosen99/102; duplicate a visible economic
identity under another ID and require an error. Reverse chain member order without
changing raw provenance and assert stable decision hash. Supply an imported-only
otherwise valid case and assert `source_evidence_unverified`.

For a `split`, construct a CorporateAction with positive split ratio; for `merger`,
`denomination_change` and `deliverable_change`, construct ShortlistDiscontinuity.
Make each effective on target date, announced/available before open; expect
`reference_discontinuity`. A visible CorporateAction of type `dividend` changes
context/hash but not chosen contracts/reference price. A ShortlistDiscontinuity of
type `unknown` yields `action_coverage_unverified`. Future-only actions do not change
the earlier hash. Never broaden the existing CorporateAction validator.

Assert every result flag is false; flag assignment raises FrozenInstanceError;
`replace(result, live_authorized=True)` raises ValueError for a non-init field.
Neither input nor candidate has quantity/limit-price/account fields. Subsequent quote
absence is not an argument to this API and cannot select a replacement.

- [ ] **2.5 Run GREEN and unchanged primitive/economics regressions.**

```sh
uv run pytest tests/unit/research/test_options_shortlist.py tests/unit/research/test_options_shortlist_models.py tests/unit/market_data/test_options_records.py tests/unit/domain/test_options.py tests/unit/risk -q
uv run ruff check src/trading_bot/research tests/unit/research
uv run mypy src
git diff --check
```

Require an independent read-only review of causality, policy adherence and imported
denials; the coordinator resolves findings and reruns impacted tests before commit.

- [ ] **2.6 Commit only Task 2 paths**, message `feat: add deterministic research-only SPY shortlist selection`.

## Task 3: Strict wire format and private no-overwrite manifest IO

**Files:** Create `options_shortlist_wire.py`, `options_shortlist_io.py` and their
two unit test files. Existing bundle/options codecs and storage primitives are read-only.

**Interfaces consumed:** Tasks 1–2; `BundleLimits`; `bundle_codec._json`, `_mapping`,
`_array`, `_integer`, `_decimal`, `_time`, `_date`, `_digest`, `_value("bar", value)`;
`options_data_codec.encode_record` / `decode_record(encoded, *, limits)`; strict
`_session` decoder; storage `_open_root`, `_read`, `_subdirectory`, `_publish`.
These private helpers already exist; confine their imports to these adapter modules.

**Interfaces produced:**

| Function | Exact interface |
| --- | --- |
| `shortlist_limits` | `(settings: OptionsShortlistSettings) -> BundleLimits` |
| `encode_shortlist_input` | `(session: ShortlistSessionInput) -> bytes` |
| `decode_shortlist_input` | `(encoded: bytes, *, settings: OptionsShortlistSettings) -> ShortlistSessionInput` |
| `read_shortlist_input` | `(input_path: Path, *, settings: OptionsShortlistSettings, repository_root: Path) -> tuple[ShortlistSessionInput, DataHash]` |
| `shortlist_code_hash` | `() -> DataHash` |
| `write_shortlist_manifest` | `(root: Path, result: OptionsShortlistResult, *, repository_root: Path, settings: OptionsShortlistSettings) -> DataHash` |

Use a small `ShortlistFileError(ValueError)` exposing only a fixed `code` from
`shortlist_input_invalid`, `shortlist_path_invalid`, `shortlist_storage_conflict`,
`shortlist_storage_unavailable`. Never embed original errors or paths in this class.

- [ ] **3.1 Write RED strict-wire tests.**

```python
import json
from dataclasses import replace

import pytest

from trading_bot.research.options_shortlist_wire import (
    decode_shortlist_input, encode_shortlist_input,
)
from tests.unit.research._options_shortlist_fixtures import make_case, load_shortlist


def test_round_trip_is_exact_and_old_record_schema_unchanged():
    case = make_case()
    settings = load_shortlist().config.options.research_shortlist
    encoded = encode_shortlist_input(case)
    assert decode_shortlist_input(encoded, settings=settings) == case
    assert encode_shortlist_input(decode_shortlist_input(encoded, settings=settings)) == encoded


@pytest.mark.parametrize("fragment", [b"NaN", b"Infinity", b"1.5", b"-0"])
def test_json_numbers_do_not_coerce(fragment):
    settings = load_shortlist().config.options.research_shortlist
    with pytest.raises(ValueError):
        decode_shortlist_input(b'{"schema":' + fragment + b'}', settings=settings)


@pytest.mark.parametrize("extra", ["verified", "live_authorized", "quotes", "returns"])
def test_extra_authority_or_outcome_fields_rejected(extra):
    settings = load_shortlist().config.options.research_shortlist
    wire = json.loads(encode_shortlist_input(make_case()))
    wire[extra] = True
    with pytest.raises(ValueError):
        decode_shortlist_input(json.dumps(wire).encode(), settings=settings)
```

Additionally mutate nested price strings to floats/bools/exponent/nonfinite forms;
use duplicate JSON keys, wrong schema, invalid UTF-8, depth17, >16MiB, >25,000 counted
records, two sessions, malformed hash, reordered valid JSON keys and mixed origins.
Boundary tests use lower configured caps for routine speed plus exact default values
and one full-size rejection test; no provider dataset is required. Reject unsupported
compression before parsing. Record count is the Task 2 definition, not all array
members (the existing replay counter counts differently and is not reused).

- [ ] **3.2 Run RED.**

```sh
uv run pytest tests/unit/research/test_options_shortlist_wire.py -q
```

- [ ] **3.3 Implement the versioned input and manifest codecs.** The input top-level
  keys are exactly `schema` and `sessions`, with schema `options-shortlist-input-v1`
  and sessions an array of exactly one Task 1 session object. Its field names exactly
  match Task 1; optional evidence/prior fields are explicit JSON null, not omitted.
  Evidence/close/calendar/action objects have the exact corresponding field sets.

Use canonical financial strings, UTC microsecond `Z` timestamps, ISO dates, JSON
arrays for tuples and exact bool types. Encode nested Bar/CorporateAction fields
with existing canonical serialization. Decode Bar with `_value("bar", value)`,
split/dividend actions with `_value("corporate_action", value)`, then require the exact
resulting domain type. For research-only discontinuities use the exact five-field
ShortlistDiscontinuity shape and allowed action types; reject hybrid/missing/extra
fields. No generic unvalidated union coercion or modification of the legacy decoder.
Decode OptionSession via the existing strict `_session`, not permissive direct
dataclass deserialization. Each `records` item is the full existing
`options-data-record-v1` envelope from `encode_record`; decode with the existing
hash-verifying `decode_record`, then require kind chain/contract. Never rewrite its
schema, recorded hash, provider source or source kind.

```python
def shortlist_limits(settings: OptionsShortlistSettings) -> BundleLimits:
    return BundleLimits(
        max_envelope_bytes=settings.max_input_bytes,
        max_blob_bytes=settings.max_input_bytes,
        max_total_bytes=settings.max_input_bytes,
        max_records=settings.max_input_records,
        max_json_depth=settings.max_json_depth,
    )
```

The decoder calls bounded `_json` before inspecting exact keys; then validates all
collection lengths/counts before constructing nested records. Existing per-record
codec verifies hashes. Re-encoding validates canonical *values*, not JSON whitespace
or input key order. Input integrity returned by IO is SHA-256 of the actual bytes read,
not proof of source authenticity. A caller-provided input digest is never trusted.

Manifest payload has exactly `schema` (value `options-shortlist-manifest-v1`) and
`result` (the complete Task 1 result object plus derived counts);
serialize all result fields, including false flags, plus derived decision/candidate/
denied-session counts. The filename hash is `content_hash(payload)` and the body is
`canonical_json(payload).encode("utf-8")`; there is no self-referential manifest hash
inside the payload. Do not embed input file paths, raw records, credentials or account
information. Manifests contain private selected symbols/strikes and therefore still
require owner-only storage. Reject a manifest exceeding the configured byte ceiling.

- [ ] **3.4 Add RED private IO/failure tests.** Use `tmp_path.resolve()` so macOS `/var`
  aliases do not accidentally introduce a symlink parent. Explicitly create 0700 root
  and 0600 input files outside a distinct fake repository directory.

```python
import os
from pathlib import Path

from trading_bot.research.options_shortlist_io import read_shortlist_input


def test_symlink_input_rejected_without_following_target(tmp_path):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    repository = tmp_path.resolve() / "repo"
    repository.mkdir()
    target = root / "actual.json"
    target.write_bytes(encode_shortlist_input(make_case()))
    target.chmod(0o600)
    alias = root / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(ValueError):
        read_shortlist_input(
            alias, settings=load_shortlist().config.options.research_shortlist,
            repository_root=repository,
        )
    assert target.read_bytes() == encode_shortlist_input(make_case())
```

Add tests for 0755 roots, 0644 input, symlink ancestors, repository-local output, `..`,
FIFO, missing path, oversized stat, file growth after stat, malformed names, manifest
collision (different preexisting bytes remain unchanged), deterministic equal rerun,
short writes, zero write, failed link, and directory fsync uncertainty. Reuse the
existing bundle-store fault injection patterns with these new public wrappers; do
not assume helper tests alone prove the new composition. No fallback ordinary write.

- [ ] **3.5 Implement narrow descriptor-safe wrappers.** Validate absolute paths,
  no `..`, input basename not empty/dot/dot-dot and no slash, root outside the actual
  repository, exact private modes and owner. Use fixed subdirectory
  `options-shortlists`; generated names are only validated 64-hex digest + `.json`.
  Never pass caller-supplied directory/digest fragments into private storage helpers.

```python
with ExitStack() as stack:
    parent = _open_root(input_path.parent, repository_root)
    stack.callback(os.close, parent)
    encoded = _read(parent, input_path.name, settings.max_input_bytes)
session = decode_shortlist_input(encoded, settings=settings)
return session, DataHash(hashlib.sha256(encoded).hexdigest())
```

Publication uses `_open_root`, `_subdirectory(parent, "options-shortlists", create=True)`
and `_publish` within ExitStack. Existing equal bytes are idempotent; conflicts fail.
If directory fsync fails after link, return unavailable/uncertain, never claim no
artifact exists or delete it; retrying equal bytes re-establishes durability.
Map errors to fixed codes and suppress exception context at the CLI boundary.

`shortlist_code_hash` hashes a fixed list of installed files by stable relative path
and SHA-256: the four new research modules, `cli/options_research.py`,
`config/models.py`, `config/loader.py`, `domain/options.py`, `domain/market.py`,
`domain/decimal_utils.py`, `clock.py`, `market_data/options_records.py`,
`market_data/options_data_codec.py`, `market_data/bundle_codec.py`,
`market_data/bundle_models.py`, `market_data/bundle_store.py`, and
`market_data/recording.py`. Use resolved module-root-relative paths, no Git subprocess,
home-directory search, environment keys or provider reads. Missing files deny; no
default all-zero hash. This is scoped research-code identity, not image attestation
or proof of every transitive dependency; the unchanged lockfile hash is recorded in
the operator validation report, not synthesized into live authorization.

- [ ] **3.6 Run GREEN and storage/legacy regressions.**

```sh
uv run pytest tests/unit/research/test_options_shortlist_wire.py tests/unit/research/test_options_shortlist_io.py tests/unit/market_data/test_bundle_codec.py tests/unit/market_data/test_options_data_codec.py tests/unit/simulation/test_options_replay_wire.py tests/unit/simulation/test_options_replay_filesystem.py tests/integration/market_data/test_bundle_store.py -q
uv run ruff check src/trading_bot/research tests/unit/research
uv run mypy src
git diff --check
```

Review no raw errors/paths, no unchecked path components, no old schema/hash changes
and no rewriting tracked/private artifacts before commit.

- [ ] **3.7 Commit only Task 3 paths**, message `feat: persist bounded private options shortlist manifests`.

## Task 4: Offline CLI, documentation and full regression evidence

**Files:** Modify `cli/options_research.py` and its existing import-boundary integration
test; create `tests/integration/cli/test_options_shortlist.py` and
`docs/options-research-shortlist.md`. Do not edit dirty `cli/main.py` or README.

**Interfaces consumed:** Tasks 1–3; existing Typer app and canonical config loader.

**Interfaces produced:**
`python -m trading_bot.cli.options_research options-shortlist INPUT_PATH --output-dir PRIVATE_ROOT [--config-dir configs]`.
Exit0 for selected or valid no_candidate; exit1 for schema/type/config/IO denial.
No `--live`, `--provider`, `--token`, `--download`, balance, quote or override parameters.

- [ ] **4.1 Write RED CLI and non-capability tests.** Test modules must block all
  network attempts with the existing socket guards, including `connect_ex`. Add fake
  secret paths/values to fixtures, but do not inspect real credentials. Guard
  `os.getenv` and relevant `os.environ` credential-key accesses during invocation;
  reject filesystem attempts outside explicitly allowed config/source/input/output
  and test infrastructure paths. Import-time IO needs a subprocess or import guard
  established before importing the new composition. Make the guard assert it is
  active with a deliberate denied access inside the test; do not merely omit secrets.

```python
import json
from pathlib import Path

from typer.testing import CliRunner
from trading_bot.cli.options_research import app
from trading_bot.research.options_shortlist_wire import encode_shortlist_input
from tests.unit.research._options_shortlist_fixtures import make_case


def test_cli_publishes_private_pair_without_disclosing_rows(tmp_path):
    root = tmp_path.resolve() / "shortlist-private"
    root.mkdir(mode=0o700)
    input_path = root / "input.json"
    input_path.write_bytes(encode_shortlist_input(make_case()))
    input_path.chmod(0o600)
    args = ["options-shortlist", str(input_path), "--output-dir", str(root)]
    first = CliRunner().invoke(app, args)
    second = CliRunner().invoke(app, args)
    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout
    row = json.loads(first.stdout)
    assert set(row) == {"status", "decision_sessions", "candidate_count",
                        "denied_sessions", "reasons", "manifest_hash"}
    assert row["status"] == "selected"
    assert row["candidate_count"] == 2
    assert str(root) not in first.stdout
    assert "SPY   " not in first.stdout
    artifact = root / "options-shortlists" / (row["manifest_hash"] + ".json")
    stored = json.loads(artifact.read_text())["result"]
    for flag in ("production_eligible", "evidence_promotable", "download_authorized", "live_authorized"):
        assert stored[flag] is False
```

Add valid missing-prior no_candidate exit0/count0, all-imported unverified exit0,
invalid schema/JSON/limits exit1 without manifest publication, storage failure exit1,
conflict preservation and all-false flags. Prove an environment live flag/credential
does not change config, output, access or candidate order. CLI help exposes no write
or acquisition option. AST import-boundary test scans `research/options_shortlist*.py`
alongside existing paths and rejects broker/persistence/httpx/mcp/subprocess imports;
keep existing risk-economics imports in the broader research CLI valid.

- [ ] **4.2 Run RED.**

```sh
uv run pytest tests/integration/cli/test_options_shortlist.py -q
```

Expected: command absent, then precise integration failures as features are completed.

- [ ] **4.3 Implement only the new command and loader.** Keep existing `_load`
  untouched; add `_load_shortlist(config_dir: Path) -> LoadedConfig` selecting
  `options/shortlist.yaml` with `environ={}`. Compose in this order:

```python
loaded = _load_shortlist(config_dir)
settings = loaded.config.options.research_shortlist
repository = Path(__file__).resolve().parents[3]
session, input_hash = read_shortlist_input(
    input_path, settings=settings, repository_root=repository,
)
result = select_options_shortlist(
    session, settings=settings, config_hash=loaded.config_hash,
    code_hash=shortlist_code_hash(), input_hash=input_hash,
)
manifest_hash = write_shortlist_manifest(
    output_dir, result, repository_root=repository, settings=settings,
)
typer.echo(canonical_json({
    "status": result.status,
    "decision_sessions": 1,
    "candidate_count": len(result.candidates),
    "denied_sessions": int(result.status == "no_candidate"),
    "reasons": result.reasons,
    "manifest_hash": manifest_hash,
}))
```

Wrap config/validation/IO errors at the command boundary and emit only
`{"status":"denied","reason":"options_shortlist_input_invalid"}` or the fixed
storage code, then `typer.Exit(1)`. Do not echo tracebacks, exception strings, input
symbols or filesystem paths. Do not catch `BaseException`; interrupts must propagate.
No success output is emitted before durable publication succeeds.

- [ ] **4.4 Write operator documentation.** Include the exact command above, root 0700/
  file 0600 requirements, one-session/no-compression caps, a complete synthetic schema
  example generated from the committed fixture, stable reason/exit-code table and
  private manifest format. Explain source-last-trade vs official close, causal dates,
  imported lane denial, no quote-based replacement and no economic/live eligibility.
  State normalization, trusted real-data evidence, quote acquisition/cost authorization,
  exits/settlement coverage and preregistered historical research remain separate work.
  Do not claim vendor savings, a complete dataset, profitable returns or Cloud execution.

Document approved budgets/limits unchanged. Preserve the downstream 3,650-calendar-day
request, 750-bar minimum, five folds, at least 50 test bars/fold and 30 independent
opportunities where applicable; this selector needs one close but relaxes none of
those study requirements. Do not choose a strategy exit or holdout after viewing returns.

- [ ] **4.5 Run narrow GREEN, then the baseline with temporary artifacts.** Before
  broad tests, inspect `tests/smoke/test_sbom_reproducible.py` and confirm it still
  writes two temporary outputs, never the tracked SBOM. Do not regenerate the dirty
  SBOM. No lockfile or dependency changes are needed.

```sh
uv run pytest tests/integration/cli/test_options_shortlist.py tests/integration/cli/test_options_research_cli.py tests/integration/cli/test_options_replay_files.py tests/unit/research/test_options_shortlist.py tests/unit/config/test_options_shortlist_config.py -q
uv run ruff check .
uv run mypy src
SHORTLIST_VERIFY_DIR=$(mktemp -d /private/tmp/options-shortlist-verify.XXXXXX)
uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80 --cov-report=json:"$SHORTLIST_VERIFY_DIR/coverage.json"
uv run python scripts/check_critical_branch_coverage.py --report "$SHORTLIST_VERIFY_DIR/coverage.json"
uv run bandit -c pyproject.toml -r src
uv lock --check
uv run pytest tests/smoke/test_sbom_reproducible.py tests/smoke/test_critical_branch_coverage.py -q
uv export --locked --all-groups --no-emit-project --output-file "$SHORTLIST_VERIFY_DIR/locked-requirements.txt" > /dev/null
```

The `uv` environment must be the verified installed locked environment. Do not allow
an incidental sync to replace staged work. If the local project environment stalls,
check whether the previously verified environment still exists at
`/private/tmp/robinhood-anyio-verification.5rJfWx/.venv`, validate its lock compatibility,
then set task-scoped `UV_PROJECT_ENVIRONMENT` to it with `UV_NO_SYNC=1`, `UV_OFFLINE=1`
and `PYTHONPATH=src` for the whole test process (including nested uv commands).
Report unavailable tools instead of claiming a pass or silently installing packages.

Keep 80% overall coverage and the existing 90% per-critical-file branch checks.
The current critical-module discovery does not include arbitrary research files;
add explicit selector/model/wire/IO branch reporting and require 90% for each new
module in this task's acceptance without weakening the existing critical gate.
Read the coverage JSON for each exact new path; a missing/zero-branch entry must be
reviewed, not treated as a pass. No whole-repository threshold is lowered.

Locked-dependency vulnerability audit uses the exported temporary requirements:

```sh
uv run pip-audit --requirement "$SHORTLIST_VERIFY_DIR/locked-requirements.txt" --no-deps --disable-pip
```

This audit may contact public vulnerability services. Run only under applicable
external-access authority; otherwise report **blocked/not run**, preserving the gate.
It is not a broker/data call and is not an offline-test exception. SBOM reproduction
is distinct from completeness: the existing generator emits `components: []` with
a lock digest; do not call that a complete dependency inventory or fix that unrelated
problem in this milestone. Record it as a pre-existing limitation.

For unchanged deployment manifests run shell syntax checks and compose validation,
not deployment:

```sh
for script in infra/digitalocean/*.sh; do sh -n "$script"; done
docker compose config --quiet
git diff --check
git diff --cached --name-status
git status --short
```

If only the standalone `docker-compose` validator is available, use its `config --quiet`
equivalent and record that fact. No Docker service start, image pull, SSH or production
migration. Record baseline failures separately from introduced failures; never label
the complete milestone verified while required checks are red or unperformed.

- [ ] **4.6 Independent final review, corrections and commit.** Give a credential-free
  read-only reviewer the exact committed base, owned paths, this plan/spec and test
  results. Request findings on specification adherence, future leakage, forbidden
  imports, private IO and accidental authorizations. Keep final policy decisions with
  the coordinator; fix findings and rerun impacted narrow plus required broad checks.
  Update the new operator document with actual commands/results and limitations.
  Commit only Task 4 paths, message `feat: expose offline options shortlist research command`.

## Completion and handoff criteria

- A deterministic synthetic fixture runs through CLI → private manifest with a call/
  put pair or a truthful no-candidate result; no provider or broker is contacted.
- Exact policy, chronology, provenance refusal, bounded IO and false flags are tested.
- Existing options risk, replay, source serialization and paused startup remain intact.
- Required validations are green or explicitly reported blocked; no implied overall
  completion when required verification is missing. Dirty user work/index preserved.
- Report research-software readiness separately from genuine data/economic evidence,
  account/runtime capability and operator authorization. All live gates stay closed.
- Next dependent work is separately reviewed normalization/trusted real-data evidence
  and bounded quote-cost/acquisition scope; not automatically authorized by this plan.

## Coordinator self-review of this plan

Spec coverage: §1–2 scope/dependency labels → Global Constraints/execution boundary;
§3 selection/calendar/actions/PIT/ties → Tasks1–2; §4 immutable records/config/hashes/
CLI/privacy → Tasks1–4; §5 exclusions/imported dependency/research minimums → all task
boundaries and Task4 documentation; §6 verification → every RED/GREEN task and final
baseline; §7 human review → execution checkpoint below.

Review Focus mapping: future/reordering → Task2.1/2.3/2.4; calendar/corporate actions →
Task2.4; untrusted evidence → Task1.3/1.4 and Task3.1; input/IO attacks → Task3.1/3.4;
execution coupling → Task1.1, Task2.4, Task4.1. Interfaces use identical names and
field types across model, wire, selector and CLI. No new loader, provider adapter,
strategy-exit policy, live bypass or source-authenticity claim is introduced.

## Execution checkpoint

Written specification approved by the operator's “proceed” on 2026-09-22.
Implementation plan prepared and coordinator-reviewed; **operator plan review and
execution-method choice remain pending**. No implementation tests have been run for
the planned feature and no source/config/product behavior changed by this document.
