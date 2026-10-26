# Conditional stock portfolio replay

`research.stock_retrospective_replay_inputs` and
`research.stock_retrospective_replay` connect retained stock observations to the
existing paused-account simulator. They share its fills, lots, disposal basis,
tax reserves, dividend receivables, settlements, expenses and risk state. The
retrospective modules contain no network or brokerage interface.

This is an accounting and strategy implementation boundary. It does not establish
an investment advantage, a complete economic study or live readiness. Its source,
strategy, investment, trading and full-Task-5 authority flags remain false.

## Inputs and deliberately limited interpretation

`RetrospectiveReplayRequest` binds a freshly checked monetary preparation, a
separately checked replay schedule, annual measurement bundles and the fixed
`RetrospectiveReplayConvention`. `prepare_retrospective_replay_inputs` returns
conditional preparation or typed unavailability. Revalidation rebuilds from
complete retained originals and compares the derived fields.

The fixed frame contains AXP, AAPL, BAC, CVX, KO, KHC, MCO and OXY, with SPY as a
separate passive comparison. It retains 706 price sessions, from January 2, 2024
through October 23, 2026. Raw prices drive accounting; split-request prices drive
signals. Exact native integer volumes and missing native interpolation/currency
fields are retained. The admitted profile requires equal price units and does
not implement a split conversion. USD is an explicit retrospective interpretation,
not a native daily quote field.

This conditional reference omits historical sector, market-cap, earnings-risk,
bid/ask, broker-tradability and complete lifecycle screens. It does retain the
causal USD10 price screen and a USD20million mean of the prior 20 completed raw
close-times-native-volume observations. This is a dollar-volume proxy, not a
verified historical spread or execution price. Omitted constraints never become
production approval. All 56 fully constrained stock/family dependencies remain
unavailable and all eight long-term quality allocator gaps stay visible.

The retrospective universe uses a named reported-date-plus-one-UTC-day proxy for
the original disclosure. Current source receipt clocks remain current. Historical
annual availability follows the separately documented filing convention; an AXP
annual supplement does not supply the other seven issuers. Unknown event or
estimate vintages remain missing.

## Public lifecycle

1. Prepare source-bound inputs with `prepare_retrospective_replay_inputs`.
2. Register independent `RetrospectiveCaseSpec` values, each with its own family,
   economic protocol and explicit operating expense plan. The public case bound
   is 1–512; duplicate specifications reject. A permitted bound is not a runtime
   or resource guarantee.
3. Call `begin_retrospective_economic_replay`. Each available case starts with its
   own paused USD1,000 account at session 200, using completed close 199. Cases
   never share cash, fills or risk state.
4. Call `advance_retrospective_economic_session` for the exact next native index,
   200 through 705. Decisions use completed information and modeled next-open
   execution. Unsupported funding leaves earned dividends as receivables;
   unsettled sale claims do not become buying power.
5. Call `finish_retrospective_economic_replay` only at next index 706 and supply
   independently freshly loaded inputs. Finish checks full source identity and
   the final book/cost histories. No padded date creates a price, fill or return.

PEAD and revision momentum have explicit unavailable case records because this
boundary has no historical event-vintage source. Quality momentum without any
annual inventory is unavailable. An admitted annual inventory still cannot turn
missing issuer measurements into neutral values or a complete family comparison.
The long-term quality variant remains unavailable until its allocator is built.
The available long-term reference is the separately labeled passive 75% SPY
baseline.

`checkpoint_retrospective_economic_replay` produces an inert source/specification/
prefix commitment. `resume_retrospective_economic_replay` requires fresh original
inputs and reconstructs the consumed prefix before comparing the state. It is
not a serialized trusted cache or a constant-time restore. The late evaluation
period is explicitly marked reused; a restart cannot make it a fresh holdout.

## Integrity and work ownership

Preparation, begin, resume and finish revalidate complete source originals.
Advances verify compact metadata, consumed observation/calendar windows and
annual measurement identities. Calendar proofs cover every row exposed to the
policy, including the next native open, without reading future price/volume.

The private synchronous book/cost transaction checks complete incoming and
outgoing history. Inside one advance, it validates only owned append deltas and
current-book cost summaries. Any book transition invalidates the earlier summary.
Public accounting helpers, state evidence, reports and recovery keep fresh
validation. The transaction is never accepted from a caller, stored globally or
carried to another advance. It preserves canonical ledger arithmetic and legacy
evidence preimages. These checks detect inconsistent objects; they do not
authenticate an arbitrary rewrite of process memory.

Complete history checks still entail growing work across the horizon. Short
fictional performance profiles measure implementation overhead only, with no
promise about full-grid timing or investment performance.

## Completing the study

The [descriptive metrics consumer](stock-monetary-metrics.md) can summarize a
completed result after fresh source verification. It retains unavailable cases,
cost/tax assumptions and policy-coverage denominators; it supplies no investment
qualification or statistical inference.

Source-envelope verification, frozen actual-input assembly, metric/benchmark
conventions and experiment registration precede actual monetary comparisons.
Remaining work includes seven-issuer annual mappings, earnings/estimate vintages,
historical constraints, long-term stock allocation, all required exit/benchmark
controls and the full cost/tax/stress/statistical report. Unavailable comparisons
remain incomplete. No result from this boundary enables live trading.
