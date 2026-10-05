# Incremental ETF replay and protected cost recording

This is offline research/integration software, not live trading readiness.

`EtfAccountStepper` applies each accepted account fact once, retaining the original
JSON-array prefix hash and common account/risk rules. It retains at most 10,000
physical facts. Failed advancement latches; reconstruct a fresh owner from its
verified tape rather than continuing a partially changed reducer.

`native_etf_baseline` projects bars/calendar/distributions without requiring a
dummy quote. The old native dataset API still rejects empty quotes.
`iter_native_etf_events(baseline, iter_catalog_quotes(...))` lazily merges quotes,
preserving duplicate observations and the existing availability/kind-priority
order. Catalog verification remains capture-bounded, not page-streaming.

`run_incremental_etf_history(context, source, catalog_hash=...)` consumes at most
10,000 source events per chunk and 100,000,000 total. It retains at most 10,000
detailed decisions and exact aggregate decision counts. The account-fact bound
still applies; crossing it denies the run, not a complete/truncated economic
report. Source failures return no completed result. `source_exhausted` means only
normal exhaustion of this iterator, never complete historical coverage.

Use `through_count=N` for a v2 checkpoint. Passing that result as `checkpoint`
reconstructs and verifies the complete prefix once before continuing the same
owners. This is linear verified-prefix recovery, not constant-time recovery from
a serialized closure. Chunk boundaries do not close a session, force a sale,
settle obligations or clear unresolved schedules. Legacy v1 result hashes remain
unchanged. V2 results are not accepted by the v1 full economic qualifier.

The 2024–2025 holdout remains sealed. Historical-control/publication waivers do
not manufacture OPEN controls, size semantics, quote coverage or calibrated
costs. Existing execution denials remain visible. No accepted after-cost or live
verdict follows from consuming a large unqualified source.

## Protected recording boundary

The optional owner observer records decision/submission/response events only
inside the existing initial-risk, review, final-risk and durable-attempt sequence.
Before-transport receipt failure prevents placement. After-transport failure
cannot erase the committed outcome or authorize retry. The receipt sink's own
UTC/monotonic clock session records local observations, not exchange latency.

An additive v2 `final_fees` receipt may finalize a fee-less terminal observation,
bound to the exact terminal receipt and separately retained fee source. Missing
fees remain missing; explicit component zeros are not inferred from missing rows.
Exact redelivery is idempotent; conflicting finalization is denied. This verifies
linkage/arithmetic only, not the authenticity or semantics of a broker document.

## Still required for a genuine sample

The shared service still rejects live modes. The current Robinhood runtime is
read-only and cannot reconcile nonempty orders/positions/fills. Authenticated
write behavior, operation-specific account/runtime evidence, live lease/fencing,
trusted full pretrade composition and all promotion gates remain required. The
user's one-trade authorization does not bypass them. No direct app-tool order,
test trade, live activation or deployment is performed by this implementation.

Full historical spans, genuine final fees/causal clocks, accepted economics,
qualifying paper/shadow observations and deployed recovery remain independently
unverified. No profitability claim is made.
