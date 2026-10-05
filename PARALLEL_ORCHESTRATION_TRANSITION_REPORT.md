# Parallel Orchestration Transition Report

## Durable owned equity lifecycle candidate — 2026-10-05

This checkpoint supersedes conflicting current software, blocker and dependency
wording below for the focused ETF execution workstream only. All earlier sections
remain immutable historical checkpoints; their revision-specific tests and
operational observations do not certify this candidate. Alpaca remains the sole
market-data source and Robinhood remains the execution-broker target.

The primary coordinator owns the lifecycle specification, implementation,
persistence/recovery integration and release decision. The credential-free
[durable lifecycle contract](docs/etf-durable-equity-lifecycle.md),
[saved specification](docs/superpowers/specs/2026-10-05-etf-durable-equity-lifecycle-design.md)
and [implementation plan](docs/superpowers/plans/2026-10-05-etf-durable-equity-lifecycle.md)
are implemented in a candidate building on reviewed/published head
`5b746c53b68a937e73b994f82beea2bef3c93a4c`, based on
`16048648d7fe8b29010e00505793abb678148a05`, in
[PR #20](https://github.com/Jed1122/Robinhoodtradingbot/pull/20). The specification
is coordinator-written, not a newly operator-reviewed artifact. Publication is
not deployment, research acceptance or live authorization. The exact final
candidate, validation and integration status are recorded in PR #20; this
pre-integration checkpoint does not certify a later revision or a merge result.

The pure `domain/owned_order_lifecycle.py` API supplies `OwnedOrderEvent`,
`encode_owned_event`, `decode_owned_event` and `advance_owned_order` using the
canonical state machine and exact Decimal quantities. Behind the existing
UnitOfWork, `orders.record_event` atomically stages an append-only journal fact,
transition and optional provider-scoped FillRow; `orders.get_broker_order`
reconstructs and validates the owned projection. `fills.get` and
`fills.list_for_account(account_id, since)` return exact recorded fills, not
independently reconciled account or position state. Migration
`0009_owned_order_lifecycle` adds journal/immutable-fill guards without rewriting
historical records; no production migration was performed.

The original OrderRow/submission-response hash remains immutable. The supported
anchor is a known accepted local equity submission with zero fills and a complete
durable intent/review/submission chain. Initial partial/full responses, unknown
acceptance and unowned/external history remain denied; they cannot create local
ownership or justify a submission retry. Every actual fill requires an explicit
fee: unknown fees never become zero. Typed facts and declaration fixtures do not
attest authenticated provenance, final charges or causal broker/quote clocks.
Exact repeated delivery is idempotent, conflicts deny, pending cancellation
survives raced partial fills and terminal states cannot reopen. Recovery verifies
the bound intent/review, original acceptance and all journal/transition/fill links.
Local SQLite isolation and bounded replay are not a live leadership fence or
independently verified deployed-host recovery.

The coordinator reports **423 targeted tests passing** after the recovery
corrections. Two independent candidate-review findings were fixed at the recorded
head. The later GitHub findings are corrected with watched failing regressions:
filled orders cannot reconcile to rejected, zero-fill anchors cannot retain an
average fill price, and this authoritative handoff is refreshed. Final integrated
review, full regression/coverage and exact-head CI for the eventual corrected
candidate are **not certified** by this checkpoint. Earlier full-suite/CI results
cannot certify later corrections. Merge remains pending those exact-final-head
checks and resolution of substantive findings; no check is bypassed.

Subsystem disposition: durable local lifecycle primitive **implemented / release
evidence in PR #20**; protected economic/broker/runtime composition **blocked /
unverified**.
Local credential-free implementation and bounded public fixture/documentation
work remain **GO** under exact-base, disjoint-path contracts. The coordinator
retains exclusive integration ownership of execution, joint economic state,
reconciliation, persistence, risk/fencing, authority and promotion. No private
customer evidence or protected implementation decision is delegated.

The remaining critical path is:

1. Verify the exact corrected lifecycle
   candidate before integration; preserve all existing risk and identity gates.
2. Reconstruct and jointly own cash, positions, reservations, settlement and trial
   history atomically with execution effects. A terminal order alone must not
   release an allocation or imply economic reconciliation.
3. Qualify authenticated nonempty broker history/position reads, exact intent and
   preview matching, final-fee sources and provider write semantics. The supplied
   declaration parser remains unqualified; the empty-only adapter remains locked.
4. Supply concrete fresh initial/final risk context, live leadership/fencing,
   unknown-acceptance reconciliation/recovery and exact one-intent diagnostic
   confirmation. The conditional diagnostic grant does not replace mandatory
   preview confirmation, order policy/limits or protected execution readiness.
5. Obtain genuine fills, final charges and causal Alpaca quote/order clocks;
   complete execution inputs and honest after-cost economics; then qualify the
   trusted paper/shadow composition and independently verify standalone runtime
   recovery. Preserve every research/promotion and elapsed-observation gate.

This slice and report update perform no real provider/broker call, authenticated
read or write, credential/customer-record access, order, production-ledger access,
deployment or live operation. Accepted economics, qualifying paper/shadow evidence,
runtime readiness and live trading remain independently **NO-GO**. No profitability
claim or new source/provenance qualification is made; merge authority is not
activation authority.

## Bounded native quote intake — 2026-10-05

The [versioned catalog](docs/etf-native-quote-catalog.md) implements a separate
private day/study index and capture-bounded native quote iterator. Original
Alpaca receipts and exact Decimal/nanosecond/page/row identities remain intact;
historical controls/gaps remain unobserved under the research waiver. Selected
captures are validated before initial yield, and later traversal errors cannot
certify a completed prefix. Nonselected future raw inputs remain unread.

This is intake only: existing replay/account/statistics/checkpoint limits and
qualified-source factories are unchanged. Whole-study incremental replay,
accepted after-cost results and genuine customer calibration remain unfinished.
No new provider, credentials, broker call, data acquisition, deployment or safety
policy change is included. Fresh preflight denies with
`ready=false/external_capability_missing`. The operator's new one-trade
cost-diagnostic grant is [recorded](docs/operator-authority.md); no order was
placed because authority does not supply missing execution readiness.

Local verification and independent candidate review are recorded in this plan's
ledger/PR, not inferred from earlier revisions. This checkpoint does not assert
merge, complete historical coverage, eligible paper/shadow cycles or live readiness.

## Historical research amendment and native acquisition — 2026-10-05

The operator now explicitly waives historical halt/LULD and gap-coverage proof for
the Alpaca-only exploratory study. The [amended specification](docs/superpowers/specs/2026-09-30-focused-etf-research-design.md)
and [authority](docs/operator-authority.md) supersede conflicting historical research
requirements below. No forward/paper/live safety, risk, cost or promotion gate is
waived; older diagnostic evidence is not rewritten or unlocked.

At committed source `454c6515cce6df883188313f3bffac94a9039b17`, a frozen five-minute
first-eligible-development SPY/SIP request retained 62,346 real quotes over 63 pages.
Raw hashes, receipt chains and private ownership/modes reverified. The combined
coverage audit now reports one quoted development session, zero full requested
sessions, and 63,420 total observations; no holdout was evaluated. Ninety-six
native capture/archive fixture tests passed. This is useful real acquisition,
not completed historical execution coverage or qualified data/economics.

Private invoice/receipt reconciliation supports one attributable operating
payment; it does not supply genuine executions, final per-order fees, slippage or
causal order clocks. Customer calibration remains `BLOCKED_INPUTS`. Next engineering
is separately versioned bounded exploratory source/replay intake under the waiver,
not another provider or a fabricated verified flag. Original records stay outside
Git/Cloud/delegated tasks. The earlier same-date checkpoint below precedes this
amendment/acquisition and is retained as an audit snapshot.

## Fresh execution-readiness reassessment — 2026-10-05

The [current reassessment](docs/etf-execution-readiness-2026-10-05.md) supersedes
the publication-pending wording in the historical checkpoint below. PR #17 is
merged at `38c2d9a948bb963e348be68d1c1cacede48fedce`, with exactly the reviewed
`72fe8a93aacc989f8ff1c2992543ae5056810f1a` tree. A newly retained Alpaca calendar
reference enabled fresh native receipt/date/request-coverage verification:
2,514 bar dates match, but none of 1,262 required development sessions has full
requested quote coverage. Reacquisition reproduces the October 2 coverage-report
identity; it does not restore original retrieval/publication evidence. Private
customer calibration remains `BLOCKED_INPUTS`.

Read-only host access now succeeds; the existing process is healthy, paused and
not ready. Its running container has zero mounts and does not contain either
new forward-owner module. This is not deployed recovery or strategy operation.
Trusted factory/worker/promotion composition, complete historical execution data,
genuine costs and accepted economics remain unfinished. No eligibility clocks
were started, provider/broker writes performed, deployment changed or gate waived.
The older snapshot below is retained as historical publication context.

## Forward-paper economic owner checkpoint — 2026-10-05

This section supersedes older software/dependency status below for the focused ETF
workstream only. Alpaca remains the sole market-data source and Robinhood remains
the execution-broker target. No live, data, cost or promotion gate has been waived.

The declaration-bound supplied equity-history parser is integrated through
[PR #16](https://github.com/Jed1122/Robinhoodtradingbot/pull/16), merge
`a6f4e5c8ae3b88ff95437a52fac376dfad15c720` on
`codex/robinhood-system-implementation`. Its integration tree
`282fbff3bef889ac0fd4a58dfcea91e35dc2aa99` matches reviewed parser head
`00a226d47ae735b303a2cabf7d62b8c96c341895`, the forward-owner branch's starting
parent. The merge is a publication base, not an ancestor of that branch.

The [versioned forward-paper owner](docs/etf-forward-paper-owner-2026-10-04.md)
is implemented on [PR #17](https://github.com/Jed1122/Robinhoodtradingbot/pull/17).
Its separate forward identities reuse the existing economic reducer without
widening historical validators. The private single-host owner jointly publishes
the full fictional tape and economic state, verifies every retained prefix on
restart, preserves trial reservations/losses and risk latches, and never advances
during recovery. The complete 8 MiB admission budget and journal entry bound
include reconstructed state and recognized retained publication-crash aliases.
Capacity is reserved before marker/claim publication, including the crash window.
Missing state, stale heads, unresolved claims and unexplained links still deny.
This branch is not represented as merged: integration requires current exact-head
checks and resolution of substantive review findings. Earlier review/test evidence
is revision-specific and cannot certify a changed candidate.

At this publication checkpoint, software primitive: **implemented, integration
pending**. Trusted strategy factory,
recurring worker, promotion composition and standalone deployed recovery:
**blocked/unverified**. Every owner result is paused, synthetic, source/cost
unqualified, execution-disabled and non-promotable. Its cycles do not count toward
eligible paper/shadow observations. Production backup inclusion, host rollback and
distributed ownership remain outside its contract.

The October 4 bounded retained-input assessment remains separate: archive receipt
integrity was reverified, but complete calendar-backed execution coverage was not
rerun because its required calendar reference was unresolved in the approved
retained scope. Customer costs remain `BLOCKED_INPUTS`; absent genuine fills,
final fees and causal order/quote clocks are not zero-valued observations. No new
private records or broker/provider calls are inspected by this checkpoint.

The current dependency chain is complete qualified Alpaca historical roles and
execution coverage plus genuine customer-cost evidence → accepted after-cost
economic study → trusted strategy-to-joint-owner/recurring composition → separate
standalone recovery verification and genuine eligible paper/shadow observations.
Root retains ownership of risk, execution, reconciliation, persistence and promotion
integration. Parallel work remains limited to exact-base, credential-free public
contract/fixture/documentation audits; no customer evidence may be delegated.
Economic acceptance, qualifying runtime/paper/shadow operation and live trading
remain independently **NO-GO**. Merge authority is not activation authority.

## Alpaca observation/calibration checkpoint — 2026-10-02

The focused ETF path uses Alpaca as its sole market-data source and retains
Robinhood as execution broker. A bounded standalone local quote/status/LULD
observation workflow and private offline customer-cost measurement workflow are
implemented; [the current contract](docs/alpaca-execution-observations.md) records
their scope. Canonical cost behavior, risk configuration, paused service, broker
capabilities and promotion gates are unchanged. Local synthetic verification is
recorded in the PR; no actual private data or credentials enter Cloud/Git.

The reconnected Mac captured SPY/SIP under reviewed 60-second and 10-second scopes at
`e104f4f1be204db71e9e830303c12d3a0fd13878`: 5,959 quotes, including 5,910
uncrossed and 49 locked, with no status/LULD events observed. Both private receipt
audits passed; the second segment reverified its direct predecessor result and plan.
The original result-v1 captures declared duration stops without recording the
collection window; current audits explicitly mark elapsed duration unverified.
Initial control state remains unknown and the restart remains a discontinuity.
The [current result](docs/alpaca-execution-observations.md) records descriptive
spread aggregates and retained artifact hashes without private payloads.

The critical path remains complete source/control evidence and dated customer
execution/cost evidence, then genuine after-cost validation and qualifying
paper/shadow operation. Historical development quotes still cover 0/1,262
required sessions; forward data does not repair historical controls. The bounded
saved-record search found no usable execution/billing inputs. After separately
authorized browser sign-in, bounded Robinhood history checks returned zero
orders and no next page for the existing intended account, both for 2026 and
without a date filter. The offline customer-cost assessment completed with
`BLOCKED_INPUTS`, without inventing fills, zero fee rates or local timings.
Customer calibration,
economic acceptance, runtime qualification and live operation remain **NO-GO**.

## Current checkpoint — 2026-09-30 UTC

This checkpoint supersedes conflicting current-status and authority statements in the
historical snapshots below. The options-only [master specification](docs/options-only-build-spec.md)
governs the migration. The eight-task [native-data milestone](docs/options-native-data.md)
is implemented and fixture-tested within its bounded offline contract; actual-source
qualification, complete option/underlying quote coverage, and genuine economic validation
remain incomplete. The [real-data research design](docs/superpowers/specs/2026-09-28-real-data-options-research-design.md)
and [implementation plan](docs/superpowers/plans/2026-09-28-real-data-options-research.md)
are approved. Closed source dispatch, bounded native quote archives, the causal
quote stream and frozen study/history contracts are implemented and fixture-tested.
The source-reverified single-episode runner now composes fixed shortlist/momentum
decisions, canonical entry-budget checks, modeled order/expiry/settlement behavior,
independent cash accounting and exact-prefix offline recovery. Manufactured native
fixtures remain engineering-only. Exact-time journal-bound loss history and offline
restart are now implemented as a partial account-risk foundation; the continuous
source-bound account coordinator and liquidation-mark owner remain pending, along
with effective-date costs, dependent-outcome uncertainty and research CLI/report
composition. See the [account-risk checkpoint](docs/options-account-risk-checkpoint.md)
for current scoped evidence and the separate
[validation and readiness checkpoint](docs/options-real-data-validation.md) for
actual test evidence, dependency remediation and broker/runtime limitations.
Actual-source rules remain unverified (Task 2); a complete qualified credit-bounded
data package remains blocked on those inputs (Task 6). No genuine economic outcome,
new data purchase, broker write, deployment or live activation is claimed.
The initial foundation was merged in [PR #3](https://github.com/Jed1122/Robinhoodtradingbot/pull/3).
See [PR #4](https://github.com/Jed1122/Robinhoodtradingbot/pull/4) for the subsequent
halt/cursor/reconstruction corrections and their exact-head CI/review verdicts.
Those corrections must not be treated as integrated until reviewed checks pass
and the follow-up is merged.

[Standing operator authority](docs/operator-authority.md) permits reviewed, in-scope
merges and necessary Databento purchases within remaining authorized credits without
repeat approvals. Required checks, complete scope/cost verification and all separate
live, deployment, risk, cash and subscription boundaries remain unchanged.

The critical path is actual-source verification, preregistered complete coverage,
credit-bounded quote acquisition, causal historical execution/accounting, and after-cost
uncertainty evaluation. Credential-free work can proceed independently of broker access.
Production lifecycle composition and verified broker/runtime capabilities are separate
incomplete workstreams. Scoped 2026-09-30 read-only broker calls succeeded: the
Agentic account reported active Level 2 options permission, and option orders,
option positions and equity positions were empty. No nonempty lifecycle or order-write
behavior was verified. Current read-only DigitalOcean inspection found the existing
health-only service healthy, shadow/paused and not ready (`paused` and
`external_capability_missing`); no deployment changes occurred. Image/configuration
identities and remaining standalone-authentication and operational gaps are recorded
in the account-risk checkpoint. These limited diagnostics do not establish complete
account eligibility, runtime capability, or promotion readiness.
Live trading remains **NO-GO**. Neither funding, data integrity nor synthetic results
supplies missing economic, capability or operator-activation evidence.

## Historical snapshots

Snapshot date: 2026-09-17 (UTC)

Repository: `Jed1122/Robinhoodtradingbot`

Integration branch: `codex/continue-implementation-from-commit-7c4dcd1`

Attestation and Cloud-review base: `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`

Verified deployed source: `32ab71fc3c845c56068179fed98cf4a9eb80461e`

Latest CI-verified implementation: `001abc6e1cd85265e84c2a5c9c87cfedcf0482ba`

Current work: the operator selected **free-only data** and approved **Alpaca Basic as the first
data-validation candidate**, without moving the funded Robinhood account or changing trading
safeguards. The [Alpaca free-data validation specification](docs/superpowers/specs/2026-09-17-alpaca-free-data-validation-design.md)
was approved by the operator, who also confirmed creating a **paper-only Basic/free account**
with no paid subscription or funded live account. These are operator-reported facts, not an
authenticated account inspection. The operator selected inline execution of the
[first-response diagnostic plan](docs/superpowers/plans/2026-09-17-alpaca-first-response-diagnostic.md).
Its local manifest, private I/O, bounded transport and standalone command are now implemented
and tested with synthetic inputs; [operator instructions](docs/alpaca-data-diagnostic.md) describe
the default offline preparation and separate capture gate. This is not an authenticated data
capability, complete-history acquisition, provider adapter or accepted source. Contractual and
technical entitlement, retention rights, corporate-action coverage, and historical availability
remain unverified. Do not repeat the completed account-setup question.
No real credential access, authenticated Alpaca request, data acquisition, purchase, production-
ledger access, deployment or live operation occurred. No parallel/Cloud worker was dispatched
for the operator-selected inline implementation. External acquisition authority remains
separate; live trading is still NO-GO.

The operator then authorized publishing the five Alpaca checkpoint commits to existing
[PR #1](https://github.com/Jed1122/Robinhoodtradingbot/pull/1), preserving its base branch and
original description. Exact implementation revision `001abc6e1cd85265e84c2a5c9c87cfedcf0482ba`
passed [PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35272155521) and
[push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35272147974): all six jobs
on each run, including Python 3.12, 3.13, and 3.14. This documentation checkpoint records
those observed results; it does not change source, tests, configuration, or release authority.
The PR remains open and unmerged, with auto-merge disabled. No deployment or authenticated
capture was authorized or performed by publication.

Completed foundation: operator-approved data-first architecture, captured in the
[verifiable local data and snapshot-loader design](docs/superpowers/specs/2026-09-17-research-data-bundle-design.md).
Written-spec approval is complete. The
[six-task implementation plan](docs/superpowers/plans/2026-09-17-research-data-bundle.md)
defines the v1 format, callable interfaces, tests, and two disjoint Cloud contracts. The operator
approved primary-led execution with actual parallel Cloud test workers. Tasks 1-4 are committed
at `5178406`: immutable codec/models, synthetic normalization, replay/coverage verification,
and the existing-interface snapshot loader. Private artifact storage, no-intent integration,
both Cloud contributions, documentation, and final central verification complete the six-task
wave at `14c29e2`. No deployment or broker operation is part of this work.

The exact Task-4 base passed [PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35262696162)
and [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35262690055).
Two actual Cloud workers were dispatched against that exact pushed base:

- `DATA-BUNDLE-TESTS-004`: `task_e_6aac39f084b0832db860bdbc63e48dbd`; returned a scoped
  `READY_FOR_INTEGRATION` proposal with 21 synthetic tests. The primary reviewed the complete
  two-file diff, applied it centrally, and reran all 21 successfully.
- `SNAPSHOT-DATA-TESTS-004`: `task_e_6aac39f187ac832dbcb4f8b1bc8a4bd8`; returned a scoped
  `READY_FOR_INTEGRATION` proposal with 21 synthetic tests. The primary reviewed its full
  two-file diff and reran all 21 successfully. Both returned files pass together: **42 tests**.

Task 5 is committed at `313f54e`: private no-overwrite artifact I/O, including bounded reads,
pre-construction combined record limits, complete-write publication and retry durability.
Task 6 integrates the real loader and feature pipeline in the existing decision cycle with
incapable test stages, pins the unchanged legacy report/manifest/render hashes, and documents
the synthetic-only boundary. The latest focused pre-final selection passed 420 tests before
the 42 Cloud cases and final retry regression were added. Exact final baseline and CI results
are recorded below when observed, not inferred from worker dispositions.

The complete integration commit `14c29e26b760d6fb59a4514ae3f5b50f9e921d1d` passed
[PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35264185795) and
[push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35264174224): all six jobs
on each run, including Python 3.12, 3.13, and 3.14. This final documentation checkpoint only
records those observed outcomes and closes the plan; source and tests are unchanged.

Cloud workers own only their test/review files. All six production modules remain primary-owned.
Local read-only reviews are separate supporting checks, not relabeled Cloud execution.

Release state: **NO-GO for live trading**

This offline implementation work performs no new broker, ledger, credential, or host check. Operational
facts below remain the separately authorized 2026-09-15 snapshot, not a fresh deployment assertion.

This report transitions the existing system to centrally governed local and Codex Cloud orchestration. It does not restart or redesign the project. The executing-image-attestation release is committed, CI-verified, and deployed in paused mode. Two isolated Codex Cloud documentation reviews, one CI-hardening task, and two synthetic fixture tasks completed and were integrated centrally. Their point-in-time findings do not supersede the newer operational evidence recorded here. Operator-authorized workstation reauthorization and server credential rotation restored the bounded broker-read connection on 2026-09-15; live trading remains blocked.

## CURRENT SYSTEM

The repository contains a broker-neutral, fail-closed trading-system foundation with canonical configuration, pure risk and sizing, durable audit/promotion records, capability-separated broker protocols, deterministic offline tooling, a write-incapable connected-shadow probe, and a paused DigitalOcean deployment.

The public operator surface is not a live trading application. Live CLI paths remain locked, the default process exposes health/metrics only, and no provider-connected equity order adapter or complete live execution composition exists. Prediction-market live execution is explicitly unsupported. No live order has been placed by this system, and the project makes no profitability claim.

The funded Agentic brokerage account does not change the software gate state. A funded account is necessary operational context, not promotion evidence or authority to trade.

## CURRENT ARCHITECTURE

The implemented boundaries are:

- `domain/` and `config/`: canonical types, modes, instruments, and strictly validated configuration.
- `capabilities/` and `brokers/`: independently injectable read/review/place/cancel contracts and provider mappings.
- `strategies/`, `portfolio/`, and `risk/`: broker-neutral decision, allocation, sizing, loss, drawdown, and pretrade logic.
- `execution/`: broker-neutral order lifecycle, idempotency, and persisted non-live execution service.
- `reconciliation/`: comparison and drift classification without a complete provider/live composition.
- `persistence/`: Alembic-owned async SQLite schema, append-only evidence, unit-of-work boundaries, and journals.
- `research/` and `simulation/`: deterministic research/backtest foundations whose remaining bias and outcome requirements are documented.
- `authorization/` and `runtime/`: signed authorization/lease primitives, locked live factory, paused service, and bounded connected probes.
- `monitoring/` and `reporting/`: structured status, promotion preview, health, readiness denial, and live-disabled metrics.
- `infra/digitalocean/`: image deployment, rollback, backup/restore, Terraform, and cloud-init assets.

Provider transports remain outside strategy, risk, portfolio, and domain logic. Read, review, place, and cancel capabilities are separate. The only connected equity-shadow path is locally write-incapable even though its OAuth credential must be treated as trading-capable.

## COMPLETED WORK

The following are complete within the stated scope, not as proof of live readiness:

- Canonical domain and configuration graph with paused and live-disabled defaults.
- Non-reducible safety envelope and strict config validation.
- Pure Decimal-based sizing, exposure, loss, drawdown, activity, and ordered pretrade evaluation.
- Append-only persistence foundations, migrations, audit records, identity-bound observations, and submission journal.
- Broker-neutral order-state machine and durable non-live execution behavior with reconciliation requirements.
- Deterministic offline/replay foundations and local fixture-based tests.
- Seven authenticated equity read mappings and dual local/transport allowlists for the connected-shadow probe.
- Signed authorization, bounded lease, promotion-policy, and code/config identity primitives.
- Paused, health-only container profile with no credentials or host volumes by default.
- Transactional image-digest deployment and last-known-good rollback foundation on DigitalOcean.
- Root-owned, canonical, per-release executing-image attestation deployed and verified from an unprivileged container, including rejection when the artifact is absent.
- Portable paused-service denial test covering both plain and ANSI-colored diagnostics, while asserting that the server never starts without `--paused`.
- Two completed, centrally reviewed Codex Cloud audits with separate owned documentation paths and no production-code changes.
- Centrally integrated, CI-verified Cloud workflow hardening with independent security, locked-dependency, and configuration checks.
- Primary-owned corporate-action filtering correction: instrument isolation, effective-as-of UTC
  dates, and canonical UTC query validation. Regression tests first reproduced 11 failures; the
  corrected adjustment suite now has 23 passing cases, including independent late-announcement tests.
- Centrally reviewed Cloud membership tests and primary-owned strict input validation: UTC
  membership/lookup times, exact booleans and immutable tuple records, nonblank IDs, and rejection
  of contradictory same-key events. Identical duplicates and distinct-time changes remain valid;
  source provenance and interval coverage remain open.
- Centrally reviewed Cloud fill-contract tests with exact BUY/SELL accounting, forced branches,
  mixed seeded outcomes, distinct-seed control, and restored global RNG state. Full simulation
  lifecycle, calibration, and outcome evidence remain incomplete. Primary-owned fill/cost input
  validation now rejects malformed numeric/typed inputs and invalid arithmetic results without
  changing valid seeded outcomes or cost formulas.
- Operator-authorized credential rotation with account-match and private-permission verification, a retained root-private previous store, and one successful write-incapable server probe.
- Read-only health, metrics, status, live-readiness, and promotion-preview surfaces.
- CI definition for Python 3.12, 3.13, and 3.14 with Ruff, strict mypy, branch coverage, Bandit, and lock validation.

## PARTIAL WORK

- **Equity provider support:** seven reads exist; nonempty position/order mapping and provider review/place/cancel adapters do not.
- **Crypto provider support:** DTO, signing, read, and write plumbing is fixture/mock verified but not authenticated externally.
- **Research:** deterministic comparison, walk-forward, cost, benchmark, and Monte Carlo components exist; point-in-time membership, corporate-action/interpolation provenance, PBO/multiple-testing controls, realistic fill/exit outcomes, and accepted evidence remain incomplete.
- **Public backtest/simulation CLI:** current commands expose deterministic identity output rather than a complete operator composition of the deeper engines.
- **Paper runtime:** fail-closed boundaries and evidence types exist, but there is no complete, validated decision/execution/outcome cycle that can generate eligible promotion evidence.
- **Connected shadow:** a bounded, write-incapable probe exists, but current records lack validated data and complete outcomes and are therefore ineligible.
- **Execution and reconciliation:** strong broker-neutral foundations exist; provider-connected live composition, restart-safe recovery, and nonempty external shapes do not.
- **Live runtime:** preflight primitives and a locked factory exist; cycle composition and mode transition remain intentionally unavailable.
- **Scheduler and operations:** skeletons and runbooks exist; production leadership, reconciliation scheduling, and alert-operability evidence are incomplete.
- **Infrastructure as code:** Terraform and cloud-init assets exist but have not been validated end to end against the current manually created 2 GB Droplet.
- **Backup/restore:** scripts and tests exist; external storage, key custody, and an operator-observed restore drill remain prerequisites.
- **Dashboard/UI:** no separate dashboard exists; only health, readiness, metrics, and CLI status surfaces are implemented.

## CURRENT BLOCKERS

1. The broker connection is restored, but connected-shadow evidence remains non-promotable. The single post-rotation probe verified authenticated reads, broker health, executing-image identity, and zero-state reconciliation, while reporting `strategy_ineligible`, `live_data_invalid`, and `outcomes_incomplete`. No diagnostic market-history probe was requested. Repeating this probe would not resolve the missing research/data/outcome evidence.
2. Verification is complete for the paused release, not for live operation. Host hardening, infrastructure-as-code conformance, off-host backup, and a full operator-observed recovery drill still require their own evidence.
3. Research/data requirements and accepted research identity are incomplete.
4. The 2026-09-15 read-only promotion preview reported an intact ledger with five ineligible shadow observations across four separate identity series, two rejected research assessments, zero eligible observations, and zero live authorizations, live leases, execution leases, or submission attempts. Inventory totals do not combine identities for promotion.
5. Paper requires 100 eligible observations; shadow requires eligible observations on seven distinct UTC dates. These elapsed evidence gates cannot be compressed or fabricated.
6. Nonempty equity response mappings and authenticated review/place/cancel provider evidence are absent.
7. No provider-connected live adapter, complete live application, durable host leadership path, or restart-safe live recovery composition exists.
8. Current external security, manual review, and runtime-control attestations have not been assembled for live promotion.
9. Codex Cloud CLI access works. `RESEARCH-GAPS-001`, `IAC-AUDIT-001`, `CI-HARDENING-002`,
   `PIT-FIXTURES-002`, `SIM-FILL-FIXTURES-002`, `PIT-VALIDATION-003`, `SIM-VALIDATION-003`,
   `DATA-BUNDLE-TESTS-004`, and `SNAPSHOT-DATA-TESTS-004` returned bounded diffs and were integrated
   centrally. Remaining review findings and complete research/runtime implementation are not implied.
10. The remote default branch is materially behind the integration branch; any future Cloud task launched from the default branch would start from stale architecture.

## CURRENT GO / NO-GO STATE

| Activity | State | Reason |
|---|---|---|
| Local implementation and deterministic tests | GO | No external side effects; existing guardrails remain active. |
| Static/read-only audits and secrets-free Cloud tasks | GO | Nine Cloud tasks integrated; continue to require exact revision, isolated worktree, frozen interfaces, and bounded ownership. |
| Paused health-only service | Last verified GO on 2026-09-15 | Healthy, readiness-denied, live-disabled, and no credential/ledger mounts at that check; not rechecked by this wave. |
| Explicit bounded read-only evidence probe | Verified once; separate authority required for another run | The post-rotation probe succeeded but remained non-promotable. The local client is write-incapable, but the OAuth token remains trading-capable. No recurring job is authorized or installed. |
| Paper promotion | NO-GO | No accepted research composition or eligible 100-cycle evidence set. |
| Shadow promotion | NO-GO | No qualifying paper promotion and no eligible seven-UTC-date shadow set. |
| Micro-live | NO-GO | Provider writes/live composition and promotion/manual/runtime evidence are absent. |
| Normal-live | NO-GO | Micro-live and the larger observation/time gates are absent. |
| Prediction-market live execution | NO-GO / unsupported | No live placement capability exists. |

Funding the account does not override any NO-GO state.

## CRITICAL PATH

1. **Completed:** restore a green integration base by fixing the portable CLI test without changing production behavior.
2. **Completed for paused operation and one bounded broker-read probe:** review, test, commit, build natively for amd64, and deploy the root-attested executing-image identity change. Restore OAuth through separately authorized workstation bootstrap and server credential rotation. The successful probe added only ineligible diagnostic evidence; no preflight or promotion check was weakened.
3. Resolve point-in-time data, corporate-action/interpolation provenance, realistic fill/reject/partial-fill/latency assumptions, PBO/multiple-testing controls, and stage-independent research identity.
4. Compose a complete durable paper decision/execution/outcome cycle and collect 100 eligible observations.
5. Compose a qualifying bounded shadow cycle with validated data, complete outcomes, reconciliation, and known order state; collect evidence over seven distinct UTC dates.
6. Under one authoritative owner, add captured authenticated provider schemas, nonempty mappings, review/place/cancel evidence, adapters, host leadership, reconciliation, and cancel-only recovery.
7. Assemble current security, manual-review, and runtime-control attestations.
8. Conduct a separately authorized, tightly capped micro-live review. Normal-live remains a later promotion decision with its own observation and elapsed-time gates.

Steps 4 and 5 contain irreducible observation/time requirements. Parallelism can improve preparation and review; it cannot make missing evidence valid.

## PARALLELIZATION MAP

The primary orchestrator owns the integration branch, dependency graph, protected components, central verification, deployment, and release decision. Independent agents use exact commits and isolated worktrees.

| Workstream | Dependency | Parallel status | Owner boundary |
|---|---|---|---|
| CI portability test | Committed base | Completed centrally at `32ab71f` | Test file only; production CLI unchanged. |
| Attestation adversarial review | Current attestation commit/diff | Independent review now | Read-only or tests/docs only; deploy helper/runtime implementation protected. |
| Research-bias gap analysis | `a58f6eb` | Cloud review completed | Review/design only; strategy selection and promotion decision protected. |
| Point-in-time membership contract | `93b28f4` | Cloud fixture tests integrated and locally verified | Tests/docs only; source coverage and provenance remain unverified. |
| Corporate-action primitive filters | `93b28f4` | Primary correction locally verified | Existing interface retained; no provider/evidence integration. |
| Simulation fill-model contract | `93b28f4` | Cloud tests integrated and locally verified | Tests/docs only; no pricing, strategy, risk, or execution changes. |
| Membership and fill/cost input validation | `095e5c0` | Complete at `8785266`; two Cloud test diffs integrated; local verification and exact-commit CI passed | Independent synthetic tests only; primary owns all production validation. |
| Verifiable local data and snapshot loader | Approved plan; Task-4 Cloud base `5178406`; complete wave `14c29e2` | Complete; both Cloud test diffs centrally reviewed; 4,073 local tests and exact-commit PR/push CI pass | Primary owns all six modules; Cloud owns bounded synthetic tests/reviews only. |
| IaC drift and recovery audit | `a58f6eb` plus sanitized inventory | Cloud review completed | Read-only; no DigitalOcean or state mutation. |
| Coverage/observability gap inventory | Committed base | Independent now | Read-only report or isolated non-risk tests. |
| Paper composition | Accepted research/data interfaces | Sequential protected work | Primary owner only. |
| Broker writes and reconciliation | Captured authenticated evidence | Sequential protected work | Primary owner only. |
| Live runtime and promotion | All preceding gates | Sequential protected work | Primary owner plus explicit operator approval. |

### Completed centrally: CI-PORTABILITY-001

Completed at `32ab71fc3c845c56068179fed98cf4a9eb80461e`; GitHub Python 3.12-3.14 checks are green. Do not redispatch this completed task.

- **Objective:** make the paused-service missing-flag test portable across Python 3.12-3.14/Typer behavior without changing production code.
- **Owner:** one Cloud task.
- **Base revision:** `a63247eca2022a80adb8b76e47ac8c9d964ed827`.
- **Owned paths:** `tests/integration/cli/test_paused_service.py` only.
- **Read-only dependencies:** `src/trading_bot/cli/main.py`, `pyproject.toml`, `uv.lock`, CI workflow.
- **Frozen interfaces:** CLI flags, exit behavior, paused-service callback, dependency versions.
- **Prohibited changes:** production files, lockfile, risk/config/runtime semantics, external calls.
- **Acceptance criteria:** absent `--paused` exits nonzero, diagnostic names `--paused`, and a monkeypatched `uvicorn.run` proves the server was never started.
- **Verification:** targeted test under Python 3.12/3.13/3.14, then full CI commands.
- **Return contract:** commit SHA, exact diff, test outputs, assumptions, and blockers.

### Completed Cloud task contract: RESEARCH-GAPS-001

Task: [Document research-evidence gap review](https://chatgpt.com/codex/tasks/task_e_6aa8222d7154832da2b71b027131115b). Reviewed output: [research-gaps-001.md](docs/reviews/research-gaps-001.md). Exact dispatch base: `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`. Only the assigned document changed.

- **Objective:** produce a traceable blocker matrix and acceptance tests for point-in-time membership, corporate actions, interpolation provenance, PBO/multiple testing, and execution outcomes.
- **Owner:** one Cloud task.
- **Base revision:** current committed integration revision at dispatch time.
- **Owned paths:** a new document under `docs/reviews/` only.
- **Read-only dependencies:** `research/`, `simulation/`, configs, tests, and strategy-research documentation.
- **Frozen interfaces:** canonical config schema, research identity, promotion flags, strategy/risk behavior.
- **Prohibited changes:** code, thresholds, acceptance decisions, external data calls, credentials, claims.
- **Acceptance criteria:** every gap maps to evidence, an owner, a deterministic test, and an explicit pass/fail criterion.
- **Verification:** link/path validation and orchestrator review against current code/tests.
- **Return contract:** commit SHA, matrix summary, unresolved ambiguities, and proposed follow-on contracts.

### Completed Cloud task contract: IAC-AUDIT-001

Task: [Perform documentation-only infrastructure drift audit](https://chatgpt.com/codex/tasks/task_e_6aa822a2bfac832da021612e65a8e28f). Reviewed output: [iac-audit-001.md](docs/reviews/iac-audit-001.md). Exact dispatch base: `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`. Only the assigned document changed. Its pre-deployment platform and release-drift findings are resolved by the native amd64 deployment below; its unverified host/IaC/recovery findings remain open.

- **Objective:** compare Terraform/cloud-init/runbook assumptions with a sanitized description of the paused 2 GB host and report drift; make no infrastructure changes.
- **Owner:** one Cloud task.
- **Base revision:** current committed integration revision at dispatch time.
- **Owned paths:** a new document under `docs/reviews/` only.
- **Read-only dependencies:** `infra/digitalocean/`, Docker/Compose files, operations/disaster-recovery/incident docs.
- **Frozen interfaces:** live-disabled defaults, firewall policy, deployment paths, rollback model.
- **Prohibited changes:** cloud/API calls, secrets, state files, deployment, Terraform apply, production code.
- **Acceptance criteria:** prioritized drift list, safe remediation dependencies, rollback effects, and exact verification commands.
- **Verification:** static checks only; primary orchestrator validates against sanitized current host facts.
- **Return contract:** commit SHA, findings by severity, assumptions, and blocked live checks.

### Ready Cloud task contract: ATTESTATION-REVIEW-001

- **Objective:** adversarially review the committed attestation change for symlink, ownership, mode, canonicalization, digest-binding, rollback, race, and cleanup failures.
- **Owner:** one Cloud task after the patch has an exact commit.
- **Base revision:** select an exact reviewed integration SHA at dispatch; the attestation implementation is already committed in `a58f6eb`. Do not use a dirty worktree.
- **Owned paths:** new or existing attestation/deployment tests and review documentation only, as assigned explicitly.
- **Read-only dependencies:** `src/trading_bot/code_identity.py`, runtime integrations, Dockerfile, Compose, and deployment helper.
- **Frozen interfaces:** artifact schema, root ownership, immutable digest binding, paused deploy order, fail-closed behavior.
- **Prohibited changes:** deployment/runtime implementation, external host access, credentials, live settings.
- **Acceptance criteria:** adversarial cases have deterministic tests or documented blockers; no guardrail is weakened.
- **Verification:** focused identity/deployment/runtime tests, Ruff, mypy, then the full suite.
- **Return contract:** commit SHA, findings, tests added, commands/results, and residual risks.

### Completed and centrally verified Cloud task contract: CI-HARDENING-002

Task: [Improve CI workflow for Robinhood trading system](https://chatgpt.com/codex/tasks/task_e_6aa8760eafd8832dbc1ab7b5cbcb7b1e). Dispatched from exact green base `32ab71fc3c845c56068179fed98cf4a9eb80461e`. The returned diff changes only `.github/workflows/ci.yml` and was reviewed centrally. Bandit, locked-dependency validation/audit, and shell/Compose validation run independently of the unchanged Python 3.12-3.14 quality matrix. The primary review tightened shell validation to each script's POSIX `sh` contract. Integration `93b28f484f1968f415d2d765a2d50143831ad3e4` passed [pull-request CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34905338948) and [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34905334040). These workflow/documentation changes did not change or redeploy the running application image.

- **Objective:** keep security and lock checks observable when a test matrix leg fails, and add bounded secrets-free shell/Compose validation.
- **Owner:** one Cloud task after `CI-PORTABILITY-001` is integrated.
- **Base revision:** the exact green integration commit at dispatch time.
- **Owned paths:** `.github/workflows/ci.yml` only.
- **Read-only dependencies:** Makefile, Docker/Compose files, deployment scripts, `pyproject.toml`, and `uv.lock`.
- **Frozen interfaces:** application code, dependency versions, test semantics, coverage threshold, and deployment behavior.
- **Prohibited changes:** authenticated tests, secrets, broker calls, deploy jobs, coverage reductions, or ignored failures.
- **Acceptance criteria:** Bandit, lock consistency, and locked dependency audit remain visible after Pytest failure; shell and Compose checks run without external credentials.
- **Verification:** workflow syntax review plus exact local command equivalents.
- **Return contract:** commit SHA, workflow diff, local results, permissions analysis, and `READY_FOR_INTEGRATION` or `NOT_READY`.

### Research primitive wave: PIT-FIXTURES-002 and SIM-FILL-FIXTURES-002

The [bounded implementation plan](docs/superpowers/plans/2026-09-15-research-data-correctness.md)
records exact contracts for two real Codex Cloud tasks dispatched in parallel from
`93b28f484f1968f415d2d765a2d50143831ad3e4`:

- [PIT-FIXTURES-002](https://chatgpt.com/codex/tasks/task_e_6aa949d2b85c832d9b4ce34a4d41524e):
  returned only `tests/unit/market_data/test_universe_contract.py` and
  `docs/reviews/pit-fixtures-002.md`. The primary inspected the complete diff, added imports to
  make its documented conflict reproduction self-contained, and reran 18 existing/new tests and
  Ruff successfully. Its 16 new tests do not establish real historical completeness.
- [SIM-FILL-FIXTURES-002](https://chatgpt.com/codex/tasks/task_e_6aa949d36158832d8048af09453cb70d):
  returned only `tests/unit/simulation/test_fill_contract.py` and
  `docs/reviews/sim-fill-fixtures-002.md`. Central review replaced the vacuous forced-outcome RNG
  check with an independently specified mixed-outcome sequence and distinct-seed control, restored
  global RNG state in `finally`, and added a liquidity-cap/forced-partial interaction case. The
  integrated file adds 11 tests. An isolated in-memory mutation that ignored the supplied RNG failed
  the strengthened test, while the real implementation passed and preserved global RNG state.

The CLI exposed ready diffs, not complete worker command transcripts or Cloud-local commit SHAs.
The assigned exact base is recorded in both returned reviews; central integration relies on full
diff inspection and fresh local verification, not an unobserved worker verification claim.

The primary independently corrected `adjust_bars` after reproducing cross-instrument contamination,
premature future-action application, and missing UTC query validation. A separate local read-only
test review found that effectivity could mask the older announcement test; two late-announcement
cases now exercise that filter independently. No strategy, sizing, risk, config, persistence,
provider, promotion, or deployment code changed. Corporate-action sequence chronology and full
source provenance remain unresolved. These are primitive correctness changes, not accepted
research, a complete paper composition, elapsed observations, or a live release.

### Bounded input-validation wave (2026-09-16)

The affected membership and simulation primitives are **partial**, not connected research or
promotion evidence. The approved dependency chain is: independent failing regression tests →
primary-owned validation → central Cloud diff review → focused and full verification → existing
branch/PR CI. Production validation and central verification are the critical path. No new
provider, research acceptance, strategy threshold, evidence gate, deployment, or live operation
is included. The prior `095e5c0` wave passed both
[PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019194133) and
[push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019186906).

Two independent actual Codex Cloud tasks were dispatched from exact committed base
`095e5c02b01aea95fd7858a549a7765e7b0488c0` on the integration branch. Each must verify or detach
that exact revision in its isolated checkout, otherwise return `NOT_READY`.

- **PIT-VALIDATION-003**, owner: [Cloud task](https://chatgpt.com/codex/tasks/task_e_6aaae8e47a28832da3c46160f25c5a9b).
  Objective: independent synthetic membership validation tests. Owned paths only:
  `tests/unit/market_data/test_universe_validation_contract.py` and
  `docs/reviews/pit-validation-003.md`. Read-only dependencies: universe source, shared validators,
  existing membership tests, and project/research documentation. Frozen interfaces: membership
  fields, universe constructor, lookup, and eligibility reason. Acceptance: reject invalid UTC,
  blank/non-string IDs, nonboolean flags, invalid tuple/record shapes, and contradictory values
  at the same instrument/effective/announcement key; retain identical duplicates, late
  announcements, sorted outputs, and existing valid boundaries. No claim of historical completeness.
  Verification: `uv run pytest tests/unit/market_data/test_universe_validation_contract.py -q`,
  Ruff on that file, then the existing `test_universe.py` and `test_universe_contract.py` tests.
- **SIM-VALIDATION-003**, owner: [Cloud task](https://chatgpt.com/codex/tasks/task_e_6aaae8e50fa8832d833020b834350eaa).
  Objective: independent synthetic fill/cost input tests. Owned paths only:
  `tests/unit/simulation/test_input_validation_contract.py` and
  `docs/reviews/sim-validation-003.md`. Read-only dependencies: fill/cost/event sources, shared
  validators, existing simulation tests, and project/research documentation. Frozen interfaces:
  existing constructors, fill evaluation, cost helpers, arithmetic, and seeded valid outcomes.
  Acceptance: exact bounded finite Decimals, positive order quantities/prices, nonnegative
  liquidity/costs, uncrossed quotes, independent probabilities in `[0,1]`, exact cursor/cost/side/
  boolean types, and positive execution results. Zero liquidity/costs, equal quotes, and probability
  endpoints remain valid. No new fee/slippage cap, timing model, or config schema.
  Verification: `uv run pytest tests/unit/simulation/test_input_validation_contract.py -q`,
  Ruff on that file, then existing `test_fills.py` and `test_fill_contract.py` tests.

Both contracts prohibit production/config edits, external broker/data/deployment operations,
secrets, live/risk/evidence changes, skipped/xfail tests, mocks, and source-text assertions.
Their review documents must return exact base, commands/results, expected-red explanations,
assumptions, risks/blockers, and an explicit integration disposition alongside the bounded diff.
Expected-red tests against the permissive base are TDD evidence, not release approval. The primary
owns `universe.py`, `costs.py`, `fills.py`, separate core regression tests, documentation, and all
integration/release decisions. Both tasks returned only their owned two-file diffs. The primary
inspected all four files, reproduced 140 expected failures and 8 valid passes on the exact old
base, and verified all 148 originally returned Cloud cases against the patch. Redundant unrelated-RNG assertions
were removed and separate primary controls now verify each membership timestamp independently.
The original primary regression run reproduced 30 failures before implementation. Further review
strengthened the Cloud-owned files to 176 cases; 38 separate primary cases bring the added total
to 214. The final new-test set produced 202 expected failures and 12 valid-boundary passes on the
old base. The full patched suite passed locally on 2026-09-17, as recorded below.

## LOCAL-ONLY TASKS

- OAuth bootstrap, refresh-token handling, and any authenticated broker evidence capture.
- Production account inspection, even when the local client is write-incapable.
- Production ledger backup, restore, migration, inspection, or evidence attestation.
- DigitalOcean provisioning, firewall, image pull, deployment, rollback, and host verification.
- Root-owned executing-image artifact installation and verification.
- Broker review/place/cancel experiments or schema capture.
- Live authorization, lease, leadership, kill-control, reconciliation, recovery, or mode transition.
- Final integration of protected components and every release/promotion decision.

These tasks stay local because they involve credentials, production state, external side effects, or safety-critical authority.

## CLOUD-CANDIDATE TASKS

- Cross-platform CI/test portability with production behavior frozen.
- Static architecture, dependency, threat-model, and documentation review.
- Fixture-only public response parsing and schema-shape tests.
- Research-bias and data-provenance acceptance design.
- Simulation/fill-model test design using synthetic data only.
- Coverage, mutation-test, and observability gap inventories.
- Read-only IaC/recovery drift review from sanitized inputs.
- README/runbook synchronization after primary-owner behavior is frozen.

All Cloud tasks require an exact committed base, isolated worktree, path ownership, no secrets, no broker/network operations, and central diff review.

## HIGH-CONFLICT COMPONENTS

The following must not have concurrent implementation owners:

- `src/trading_bot/runtime/live.py` and mode-transition surfaces.
- `src/trading_bot/risk/`, sizing, strategy selection, and exposure logic.
- `src/trading_bot/execution/` and submission idempotency.
- `src/trading_bot/reconciliation/` and restart/cancel-only recovery.
- Provider write/review/cancel adapters and capability bindings.
- Authorization, leases, leadership locks, kill controls, and promotion decisions.
- Persistence migrations, production ledger, and evidence schemas.
- `configs/safety-envelope.yaml`, live configs, and canonical config schema.
- Credential handling and authenticated transport code.
- Docker/Compose and `infra/digitalocean/deploy-remote.sh` while release attestation is changing.

Shared interface changes in these areas require a sequential plan, explicit migration, focused tests, architecture documentation, and primary-owner integration.

## TEST STATUS

### Alpaca publication verification (2026-09-17)

- Fresh pre-push verification at `001abc6` passed **4,223 tests**, **86.64% coverage with
  branch measurement**, in 144.06 seconds on Python 3.12.13. The 80% floor is unchanged.
- Ruff, strict mypy across **174 source files**, Bandit, `uv lock --check`, dependency
  audit, **3 documentation smoke tests**, and `git diff --check` passed. The local project
  package remains unauditable on PyPI; existing annotation/deprecation warnings were retained.
- All six jobs in both exact-revision CI runs linked above passed: three Python quality
  jobs, Bandit, locked-dependency validation/audit, and shell/Compose configuration checks.
  Existing GitHub action-runtime deprecation annotations are non-failing and unchanged.
- The integration branch was pushed without force, and the existing PR description was
  preserved beneath a current checkpoint clarifying implemented versus externally unverified
  behavior. The named worktree and unrelated untracked files were preserved.
- This supersedes the implementation-time no-push status below, not its safety boundary.
  Authenticated source evidence, data acceptance, promotion, merge, and deployment remain
  outside this publication. The next external prerequisite remains the separate acquisition gate.

### Alpaca inline diagnostic implementation (2026-09-17)

- Inline execution followed operator approval, starting at `9c71e63f0b549f063825633f1a0517ab922af759`.
  Task 1 is committed as `2777c5d`; Task 2 as `0aae197`; Task 3 adds bounded mocked transport,
  standalone offline-default command, safe assessment, documentation and anti-replay marker.
- Fresh starting selection: **133 tests**. New diagnostic tests demonstrate the missing
  implementation first, then pass after the matching implementation. Edge cases reproduced
  and fixed numeric-exponent exception leakage, repeated use of an approved manifest, and
  an incorrect zero-sample count on potentially partial failure.
- Final focused diagnostic selection passed **150 tests**. New source modules measured
  96% and 97% coverage with branch measurement in the first full run. No real provider response
  or credential is used in those tests. CLI smoke tests write only synthetic temporary files.
- The final full run passed **4,223 tests**, **86.64% coverage with branch measurement**,
  in 139.15 seconds, above the unchanged 80% floor. This includes 150 new diagnostic tests
  on top of the prior 4,073-test implementation. The earlier 4,221-test run preceded the
  final two partial-report assertions and is not the final count.
- Ruff passed; strict mypy passed across **174 source files**; Bandit found no issues;
  `uv lock --check` passed; `pip-audit` found no known vulnerabilities among auditable
  dependencies and skipped the local project package because it is not on PyPI. Existing
  Bandit annotation warnings and the Starlette/httpx deprecation warning were not suppressed.
- Documentation smoke selection passed **3 tests**; changed-document links and exact staged
  scope were checked locally. The named worktree and unrelated untracked files are preserved.
  Existing PR #1 targets `codex/robinhood-system-implementation`; no push, merge, deployment or
  new PR was performed. Local completion does not substitute for new-commit CI.
- These are local results, not new-commit CI or authenticated source evidence. No risk,
  strategy, broker, production persistence, configuration, dependency, runtime or deployment
  behavior changed. No live order, paid subscription or real credential operation occurred.

### Alpaca account-confirmation and diagnostic-plan checkpoint (2026-09-17)

- Based on `62cc33b2520124ead55aa8effe8aa24ea24cdedc`. The operator approved the written
  specification and confirmed a created paper-only Basic/free account, no paid subscription
  and no funded Alpaca live account. No authenticated verification is inferred.
- Documentation only: updated specification status, bounded first-response implementation
  plan, and this handoff. The new plan is not implemented. Its external capture remains gated.
- A separate local read-only worker inventoried existing documentation checks; no edits,
  provider data, credentials, network or Cloud execution were delegated. The primary checked
  the plan against the approved specification and existing config/clock/storage interfaces.
- Fresh documentation smoke selection passed **3 tests**. These checks do not validate the
  new plan. An independent local-link check resolved **9 links across 3 changed documents**;
  the primary reviewed the exact diff and `git diff --check` passed. No full suite or new CI
  result is claimed for docs only.
- No source/config/dependency/runtime changes, credential operation, authenticated request,
  data capture, paid subscription, broker operation, ledger access, deployment or live activation.

### Alpaca free-data design checkpoint (2026-09-17)

- Documentation only: a proposed validation specification and this handoff update, based on
  `d53d596e5e11b21938adbc2ac6adaa95e6a4284c`. The operator selected Alpaca Basic as the first
  $0 candidate and confirmed that no Alpaca account exists.
- The primary reviewed current official public documentation and self-reviewed the specification
  for authority, cost, source/time ambiguity, compatibility, and unsupported acceptance claims.
  A parallel read-only inventory checked the existing documentation-test boundary; it made no edits
  and is not a Codex Cloud implementation result.
- Fresh `tests/smoke/test_documentation.py` execution passed **1 test**. This existing test does
  not inspect the new specification or handoff, so both changed Markdown documents also received
  a separate local-link check: **6 local links resolved**. `git diff --check` passed.
- No source, tests, configuration, dependencies, runtime, or deployment changed. The full test
  suite and new-commit CI were not run for this design-only checkpoint; earlier baseline and CI
  results below remain attached to their original implementation commits.
- No authenticated API request, account creation, credential operation, paid subscription,
  production-ledger access, data acquisition, source acceptance, or trading operation occurred.

For the synthetic research-bundle implementation wave on 2026-09-17:

- The final local full suite, including both reviewed Cloud contributions, passed **4,073 tests**
  in 130.26 seconds with **86.38% coverage with branch measurement enabled**, above the unchanged
  80% threshold. This adds 314 tests to the prior 3,759-test implementation. One existing
  Starlette `httpx` deprecation warning remains. The earlier 4,052-test run preceded integration
  of the second Cloud file and is not used as the final count.
- The final focused data/research/features/decision-cycle/paper/promotion/no-live-write selection
  passed **463 tests**. Both Cloud-owned files passed separately and together (**42 tests**).
  The real-loader decision-cycle test creates no decisions, intents, or execution outcomes;
  legacy report, manifest, and rendered-value hashes remain unchanged.
- Ruff passed; strict mypy passed across **171 source files**; Bandit found no issues; and
  `uv lock --check` passed. Existing Bandit annotation warnings were not suppressed.
  A fresh audit of exact locked requirements exported to an isolated temporary directory
  reported **no known vulnerabilities**. No credential or production payload was exported.
- DigitalOcean shell-script syntax and standalone `docker-compose config --quiet` passed.
  The local Docker Compose plugin is absent; exact-commit CI runs its native `docker compose`
  command. No container or deployment was started by configuration validation.
- Tests used the verified clean Python 3.12.13 environment with `PYTHONPATH=src` from this
  worktree. The final source/test suite was stable during the run; subsequent changes only
  record verification in documentation. Exact integration-commit PR and push CI at `14c29e2`
  passed all six jobs each; Task-4 CI at `5178406` also passed. Existing Node 20 action-runtime
  deprecation annotations are warnings, not failures; no workflow check was bypassed.
- Primary regression tests reproduced parser, preflight, and retry-durability findings before
  fixes. Process-local fault injections demonstrated that malformed-limit, duplicate-key,
  exact hash, source-scope, blob integrity, membership, and real-loader integration assertions
  detect disabled or incorrect behavior; none of those bypasses were retained in source.

Historical pre-implementation planning snapshot on 2026-09-17:

- Fresh offline artifact, report, research-validation, replay, feature, and decision-cycle
  verification passed **16 existing tests** in 0.67 seconds. Captured legacy synthetic
  report/manifest/rendered-value hashes are pinned in the plan as compatibility controls.
- A read-only parallel inventory verified reusable fixture/test paths; the primary performed
  the plan/spec coverage and signature review. At that earlier planning checkpoint no
  implementation task was complete and no bundle Cloud worker had been dispatched.
- Fresh documentation smoke verification passed **1 test**; all **17 Python examples** in
  the plan parsed successfully under the clean Python 3.12 environment. Example syntax
  validation is not execution of the planned code. Diff whitespace checks passed.
- This pass changes only the implementation plan, approved-spec status, and handoff report.
  The full-suite/CI evidence below still belongs to implementation commit `8785266`.

For the data-first architecture review on 2026-09-17:

- Before writing the spec, the existing promotion-wiring, paper, and no-live-write
  integration tests passed: **21 tests**, using the clean locked environment with
  `PYTHONPATH=src`. These are boundary checks, not eligible paper observations.
- The new spec and this handoff update are documentation only. Full implementation-suite
  and CI results below belong to `8785266`, not to a later documentation commit.
- The primary self-reviewed the spec for scope, compatibility, coverage/time ambiguity,
  and non-promotable boundaries. An independent read-only call-site inventory corroborated
  the legacy constructor/hash constraints. Fresh documentation smoke verification passed
  **1 test**; no new source implementation or external verification is claimed.

For the input-validation wave, verified on 2026-09-17:

- A fresh secrets-free archive of staged tree `fe4d74c0a66b9b1898e88b5ded328f25509fc0b9`
  passed **3,759 tests** in 137.37 seconds, with **85.64% coverage with branch measurement
  enabled**, above the unchanged 80% threshold. The existing Starlette `httpx` deprecation warning
  remains. The interrupted September 16 full run is not counted as passing.
- This wave adds 214 cases to the 3,545-test base. The expanded market-data, simulation, and
  paper/decision-cycle integration selection passed 288 tests. The final new tests independently
  produced 202 expected failures and 12 valid-boundary passes on exact base `095e5c0`.
- Fresh Ruff, strict mypy across 165 source files, Bandit, and `uv lock --check` passed on the
  archived snapshot. A fresh audit of the exact locked requirements found no known vulnerabilities.
  Existing Bandit annotation and audit invocation warnings were not suppressed.
- POSIX shell syntax checks and standalone `docker-compose config --quiet` passed. No container
  build, deployment, account access, credential operation, production-ledger access, or live check
  was performed.
- Verification used the existing clean locked Python 3.12.13 environment with `PYTHONPATH=src`
  against the archive. The final documentation-only edits record results, clarify historical
  observations, and reconcile the original and strengthened Cloud test counts; production and
  tests remain identical to the verified tree. The user's pre-existing coverage/error files are
  not included or altered.
- Committed and pushed as `8785266866206b1e93f1f031794703d3ab8f106e` on the existing branch and
  [pull request](https://github.com/Jed1122/Robinhoodtradingbot/pull/1).
  Exact-commit [PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35255574816)
  and [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35255569133) both
  passed all six jobs: Python 3.12/3.13/3.14, Bandit, locked dependencies, and configuration.
  Existing Node 20 action-runtime deprecation warnings were not failures.

For the research-primitive implementation wave on 2026-09-15:

- A secrets-free archive of staged tree `93a9b8a0e817aa9a56823f38c46f3cd623d23095` passed
  **3,545 tests**, with **85.57% coverage with branch measurement enabled**, above the unchanged
  80% threshold. One existing Starlette `httpx` deprecation warning remains. This wave adds 47 cases
  to the previous 3,498-test suite. The final report and plan only record these results afterward;
  production code and tests are unchanged from the verified snapshot.
- The focused market-data, simulation, and paper-runtime integration selection passed 73 tests.
- Ruff passed; strict mypy passed across 165 source files; Bandit reported no issues;
  `uv lock --check` passed; a fresh audit of the exact locked requirements found no known
  vulnerabilities. Existing Bandit annotation warnings were not suppressed.
- POSIX shell syntax checks and Compose configuration validation passed. This workstation uses
  the standalone `docker-compose` 5.2.0 command; its `docker compose` plugin is unavailable.
- Verification used the existing clean locked Python 3.12.13 environment and `PYTHONPATH=src`
  against the archived edited source, avoiding the reusable project environment and slow source
  reads in the Documents worktree. Earlier interrupted full runs are not counted as passing.
- This prior wave was committed as `095e5c02b01aea95fd7858a549a7765e7b0488c0` and passed
  [PR CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019194133) and
  [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/35019186906).

For deployed source `32ab71fc3c845c56068179fed98cf4a9eb80461e`:

- The CI failure was reproduced with a color-capable terminal. A plain/color parametrized regression failed before ANSI normalization and passed afterward; it still requires exit code 2, the specific missing-flag diagnostic, and no server start. Production CLI code was unchanged.
- The full local suite passed: 3,498 tests, 85.45% coverage with branch measurement enabled, and one existing Starlette deprecation warning.
- Ruff passes; strict mypy passes across 165 source files; Bandit reports no issues; `uv lock --check` passes.
- A fresh audit of the exact locked requirements reports no known vulnerabilities. Stale metadata in the reusable local virtual environment is not used as the dependency inventory.
- Compose rendering, deployment-script syntax checks, and `git diff --check` pass.
- Both [push CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34869770386) and [pull-request CI](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/34869775452) completed successfully on Python 3.12, 3.13, and 3.14.
- The native amd64 image build, paused-host deployment, missing-artifact denial, and mounted-artifact verification all pass.
- The two Cloud documents were reviewed against the referenced source. All 43 unique source line references resolve; the three documentation smoke checks pass.

These are snapshot facts, not completion claims.

For the operator-authorized reconnection on 2026-09-15, a clean runtime from `93b28f4` with locked dependencies passed 28 OAuth/CLI safety tests and 23 connected-shadow deployment/runtime tests. The native deployed image independently passed offline credential/configuration checks and the one authorized broker-read probe. No production application code changed during credential rotation.

## VERIFIED PAUSED DEPLOYMENT

- Source commit: `32ab71fc3c845c56068179fed98cf4a9eb80461e`.
- Immutable native image: `sha256:1a259e1a559c2ecb2ae0277e8f7fa2733e7e9f0c2b90ff418f5baa1c527e9d25` (`amd64`, `linux`).
- Resolved deployment configuration: `f617b11838362eccf5ea0e4e18e274974f347cb12f5e01006a1c1b7a3255f224`.
- Compose SHA-256: `6ad9422f7d5e10280fcccef97a6703edb6deeb422e7fcd64f9e6d3d2c5a55c54`.
- Default container: healthy; `/healthz` 200; `/readyz` 503; `trading_bot_live_enabled 0.0`; zero host mounts.
- The canonical release artifact is root-owned mode `0444`; `last-good` matches the exact image/config/Compose release key.
- A network-disabled, non-root container rejected an absent artifact and accepted the actual read-only mounted release artifact with matching configuration and Compose hashes.
- The previous image and release record were retained. Prior administrative Compose/helper files were preserved in a root-private backup. A full failure-injection/restore drill was not performed.
- A local ARM image was not deployed. The local legacy cross-platform builder failed, so the exact committed source archive was built natively on the existing amd64 host with bounded build memory and reduced CPU priority.
- Historical pre-rotation check on 2026-09-14: the broker-read probe failed closed and did not append an observation. A separately bounded schema-only handshake failed with `OAuthFlowError` before provider-tool invocation despite passing offline credential checks. Fresh authorization later restored the connection; the exact cause of the earlier OAuth failure was not established.

## VERIFIED CREDENTIAL ROTATION AND BOUNDED PROBE

On 2026-09-15, the operator separately authorized workstation browser authorization and then credential installation plus exactly one write-incapable server connection probe.

- Workstation bootstrap completed, verified the seven permitted read-tool declarations and one active individual cash Agentic account, and saved a new private encrypted store without overwriting the existing one. The new account fingerprint matched both the previous workstation store and the server store.
- The four credential files were streamed directly over host-key-verified SSH to a root-owned mode-`0700` staging parent. No credential values were put in Git, Cloud tasks, tool output, environment variables, or command arguments.
- A network-disabled, non-root container verified account-fingerprint validity, encrypted token/client validity, and configuration-to-image attestation binding before cutover.
- Under the deployment lock, the previous store was retained behind the root-private rotation parent and the new store was installed at the existing active path. Active and preserved store directories remain mode `0700`, their four regular files remain mode `0600`, and ownership is `10001:10001`. Application image, Compose, release identity, and live-disabled defaults were unchanged.
- Exactly one bounded connected-shadow invocation succeeded with `authenticated_reads=true`, `broker_health=true`, `code_identity_verified=true`, `zero_state_reconciliation=true`, `write_capabilities_present=false`, and `live_enabled=false`.
- The invocation persisted one non-promotable observation with `strategy_ineligible`, `live_data_invalid`, and `outcomes_incomplete`. Both evidence and promotion eligibility remain false; the qualifying calendar clock did not start. No diagnostic market-history read was requested.
- After the probe exited and its container was removed, the paused service still returned health `200`, readiness `503`, and live-enabled metric `0.0`, with zero host mounts. No SQLite WAL or journal sidecar remained.
- The subsequent network-disabled, read-only promotion preview verified ledger integrity, five ineligible shadow observations across four separate identity series, two rejected research assessments, and zero eligible observations, submission attempts, live authorizations, or leases. Every identity-bound promotion remained denied.
- No order review, placement, cancellation, recurring probe, live-mode activation, or application redeployment was performed. The credential remains trading-capable despite the client's local write incapability.

## SECURITY / EXECUTION RISKS

- The OAuth token is trading-capable even when application allowlists expose reads only; host or token compromise could trade outside the local client boundary.
- Any gap between requested image digest and executing image identity can invalidate promotion evidence. The deployed attestation binds those identities under a trusted-root host model; it is not remote signed attestation and does not protect against root compromise.
- Empty-only equity order/position mappings are insufficient for reconciliation or live recovery.
- Retry, lease, leadership, and reconciliation errors can duplicate or increase exposure unless kept behind fresh risk checks and idempotent journals.
- Research/data leakage, survivorship bias, unsupported interpolation, or incomplete outcomes can make promotion evidence invalid without obvious runtime failure.
- A funded account raises the impact of credential or host compromise even while the service is paused.
- Dirty worktrees and overlapping agents can silently combine unreviewed safety changes; exact commits and path ownership are mandatory.
- Terraform/cloud-init drift from the manually provisioned host can create false recovery assumptions.
- Missing elapsed evidence cannot be replaced by configuration changes, copied records, or synthetic timestamps.

## RECOMMENDED NEXT WAVE

1. The bounded broker connection was verified once on 2026-09-15 after credential rotation. Do not repeat ineligible probes as a promotion strategy or install recurring diagnostics; the critical path is validated research/data and complete outcomes.
2. The operator approved the written Alpaca Basic free-only validation specification and
   confirmed completion of paper-only Basic/free account setup on 2026-09-17. Inline local
   implementation of the bounded first-response diagnostic is complete; the next external
   step is its separately authorized capture gate, not another signup or more funding.
   Do not access credentials. Source choice remains a candidate. Resolve usage/retention
   and paper-only-versus-SIP entitlement ambiguity, agree the exact private paths and retention
   scope, then obtain one manifest-bound acquisition approval before authenticated capture.
   The probe will collect only two first-page samples; complete-history acquisition and an
   importer still require follow-on source-shape review and design. Publication to existing
   PR #1 and exact-implementation PR/push CI are complete as recorded above; the PR is not
   merged and no duplicate PR is needed.
   Imported data stays unsupported in the synthetic bundle implementation. Collection and
   historical availability, membership, corporate-action/interpolation provenance, and explicit
   coverage remain primary-owned source checks. Hash consistency alone cannot accept a source.
   Leakage, multiple-testing controls, source acceptance, and statistical acceptance remain open.
3. Use the completed IaC review to prepare a sanitized host-hardening and recovery evidence checklist. Do not import, rebuild, replace, resize, or apply Terraform without a separately reviewed plan and authority.
4. `CI-HARDENING-002` is integrated and verified green. A bounded attestation-test review can follow under its own exact-commit contract.
5. Compose qualifying paper and shadow cycles only after their research/data/outcome interfaces and evidence are complete. Preserve all existing observation and elapsed-time gates.
6. Keep broker writes, reconciliation, live runtime, and promotion decisions sequential under the primary owner.

The immediate aim is a reproducible, green, paused release with truthful evidence and clean delegation boundaries. Beginning live trading is not an acceptable shortcut around the critical path.
