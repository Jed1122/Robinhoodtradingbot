# Equity history prerequisite handoff — 2026-10-04

## Delivered software boundary

Credential-free functions `parse_equity_orders_page` and `assemble_equity_order_history` in
`brokers/robinhood_equity_history.py` implement the exact preserved Robinhood-2 declaration,
not authenticated account behavior. They preserve original bytes and hashes, exact fractional
shares/fees, provider nanosecond timestamps, optional/null distinctions, unknown state denials,
native execution deduplication and conflicting-evidence rejection. Explicit request filters and
bounded terminal opaque-cursor chains must match. Private records/free text never appear in repr
or errors. No private customer fixtures, account identifiers or credentials are committed.

Matching order/per-fill regulatory-plus-clearing fees establish internal consistency only.
All authority flags remain false; final-fee and complete-history verdicts remain unknown.
The authenticated nonempty-order/position gate, canonical risk/configuration and live blocks are
unchanged. This parser is not wired into the provider adapter or calibration evaluator.

## Genuine cost and historical economics

The previously retained activity export had funding only, not equity executions. Do not create
test trades, repeat empty-history polling or substitute declared/synthetic fills to close this
gap. Genuine costs require supported final charges, owned orders/fill IDs, dated matching Alpaca
quotes, and actual same-local-clock order receipts; later export timestamps cannot reconstruct
decision/arrival timing. Fee absence is not explicit zero. Actual calibration remains
`BLOCKED_INPUTS` until those inputs exist.

The existing historical evaluator remains latest-vintage exploratory and `ECONOMIC_NO_GO`.
Complete qualified execution quote/control/action coverage, supported execution/cost assumptions,
robustness and untouched final validation remain independent requirements. A technically complete
evaluator does not guarantee an economically accepted strategy or profitability.

## Forward paper/shadow and standalone runtime

An exact-base read-only audit found `PaperPromotionComposition` is still an injectable boundary,
not a trusted ETF factory, and generic paper results remain in memory. Connected shadow explicitly
denies validated data and complete outcomes; it is a diagnostic, not a qualifying strategy cycle.
The frozen ETF study/account/history contracts cover 2016–2025 and the history owner is
`etf-offline`. Do not widen those identities to relabel October 2026 observations as forward paper
evidence. A new versioned owner must connect independently qualified Alpaca inputs, accepted
research, canonical risk, simulated execution, durable economic state and promotion journaling.

Before runtime recovery can be verified, add reviewed joint ledger/journal/checkpoint backup and
recovery composition, then inspect the actual immutable runtime/authentication/state within
authorized read-only scope. A paused health endpoint or credential-directory metadata does not
prove unattended strategy recovery. Deployment/credential mutations and real broker writes are
outside this increment. Only after independent eligibility passes can genuine 100 paper cycles
and seven distinct shadow dates be collected; no synthetic counters or automatic promotion.

## Verification

The implementation follows the saved design/plan with synthetic declaration-shaped fixtures
and unchanged adapter/calibration regressions. Exact revision-specific full verification and fresh
whole-branch review are recorded in the implementation handoff/PR; no authenticated provider
tests, historical qualification, genuine fills or deployment recovery are claimed by local tests.
