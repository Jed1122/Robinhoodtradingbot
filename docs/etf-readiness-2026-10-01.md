# ETF implementation and readiness checkpoint

This is a development checkpoint, not accepted research or live authorization.
The operator reports an active Algo Trader Plus subscription. Existing read-only
connector samples returned 2016 SIP bars and quotes; those samples are not a
qualified 2016–2025 dataset. No subscription change, broker order, production
credential operation or deployment was performed by this continuation.

## Implemented increment

`simulation/etf_history.py` now provides `EtfFixturePrefixRequest`,
`run_etf_fixture_prefix` and `resume_etf_fixture_prefix`. This partial Task 3 owner:

- Restores the canonical model/envelope from the study's immutable JSON, verifies
  its exact hash and revalidates the study; it never reloads files or environment.
- Reuses `FeaturePipeline` and `MomentumStrategy` with precisely the latest 100
  completed, strictly earlier-available bars. Original and corrected versions
  remain distinct; later revisions cannot rewrite earlier decision hashes.
- Preserves the 750-bar warmup, fixed five-session cadence, $100 risk reference
  and separate hypothetical $500/$1,000 starting cash. No sizing authority grows.
- Rejects unavailable history, effective unsupported corporate actions and
  ineligible/expired session observations. Fixture clocks do not establish an
  authenticated exchange calendar, gap coverage or freshness.
- Keeps authoritative nanoseconds and source ordinals in identities. Datetime
  projections are used only after exact visibility filtering.
- Emits immutable paused checkpoints and reconstructs/compares consumed input
  and decisions before resume. Changed bytes, cash, study or checkpoint deny.
- Revalidates nested signal records before binding checkpoint hashes and rejects
  altered fixed study fields. Fixture daily bars occupy one New York session date
  each; only explicitly linked revisions may replace the same exact interval.
- Requires eligible open-session source/receipt/close dates to agree, with the
  next open on a later local date. Delayed cross-day clocks cannot consume an
  extra cadence slot. This is fixture consistency, not exchange-calendar proof.

There is deliberately **no order admission or execution**. Cash is unchanged,
shares/reservations remain zero, `account_replay_complete=False`, and execution
and promotion flags remain false. Checkpoint replay is in-memory reconstruction,
not durable SQLite persistence, fencing, economic restart or paper evidence.
The new owner files join the existing per-module 90% branch-coverage gate.

The independent increment review identified four validation issues. Nineteen
new regression cases reproduced them, then passed after the targeted fixes.
The focused prefix/coverage-check suite passes 78 cases, with 52/54 branches
covered in the decision owner and 16/16 in its state records. The wider final
verification passed 6,422 tests on each of Python 3.12, 3.13 and 3.14, with 33
optional-tool skips and one Starlette deprecation warning on each. A separate
native environment passed all 20 historical-episode tests. Combined coverage is
89.36%; the per-module 90% critical branch gate passes. These local results include
the preserved working tree; exact committed hosted-CI results remain distinct.
Ruff, Mypy, Bandit, both lock checks and both dependency-advisory audits passed.
Compose and deployment-script syntax checks passed without deployment changes.

## Separate readiness verdicts

| Gate | Current verdict | Missing work/evidence |
|---|---|---|
| Native historical data | BLOCKED_INPUTS | Native capture/decoder, complete pagination/coverage, original/revision availability, corporate-action/payment history and execution terms |
| Full account replay/restart | PARTIAL | Sizing/admission integration, orders/fills/cancels, cash/dividend/settlement accounting and durable transactional restart |
| Genuine after-cost economics | NOT_RUN / ECONOMIC_NO_GO | Qualified actual inputs, calibrated costs/fills, complete account outcomes, matched benchmarks and uncertainty evaluation |
| Broker/runtime | NOT_READY | Nonempty position/order/fill mapping, provider lifecycle behavior, deployed unattended authentication and operational recovery evidence |
| Qualifying ETF paper/shadow | NOT_READY | Accepted research and reviewed trusted composition; actual 100 eligible paper cycles and seven distinct UTC shadow dates |
| Live authorization | DISABLED | All independent gates plus explicit activation authority; no automatic promotion |

## Native-data findings

The current source module only accepts the code-owned synthetic format. Its
qualified-dataset constructor and iterator remain unavailable, not provisionally
approved. The earlier Basic-plan SIP denial is historical; a paid-plan user report
and successful sample reads improve access evidence but do not finish qualification.

The next native importer must retain exact bodies, request/response times, hashes,
allowlisted metadata and complete page-token chains. A short page is not proof of
completion. Pin SIP, raw prices, USD and explicit symbol mapping; provider inclusive
time bounds must be mapped to the study's exclusive end without losing records.
The `asof` argument is symbol mapping, not an original-revision query. See the
[official quote endpoint](https://docs.alpaca.markets/us/reference/stockquotes-1)
and [bar endpoint](https://docs.alpaca.markets/us/reference/stockbarsingle-1).

Daily bar timestamps describe the start of the New York aggregation interval,
not completion or historical availability; a receipt generated today cannot
establish what a 2016 decision knew. Preserve those separate concepts. See the
[aggregation documentation](https://docs.alpaca.markets/us/docs/market-data-faq).
Alpaca documents a corporate-action mutation stream, but its historical retention
and account access have not been established here; do not claim the interface is
absent. See [corporate-action events](https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse).

## Broker and paper/shadow audit

Read-only inspection at base `36b4f89` found empty-only equity position/order
mappings, no provider review/place/cancel adapters and no complete ETF runtime.
The paper CLI denies absent trusted research/account/data/reconciliation/runtime
composition. Connected shadow explicitly marks data and outcomes unqualified;
neither it nor generic shadow starts the qualifying elapsed-evidence clock.
The daemon is not a completed strategy scheduler.

The audit ran 222 existing broker/auth/paper/shadow/promotion/ETF-contract cases
and 386 fake-execution/recovery cases: 608 passed on Python 3.12. These are local
tests, not fresh account inspection, host verification, actual economic results
or broker-connected lifecycle proof. Nonempty mappings remain locked despite
empty-account read support. Robinhood's `internal` OAuth credential is trading-
capable; local read allowlists do not make the credential broker-read-only.

## Integration and next dependencies

PR #4 was merged after its actual hosted CI passed, at merge commit
`995a7a22661c442859ec3137bfae82735cd47dfb`. This does not include later uncommitted
fixture-prefix work and did not deploy anything. Protected unrelated dirty work
was not staged.

Continue native offline response validation and resolve original/revised-history
feasibility before bulk acquisition. Complete the canonical account owner and
durable research ledger; then integrate real costs, benchmarks and uncertainty.
Only independently accepted research may proceed to the later paper/shadow
composition and actual elapsed observations. No provider purchase or test can
guarantee a profitable strategy or a live start date.
