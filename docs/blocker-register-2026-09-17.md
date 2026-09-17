# Live-readiness blocker register

Reviewed: 2026-09-17 UTC. Local source revision:
`a447de05da54e078b1b28859cdb5a04085d46e2b` on
`codex/continue-implementation-from-commit-7c4dcd1`.
Pre-existing uncommitted documentation and shutdown-test changes were preserved.

**Release disposition: NO-GO.** This is a source audit and closure roadmap, not a
new runtime design approval, provider permission, promotion attestation, or deployment
verification. No live order, credential operation, provider-data acquisition, production-ledger
access, subscription purchase, or deployment change was performed during this review.
Existing host and authenticated capability facts remain historical unless explicitly refreshed.

## Findings that change the work sequence

- The configuration-driven simulator is implemented for **one synthetic order**. It is not yet
  integrated with a complete strategy entry/exit lifecycle or multi-order portfolio accounting.
- At the audited revision, `backtest` and `simulate` in `src/trading_bot/cli/main.py` called
  `_summary` and misleadingly emitted `completed_offline`. The approved replay implementation
  now corrects the summary to `configuration_only` with `executed=false`. These commands still
  do **not** execute a strategy backtest or the new simulator; exit status is not outcome evidence.
- The public paper command intentionally has no trusted `PaperPromotionComposition`. It fails
  before creating a ledger or lock and reports seven missing inputs. Passing this negative test
  verifies the guard, not paper readiness.
- `LiveApplication.run_cycle` in `src/trading_bot/runtime/live.py` checks the paused state but
  contains no live decision/execution cycle. The guarded factory is not a complete live runtime.
- Connected-shadow probes retain `data_validated=false` and `outcomes_complete=false`.
  A verified release attestation can establish runtime scope, but cannot turn a diagnostic into
  eligible shadow evidence or start its seven-date clock.

## Dependency chain

Two independent tracks can advance without weakening any gate:

```text
Offline strategy lifecycle and deterministic outcome accounting ----+
                                                                  +--> accepted research
Source rights --> authorized capture --> real-data validation ------+

Accepted research + reviewed provider/account evidence + clean reconciliation
    --> trusted paper and write-incapable strategy-shadow composition
    --> eligible paper cycles and elapsed shadow dates

Provider write evidence + recovery controls + reviewed live composition
    + qualifying promotion + security/operations evidence + explicit authorization
    --> separately reviewed micro-live activation
    --> further observations and review --> separately reviewed normal-live activation
```

The tracks converge on evidence; a software test, a funded account, a plugin connection, or a
synthetic run cannot substitute for it. No start date or completion deadline is asserted here.

## Remaining blockers and closure criteria

| ID | Subsystem and current status | Required closure evidence | Boundary / dependency |
| --- | --- | --- | --- |
| B01 | Complete offline strategy replay: **partial** | Existing strategy decisions drive entry and exit intents, configured execution outcomes, explicit portfolio/cash state, deterministic IDs, and canonical typed audit records. Cover rejection, no/partial fills, cancel races, stale data, concurrent cash/liquidity constraints, configured exits, and incomplete outcomes. Wire a truthful operator command to the real runner. | New reviewed design required. Reuse existing config/risk/lifecycle logic; no second strategy or sizing implementation. Synthetic output stays non-promotable. |
| B02 | Real-source entitlement and retention: **blocked** | Applicable source terms or written clarification covering the exact account, feed, corporate actions, private retention, and intended use; explicit private capture paths and bounded acquisition authority. | Alpaca is optional. The support thread was rechecked in this review and contained only the sent inquiry, with no reply. No message was resent. Spend authority remains $0. |
| B03 | Real-data ingestion and provenance: **unimplemented for real sources** | Reproducible raw-to-normalized replay, hashes, source provenance, point-in-time membership, coverage/gap checks, and verified split/dividend handling. Preserve the configured 3,650-calendar-day request window and 750-daily-bar minimum. | B02 and an approved provider-specific design/capture. Current bundle loader supports only `synthetic-market-v1`; synthetic consistency is not source authenticity. |
| B04 | Accepted research: **blocked** | Complete entry/exit outcomes, all attempts recorded, required purged/walk-forward validation and bias controls, cost/fill stress, Monte Carlo/robustness, benchmarks, and canonical acceptance decisions on validated data. | B01 + B03. Existing ETF comparison uses complete next-open target fills and is not acceptance evidence. No positive result is guaranteed. |
| B05 | Broker response and write capabilities: **externally unverified / absent** | Reviewed nonempty position/order/fill and pagination shapes; exact review/place/cancel semantics and durable submission identity evidence before implementing a capable adapter. | Separate explicit authenticated authority. Seven equity reads have historical sanitized evidence, but empty rows are not evidence of nonempty mapping. No order may be created merely to manufacture evidence. |
| B06 | Trusted paper and strategy-shadow composition: **missing** | Supply accepted research, exact account/provider/strategy/config/code identities, validated data, complete simulated outcomes, clean reconciliation, and runtime attestation. Persist real observations through existing stores/mutex and verify restart/idempotency. | B01, B03, B04, and relevant B05 reads. Do not replace missing inputs with caller-selected booleans or enable research flags prematurely. |
| B07 | Reconciliation and recovery integration: **partial** | Durable nonempty order/fill recovery, partial-fill shutdown/restart, unknown-submission handling, cancellation uncertainty, and fault evidence that unknown state pauses and never duplicates exposure. | Reviewed provider evidence and primary-owned execution/reconciliation design. Current callback shutdown tests do not prove host/broker recovery. |
| B08 | Live cycle and controls: **unimplemented composition** | Reviewed integration of decision pipeline, independently injectable review/place/cancel capabilities, canonical pretrade checks, signed authorization/leases, locks, and unknown-state controls. Startup remains paused. | B04-B07 and separate design/activation authority. Review existing preflight literals against canonical configuration; do not relax limits. No provider adapter from a schema declaration alone. |
| B09 | Release/security/operations evidence: **partial, current host unverified** | Exact candidate commit passes CI, dependency/static/security review, immutable image verification, paused health/readiness denial, live-disabled metrics, image/config attestation, alerts, backup/restore, and rollback checks for that release. | Local checks below are fresh; remote CI/image/host were not refreshed. No push, merge, build, deployment, credential rotation, or host inspection was performed. Local audit success is not a stage-specific security clearance. |
| B10 | Qualifying promotion evidence: **blocked by prerequisites and elapsed time** | At least 100 unique eligible paper cycles and seven distinct eligible shadow UTC dates before micro-live, plus current stage-specific security, manual acknowledgement, and runtime controls. | B04, B06-B09. Diagnostic/synthetic observations do not count. Code/config/account/provider/strategy identity changes partition the evidence population. |
| B11 | Normal-live promotion: **future gate** | Retain paper/shadow requirements and accumulate at least 100 eligible combined observations over 30 distinct UTC dates, including micro evidence, plus current order-boundary review, slippage/drawdown and required attestations. | A separately authorized, qualifying micro stage first. Normal observations do not bootstrap eligibility; no backdating or compressed elapsed-time substitutes. |

The seven exact public-paper blockers are defined by
`src/trading_bot/runtime/paper_promotion_runtime.py`:

```text
accepted_research_evidence_unavailable
account_identity_unavailable
provider_evidence_unavailable
strategy_cycle_composition_unavailable
validated_market_data_unavailable
clean_reconciliation_unavailable
runtime_scope_attestation_unavailable
```

Other unresolved items should not be silently folded into a green status. In particular,
`DecisionCycleService` currently serializes outcomes with `str(item)` and `IntentPlanner` creates
fresh order IDs. A repeatable whole-strategy replay needs explicit identity and outcome contracts;
the deterministic single-order simulator alone does not establish them.

## Checks executed in this review

The existing Python 3.12 verification environment was used with `PYTHONPATH=src` pointing at
this worktree, not its editable-install target. No dependencies or lockfiles were modified.

- Focused simulation, paper, CLI, runtime, reconciliation, and promotion selection:
  **472 passed**, one existing Starlette/httpx deprecation warning.
- Ruff: passed.
- Mypy: passed for 184 source files.
- Bandit: exit 0, no findings reported; existing `nosec` comment warnings remain.
- `uv lock --check --offline`: passed, 105 packages resolved.
- Locked dependency vulnerability audit: exit 0, **no known vulnerabilities found** by the
  configured advisory service at review time. This is not a guarantee of absence of vulnerabilities.
- Full non-authenticated suite with branch coverage: exit 0; **87.24%** combined line/branch
  coverage, above the unchanged 80% floor. The existing Starlette/httpx warning remains.

The direct `pip-audit --locked .` dry run did not recognize `uv.lock`. An installed-environment
attempt rejected the editable project. Neither attempt is a successful audit. The completed
check exported the existing frozen lock to standard input without emitting the local project:

```sh
set -o pipefail
uv export --frozen --offline --all-groups --no-emit-project \
  --no-annotate --no-header --format requirements.txt |
  python -m pip_audit --requirement /dev/stdin --no-deps --disable-pip \
    --strict --progress-spinner off --timeout 15 -f json
```

Here `python` denotes the reviewed verification environment. The export includes the locked
transitive dependencies and hashes; `--no-deps --disable-pip` prevents a fresh dependency
resolution or installation during the audit, consistent with the CI lockfile-audit approach.
Environment markers still select the applicable dependencies for that environment. This does not
replace the remote Python 3.12/3.13/3.14 CI matrix, a container scan, or a deployed-host review.

## Plugin assessment

The installed-plugin directory was checked, not inferred from names in the sidebar.
Installed/enabled does not prove a connected account, suitable entitlement, or authority to use
an authenticated operation. No plugin was installed, account connected, or subscription changed.

| Plugin | Directory state | Useful role | Does not resolve |
| --- | --- | --- | --- |
| GitHub | Installed/enabled | Exact-commit CI results, PR/diff review and scoped integration tracking. | Missing runtime implementation, research or live authorization. |
| Codex Security | Installed/enabled | Focused security review of new composition boundaries and repository findings. | Broker evidence, trading suitability or an automatically valid promotion clearance. |
| Alpaca | Installed/enabled | Candidate data access after rights, source-quality and exact operation authority are resolved. | Paper-only SIP/retention ambiguity, real-data acceptance, or missing execution integration. |
| DigitalOcean | Installed/enabled | Later approved infrastructure work and deployment inspection. | Strategy outcomes or promotion evidence; no new Droplet is currently justified. |
| Financial Datasets / Massive | Not installed | Optional alternative-source candidates if a documented data requirement cannot be met by the existing path. | Required history/corporate-action coverage, license/retention rights, cost and source provenance must still be checked. Not recommended as an immediate prerequisite. |

**Recommendation: no additional plugin is required for B01 or the current local verification
work.** Use the already installed review/CI capabilities when their scoped task arises. Keep data
provider selection neutral; a new broker/plugin or paid data plan is not an engineering fix.

Public documentation checked for candidate capability context:

- Alpaca describes Basic/free data and paid tiers in its
  [market-data overview](https://docs.alpaca.markets/us/docs/about-market-data-api).
  That overview does not settle the account-specific questions in the outstanding support inquiry.
- [Financial Datasets documentation](https://docs.financialdatasets.ai/introduction) lists structured
  prices, company data and active/delisted tickers. That listing is not verification of the exact
  history, corporate-action or retention requirements here.
- [Massive stock-data documentation](https://massive.com/docs/rest/stocks/overview) describes its
  market-data interfaces. An interface description is not acceptance of an account's license or
  proof that a particular plan meets this project's data contract.

## Proposed first implementation decision

Recommended next scope: **offline equity strategy replay through the existing decision pipeline,
configured order simulator, and lifecycle accounting**. Include explicit cash/position state,
deterministic identities and typed outcomes, configured exits, and tests for denied/incomplete
paths. Do not add a new strategy, change risk limits, acquire data, construct a broker writer,
touch production persistence, or create promotable evidence in this slice.

The operator selected this scope during the review. The
[written replay design](superpowers/specs/2026-09-17-offline-equity-strategy-replay-design.md)
was approved by the operator. The [implementation plan](superpowers/plans/2026-09-17-offline-equity-strategy-replay.md)
records completed integration seams and the remaining replay work. Source-first work can continue
after the external rights issue is resolved; broker-first work requires separately scoped
authenticated evidence and is not a shortcut around the offline lifecycle. Existing inline and
primary-owner boundaries remain in force. No new parallel or Cloud task was dispatched.
