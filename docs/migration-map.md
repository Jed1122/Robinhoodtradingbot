# Options-only migration map

Governing specification: [complete master prompt](options-only-build-spec.md), retained
without textual changes (the repository copy has a conventional final newline).
Approved execution plan: [migration tasks](superpowers/plans/2026-09-18-options-only-migration.md).
This map covers every numbered section and traceability area of the historical
[multi-asset design](superpowers/specs/2026-07-10-robinhood-multi-asset-trading-system-design.md).
Classification is a policy decision, not an assertion that its replacement is complete.

| Original section / requirements | Classification | Options disposition |
| --- | --- | --- |
| 1 Purpose; small account, determinism, no return promises | Retained / replaced | Preserve safety; alpha universe becomes options only. |
| 2 Multi-asset entries | Retired | New options simulation profile disables standalone equities, crypto and prediction. Legacy research remains readable and unchanged. |
| 2 Blanket options prohibition and long-only equity invariant | Replaced / retained | Separate options types permit matched short legs in research; old OrderIntent validator and legacy equity prohibition remain unchanged. No options broker writer exists. |
| 2 Naked leverage, martingale, averaging down, hidden escalation, unofficial interfaces, autonomous LLM trading, generic liquidation | Retained | Never permitted by the migration. Covered-call/CSP/wheel also excluded. |
| 3 Capability baseline | Replaced / blocked | Public/session/account/runtime evidence are separate. Session declarations are not runtime authentication proof. Account/runtime options evidence remains missing. Historical negative evidence is retained. |
| 4 Delivery and no fictional gates | Retained | Incremental test-first slices, explicit remaining work. |
| 5 Python modular architecture and dependency direction | Retained | New domain/config/risk/simulation modules use existing neutral primitives. No broker imports in the new offline CLI or replay. |
| 6 Deterministic data flow and all 24 final checks | Retained / replaced | Options-specific economics replace inapplicable share calculations. Current capital filter is necessary only, not a substitute for 24-check admission. Full options composition pending. |
| 7 Decimal, typed immutable IDs/records, UTC, versions, sanitized evidence | Retained | Whole integer package units; versioned options serialization; old serializer unchanged. Numerical features use explicit bounded precision. |
| 8 Single config graph, precedence, release envelope, hashes, secrets | Retained | Required options subtree in existing AppConfig/SafetyEnvelope; no second loader. New config content intentionally changes hashes. Old JSON/hash evidence is never rewritten or relabeled. Old configs without the new required subtree fail rather than silently inheriting permissions. |
| 9 Modes and paused startup | Retained / blocked | New options profile supports offline modes only. Recorded replay is currently a simulation command, not a new persisted mode. Options shadow/live remain locked. |
| 10 Account isolation, $100/$150 assumptions, signatures, leases, expiry, exact acknowledgement | Retained | No balance verification or account access. New research tiers do not change these values. |
| 10/22 Micro-live $5 order, $20 gross, two entries/day | Replaced for options / blocked | Complete-unit feasibility, one unit/position/session; percentage and trial caps remain binding. No options micro-live composition exists; legacy equity settings stay historical/unchanged. |
| 11 Share quantity from stop distance | Replaced | Long options reserve full premium times verified multiplier plus bounded entry/exit fees. No stop-loss guarantee or fractional options. |
| 11 60% gross/40% cash, five positions, correlation limits | Replaced / retained | Options add 5% payoff risk, 2% group risk, 80% unencumbered cash, one initial position. The capital filter also retains stricter applicable legacy absolute/percentage notional limits. |
| 11 0.50% per-trade, 2%/5%/10% loss limits, activity/cooldowns | Retained | Whole-percent values; $100 means $0.50. Session entry cap tightens to one. Full dynamic loss-window integration is pending. |
| Prior trial $50 per-trade and $50 cumulative ceilings | Retained | Outer per-trade ceiling subordinate to percentage budget. Sum completed losing episodes; gains never offset consumed capacity. Incomplete episodes retain reservation. Durable history reconstruction still pending. |
| 11 Universal reward/risk 2:1 | Replaced | No unvalidated universal option payoff/exit requirement. Legacy strategy fields are retained, not silently reinterpreted as options evidence. Each future strategy must preregister/test exits. |
| 11 Equity/crypto liquidity and earnings filters | Retained / replaced | Underlying screening can be reused; options need contract-specific quotes, depth, expiry, events and stressed analytics. No exemptions to force a cheap trade. Full selection gates pending. |
| 11 Weekly/drawdown behavior and runtime action matrix | Replaced / retained | Future options entry halts must preserve separately authorized protective management; weekly/drawdown latches require manual review. Existing explicit kill/stale/unknown-ownership denials are not weakened in this slice. |
| 12 Order transitions, unknown acceptance, idempotency, cancel confirmation, restart | Retained | New replay uses the same order state machine. Unknown/cancel-pending retain reserves; no forced end-of-data close. Durable multileg lifecycle pending. |
| 13 Equity, Crypto, prediction adapters | Retired from options runtime | Keep underlying data/legacy evidence. No separate-leg spread fallback. |
| 13 Official options reads/review/place/cancel | Blocked | Schema/fake-contract work remains; real adapter requires separately authorized account/runtime evidence. Local Codex tool declaration inspection confirms single-leg-only review/place metadata; no broker tool was called or runtime support verified. |
| 14 Quotes, quality, provenance, licensing | Retained / replaced | Zero bids allowed as observations but denied for entries; locked quotes explicit; crossed quotes invalid. Contract/session/underlying identity is explicit. Point-in-time historical import/store pending. |
| 15 Equity/crypto/prediction active research families | Retired / replaced | Reuse underlying momentum features as unvalidated hypothesis. Options sequence: longs, debit verticals, credit verticals, then condors. Only single long-call engineering slice implemented. |
| 15 OOS/walk-forward, small grids, costs, metrics, uncertainty, registry, cash benchmark | Retained / extended | No synthetic result is economic evidence. Provider rights/history, QuantLib, Greeks, stress and empirical scorecards remain pending. |
| 16 SQLite WAL/Alembic, append-only audit, exact IDs/hashes, structured redacted logging | Retained / extended | No schema or production state migration yet. Options legs/reservations/settlement/trial ledger are later additive work. |
| 17 Crypto schedules and continuous-market assumptions | Retired | Contract-specific sessions; continuous service is not continuous options-market access. |
| 17 Single execution owner, leases/fencing, bounded scheduling | Retained | Future options continuous service must integrate existing protection; offline functions own no writer. |
| 18 Private read-only health/metrics, alerts, CLI, persistent kill switch | Retained / extended | Options status/Greeks/expiry/incidents pending. New commands are credential-free research only. |
| 19 Secrets, non-root container, DigitalOcean, backup/restore, rollback, shutdown, threat model | Retained / blocked | Existing files/deployment untouched. Options compatibility and current resource/cost verification pending; no deployment authorized. |
| 20 Optional read-only LLM and tax exports | Retained | No model/credential/order access added; missing tax facts stay unknown. |
| 21 Tests, properties, replay, chaos, dependency checks, 80%/90% gates | Retained / extended | SBOM tests use temporary output. Add explicit branch-only critical-module enforcement, not combined percentage. Coverage deficits must remain visible. |
| 22 Paper/shadow/micro/normal elapsed evidence and manual review | Retained | Clocks remain necessary but do not establish an options edge. Synthetic runs permanently ineligible. |
| 23 Deliverables, Makefile, docs and no-live-orders statement | Retained / extended | New research module CLI avoids overwriting unfinished main CLI work. Integration and other requested commands remain pending. |
| 24 Traceability; 25 definition of done | Retained | This map, implementation plan and validation report distinguish implemented, verified, pending and external blockers. |

## Governing master traceability

The preceding table disposes of historical requirements. This separate matrix traces
all 24 sections of the governing options master. A retained requirement is not necessarily
implemented. "Foundation" means local credential-free engineering, never production or
economic readiness. The approved migration further tightens the master's three-position
defaults to one unit/position/session and retains the $50 non-replenishing trial ceiling.

| Master section | Disposition and delivery evidence |
| --- | --- |
| 1 Assignment and authority | Retained. This map, approved migration plan and validation report preserve development-only authority. Full migration unfinished. |
| 2 Options-only scope | Retained, partial. Canonical options simulation overlay disables standalone asset entries; immutable structure identities exist. Production runtime migration and unexpected-share incident handling pending. |
| 3 Economic objective | Retained, pending. Synthetic cash-flow reports are engineering evidence only. No empirical scorecard, edge or selected winner. |
| 4 Official Robinhood capabilities | Retained, blocked for live. Existing negative findings preserved; separate public/session/account/runtime dimensions and options fake-transport integration pending. |
| 5 Account isolation and feasibility | Retained, partial. Eight hypothetical tiers and necessary whole-unit capital checks implemented. $100/$150 assumptions unchanged; no account verification or stress/capacity suitability established. |
| 6 Risk policy and sizing | Retained / tightened, partial. Canonical options subtree, multiplier/fee admission, one-unit/position/session ceilings and non-netted trial losses implemented. Full final risk evaluation, nonlinear costs and runtime loss windows pending. |
| 7 Contract master and market data | Retained, partial. Immutable contracts, point-in-time quote checks, session identity and adjusted-deliverable denial implemented. Historical storage, importers, provider rights and data acquisition pending. |
| 8 Strategy research | Retained, pending. Existing momentum calculations drive one unvalidated synthetic long-call hypothesis. Preregistered families, grids and comparisons pending. |
| 9 Selection and exits | Retained, pending. Explicit synthetic candidate/close inputs are not validated selection or exit policies. Liquidity, event and expiry policies pending. |
| 10 Pricing, Greeks and stress | Retained, pending. No numerical pricing backend, validated Greeks or full-repricing scenarios integrated. |
| 11 Event-driven backtests | Retained, partial. Deterministic next-observation synthetic fills, cancel race, incomplete outcomes and exact cash accounting implemented. Historical/partial-package/realistic execution validation pending. |
| 12 Validation and economic promotion | Retained, blocked. Every synthetic replay is non-promotable and `ECONOMIC_NO_GO`. Holdout research and options-specific economic promotion pending. |
| 13 Broker execution | Retained, blocked for live. No options adapter or write capability added. Read/review/place/cancel contracts, exact binding and final admission integration pending. |
| 14 Lifecycle and reconciliation | Retained, partial. Common transitions and in-memory trial reservations used. Durable legs, settlements, idempotency, recovery and full reconciliation pending. |
| 15 Exercise, assignment and expiry | Retained, pending. Contract identities exist; incident workflows, preceding-session deadlines and operational handling remain unimplemented. No stock-remediation authority. |
| 16 Modes and authorization | Retained, partial / blocked. Credential-free options simulation only; options paper/shadow/live compositions and evidence remain incomplete. Research capital never changes live authorization. |
| 17 Kill switches and degradation | Retained, pending for options. Existing guards unchanged and denial coverage extended. Options-specific entry-halt/protective-action composition and recovery pending. |
| 18 Architecture and storage | Retained, partial. Canonical Python/config/Decimal boundaries preserved and new evidence versioned. Parquet/DuckDB, QuantLib and additive options ledger migrations pending. |
| 19 Security and connector boundaries | Retained, partial. Offline CLI denies network in tests; no credentials/writers added. Runtime authentication and options production-security validation pending. |
| 20 Deployment and operations | Retained, pending for options. Existing DigitalOcean files untouched. Options scheduling, heartbeat, restore/rollback/resource validation and current cost estimates pending; nothing deployed this change. |
| 21 Tests and acceptance | Retained, partial. Focused tests, broad baseline, temporary SBOM verification and explicit critical branch gate implemented. All unimplemented lifecycle/research/operational acceptance scenarios remain outstanding. |
| 22 Parallel workflow | Retained, in progress. Coordinator owns protected implementation; isolated local CI/SBOM work reviewed and integrated. Local read-only reviewers used; no Cloud execution occurred. |
| 23 Commands and deliverables | Retained, partial. Standalone research CLI and this progress report exist. Integration into `trader`, the full command set and final six-milestone handoff pending. |
| 24 Official references | Retained, pending revalidation. Source references preserved, not asserted current. Each external capability/licensing/regulatory claim requires implementation-time verification. |

## Interface freeze for this slice

`domain/options.py` owns immutable option contracts, observations, 1:1 structures and
whole-unit limit/DAY intents. `domain/options_serialization.py` owns only
`options-order-intent-v1`; unknown or missing fields are errors. `config/models.py`
owns OptionsSettings and the loader/envelope enforce it. `risk/options_economics.py`
owns necessary capital checks and immutable completed-episode trial accounting.
`simulation/options_replay_models.py` fixes the synthetic-only request/result contracts.

No new AssetClass value is injected into legacy broker dispatch. Constructing a record
is not constructing a write capability. Package identity support does not establish
multileg pricing, partial-package execution, account permission or native tool support.
