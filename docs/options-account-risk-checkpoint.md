# Options account-risk and readiness checkpoint — 2026-09-30

This development slice adds journal-bound loss history to the existing offline
execution clock. It does **not** complete the continuous strategy/account runner,
qualify a real-price study, deploy code, or authorize live trading.

## Implemented risk and restart foundation

- `OptionsLossObservation` wraps the unchanged legacy loss point with exact native
  availability and a causal ordinal. Both APIs use the same canonical loss reducer.
  A loss and recovery within one microsecond—or one nanosecond—remain distinct.
  A rounded timestamp is not proof of an observed session close.
- Additive `JournalRiskObservation` facts bind account/configuration, exact equity,
  external flows, event order and the preceding journal hash. Only the new fact
  uses the v2 hash domain; existing v1 journal/point preimages stay unchanged.
- Reconstruction checks every recorded monetary state after risk initialization.
  A later mark, flow or fill cannot hide an unobserved loss. The sole valuation
  exception is the first same-nanosecond mark for the exact newly held position
  whose liquidation mark is unknown. Existing partial-fill valuations cannot be
  overwritten before their loss observation.
- Weekly, drawdown and incomplete-history latches persist through exact-prefix
  restart. Deposits do not reset them, enlarge authorized sizing capital, offset
  losing episodes, or become trading P&L. Daily rebasing still requires the shared
  reducer's exact, complete preceding-session close.
- Entry halts remain separate from ownership incidents. They deny new BUY intents
  without preventing an independently permitted protective SELL, settlement or
  completion of its economic episode. No live order capability is introduced.
- Closed checkpoint commands now include marks, hypothetical external flows and
  risk observations. Restore replays and validates the commands rather than trusting
  saved balances, loss counters or a clean-status flag.
- A terminal, flat, settled book is still reported incomplete if initialized risk
  history is stale or lacks the final monetary observation. Lifecycle completion
  cannot silently stand in for complete loss history.

### Owner contract and limitations

This is an internal research clock, not a complete risk-admission API. Existing
genesis-only episode callers without risk history retain their prior engineering
behavior; they must not be represented as full-policy research. A new account owner
must initialize loss history at genesis, verify mark/session provenance and observe
each fill, mark and external flow at its actual clock nanosecond before proceeding
to another monetary state. Advancing past a pending observation fails subsequent
reconstruction rather than inventing a backdated repair. An interrupted prefix may
remain incomplete and must resume with its exact, verified inputs.

A non-null mark is an accounting input, not proof of freshness or executable
liquidity. The source-bound owner must invalidate stale/unknown marks, bind genuine
calendar boundaries and continuously evaluate the canonical risk policy. It must
also merge overlapping quote windows without replenishing liquidity or clearing a
held position's book merely because another candidate window ends. That coordinator
and its public `run_options_account_path` result/report remain unfinished.

## Separate readiness checks

The [actual-source audit](options-actual-source-readiness-2026-09-30.md) identifies
concrete blockers: actual semantic adapters/rules, individual partial-symbol
coverage, bar publication/corrections and the unsupported OPRA initialization
assumption. No qualified actual-price study or data purchase occurred. Existing
credit-only purchase authority is unchanged; credits alone cannot establish a
complete usable package or an economic edge.

The [broker/runtime audit](options-broker-runtime-readiness-2026-09-30.md) separates
public, session, account and runtime evidence. After that independent audit, the
coordinator used existing read-only authority for current account, portfolio,
options positions/orders and stock-position reads. Calls succeeded; the collection
responses supplied only empty-row shapes without further pages. No account IDs,
balances, raw payloads or credentials were written into this repository. Nonempty
fills, fees, settlement, restrictions, approval behavior and order writes remain
unverified. Successful interactive reads do not establish daemon authentication.

Current read-only DigitalOcean inspection found the configured service healthy and
paused: `/healthz` 200, `/readyz` 503 with `paused` and `external_capability_missing`,
shadow mode and `trading_bot_live_enabled 0.0`. The running container is UID/GID
10001, read-only, with zero mounts. Its observed image is
`sha256:1a259e1a559c2ecb2ae0277e8f7fa2733e7e9f0c2b90ff418f5baa1c527e9d25`.
Its read-only shadow configuration-hash command returned
`f617b11838362eccf5ea0e4e18e274974f347cb12f5e01006a1c1b7a3255f224`.
This is the existing health-only deployment, not this branch's code. No credentials,
environment values or private state were inspected; no container or host changes
were made. Matching release attestation, authenticated options adapter,
renewal, fencing, operational restore and production lifecycle remain unverified.

## Validation

The pre-change suite passed 6,123 tests, with 33 skips and one existing warning.
Test-first regressions reproduced missing exact-time observation/clock behavior,
then two independent-review findings: skipped loss marks and an overly broad
fill-to-mark exception. Both bypasses were fixed and independently reproduced as
denials. The reviewer passed 151 focused tests and cleared this foundation only.
The first reviewed candidate passed 6,155 primary tests (33 skips, one existing Starlette
warning) and 1,498 research-environment tests without skips. Ruff, Mypy (282 source
files), Bandit, both frozen lock checks and the main locked-dependency audit passed.
Its combined native/primary coverage was 89.02%, passing the unchanged 90% per-critical-
file branch gate. Final whole-commit review then found the incomplete-final-risk
reporting defect described above; its correction requires fresh verification rather
than inheriting that candidate's successful checks.
Four encrypted-backup tests remain skipped without local `age`; optional native
backends missing from the primary environment were exercised in research. Coverage
and exact-head remote CI remain separate integration gates; these counts do not
claim remote CI success. No source/economic/runtime gate is cleared by test counts.

## Next required work

1. Complete the single shared-clock, continuous strategy/account coordinator,
   session-close marks, overlap-safe inputs, risk observations and restart fixtures.
2. Implement and qualify native/reference semantic adapters; establish a complete
   usable pilot and current credit-only cost conditions before buying quotes.
3. Add effective-date costs, operating/cash comparisons, dependent-outcome uncertainty
   and untouched holdout testing. Insufficient data remains `ECONOMIC_NO_GO`.
4. Complete declaration-bound broker parsing and fake lifecycle contracts, then
   separately verify account behavior and the standalone paused runtime.
5. Only after objective research gates: paper, shadow, and separately authorized
   live readiness. No automatic promotion or live order is permitted by this work.
