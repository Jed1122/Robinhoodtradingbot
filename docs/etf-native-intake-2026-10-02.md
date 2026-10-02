# Native ETF intake, economic machinery and operational blockers

## Bounded intake implemented

`read_etf_native_quote_pages` reads every page of a retained native capture under
its existing limits: at most 128 pages, at most 1,000 records per page and at most
1 MiB of original response bytes per page. It checks the complete request/token/
receipt/raw-hash chronology before returning any archive. Empty terminal pages
remain represented, equal-time observations retain page/row identity, and native
prices, nanoseconds, raw sizes, exchanges, tape and ordered conditions are unchanged.

This is a separate `etf-native-quote-pages-archive-v1` identity. The old small-reader
10,000-row ceiling, bar/quote archive hashes, capture limits and stored reports are
not changed. It materializes a bounded archive: page grouping is **not** a streaming
or partitioned bulk-storage implementation or a daemon throughput guarantee.

`execution-coverage-run --page-bounded-quotes` opts into this reader. The flag
selects a bounded input representation; it cannot bless source semantics, accept
costs, enable orders or alter readiness. The default command keeps its original
reader and report identities. Both kinds can feed the same blocked coverage
assessment. No quote becomes synthetic or executable through this intake.

Test-first cases cover the 10,001-row boundary, all 128,000 admitted capture rows,
late-page corruption, excessive pages, unfinished/repeated cursors, backward time,
empty terminal pages, unchanged legacy limits, identity and CLI publication.
No new transport, credential read, download, spending or broker operation is added.

## Dependent statistics implemented

`dependent_mean_risks` reports exact loss and nonpositive counts from the same
seeded, noncircular 20/100-session moving-block draws used by the existing interval
API. Default draws remain 1,000 with outward 95% endpoints. Zero outcomes count as
nonpositive, not losses; classification occurs before mean rounding. Counts divided
by draws are dimensionless descriptive frequencies, not calibrated market-risk
probabilities or evidence of economic acceptance. Original observations and
resampled draws remain separate counts.

The legacy `EtfBlockInterval` record and `dependent_mean_intervals` values/hashes
are preserved. Tests independently specify small draw totals, hostile Decimal
contexts, extreme exact cancellation and seeded interval identities. This adds an
analytics prerequisite, not strategy returns, benchmarks or cost calibration.

## Actual retained input check

The page-bounded command reread the existing 1,074 quote observations and their
receipt chain. The result still has zero quote-observed or fully requested sessions
among 1,262 eligible development sessions. Report:
`9f3c31aff0b9e9212a81a1debb3f0fdd4cb755e22826aa1ce61fc99ee93cd352`.
All outputs remain `BLOCKED_INPUTS`, `ECONOMIC_NO_GO`, execution-disabled and
nonpromotable; the 2024–2025 holdout was not evaluated.

## Qualification and execution are still unfinished

The real-data adapter needs a source-neutral internal coordinator/quote-consumption
kernel, with unchanged fixture wrappers and a separately admitted native wrapper.
Native records cannot be supplied to sealed synthetic market-event constructors.
Historical fills may be simulated, but their native market provenance and replay
clock assumptions must remain separate from simulated account facts. Broker
acknowledgments/fills/cancellations/settlement cannot be fabricated notices.

Alpaca's dated size-change notice announces share-based display starting November
3, 2025, while the general stream schema labels sizes in round lots. It does not
explicitly establish the encoding of an older historical quote retrieved today.
The existing event-date `size_unit` hint is **not** authority for capacity conversion;
the intake retains `size_conversion_unverified` and never multiplies by 100.
[Dated size notice](https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change),
[stream schema](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data).

The documented live stream has status/LULD messages; the retained REST quote/schema
does not establish complete historical controls, continuous monitoring or exchange
sequence. A calendar-open session cannot manufacture `halted=False` or clear broker
restrictions. Requested REST spans and completed pagination are transport evidence,
not tick/control completeness.
[Historical quote endpoint](https://docs.alpaca.markets/us/reference/stockquotesingle-1),
[live control channels](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data).

Remaining prerequisites include full development coverage, dated quote conditions
and size semantics, action/ticker continuity, fractional order terms, settlement
and a code-owned cost/calibration assessment. Do not introduce user-supplied
`verified=True` flags. The six cash-tier/fill-scenario evaluator and native
execution are not delivered by the new reader or descriptive statistics.

## Runtime and qualifying operation

An October 2 authorized read-only browser inspection found the existing 2 GB
Droplet active. Its Web Console returned **“All configured authentication methods
failed.”** No remote command, service log, container identity or application health
was retrieved. The earlier SSH authentication denial remains consistent. Active
Droplet metadata does not verify runtime recovery or unattended authentication.
The console attempted its ordinary connection authentication; no manual password/
key-setting change, deployment, restart or production migration was performed.

A separate scoped `robinhood-2` check at approximately 06:45 UTC completed the
authorized account, equity-position/order and SPY-tradability reads. Personal
account results are deliberately not retained in repository documentation. This
establishes only interactive read scopes, not fractional limit-order minima/
increments, historical restrictions, order lifecycle, standalone authentication,
paper execution or deployed recovery. No order review, placement or cancellation
was called; no private account information is included here.

The study remains research-only and nonpromotable. Paper lacks a trusted ETF
composition; connected shadow diagnostics lack validated strategy data/complete
outcomes. Neither has started qualifying clocks. The 100 unique eligible paper
cycles and seven distinct UTC shadow dates cannot be generated by tests, replay,
diagnostics or a scheduled loop while these gates remain unmet.

Next: integrate qualified native observations through the sole accounting/risk
owner; freeze calibrated six-scenario economics and assess the untouched protocol;
verify host access/recovery and a separately trusted paper/shadow composition;
only then collect genuine elapsed observations. The fixed candidate also retains
unmeasured stability requirements and cannot be promoted merely by running a
NO-GO study. Live authorization remains independent.

## Revision-specific verification

Source commits `2fe3828` and `0b76da0` add only bounded intake/coverage and descriptive
resampling. The reused working tree passed 7,321 tests with 33 optional/tooling
skips and one existing warning; 20 separate native-history tests passed. Combined
statement-plus-branch coverage was 90.2268%; every required critical-module branch
gate passed. The aggregate number is not a claim of 90% overall branch coverage.
Narrow combined verification passed 157 tests. Ruff, Mypy (307 source files),
Bandit, both lock checks and both public locked-package advisory audits passed.
The research advisory export excluded its local editable project, not public
dependencies. Deployment/SBOM temporary-output tests passed 24 cases with four
age-dependent backup skips; four deployment shell syntax checks and standalone
Compose configuration validation passed. No tracked SBOM was overwritten.

Independent exact-head review found no Critical/Important issues: 455 focused and
regression tests passed; 14 malformed intake/qualification cases denied; 24 exact
Fraction-oracle scenarios (1,992 draws) matched; legacy interval/archive hashes
were unchanged. It did not inspect the private corpus or production runtime.
The first full Git-archive run had 7,244 passes and two diagnostic smoke failures:
offline probe preparation intentionally requires actual Git HEAD/root metadata,
which an archive lacks. An isolated local Git clone at the identical committed
head/tree passed both unchanged tests. Its complete rerun passed **7,246 tests**
with 33 optional/tooling skips and one existing warning in 483.58 seconds; fresh
native-history validation passed **20 cases** in 152.57 seconds. Combined coverage
was **90.1826%**; all **54 critical modules** passed the 90% per-module branch gate
(minimum 92.8571%). The exact tested source is
`0b76da0362982ad58837e8f18e10e45a36e34f0a`, tree
`3498389996c294bfa82d0656973d54ef9968ddf7`.

No identity check was bypassed, test skipped to avoid failure or source repaired.
The failed archive result is retained separately. Unrelated local edits are not
part of this increment. This completion document changes no executable code after
that source verification. Hosted interpreter-matrix completion is not claimed,
and no merge protection or readiness gate is bypassed.
