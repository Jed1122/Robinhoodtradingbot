# ETF restart, execution coverage and readiness — October 2, 2026

## Implemented checkpoint

`strategy-checkpoint-run` persists the synthetic ETF coordinator across separate
processes. It stores the complete source cursor, orders, reservations, accounting,
frozen exit policies and decisions together. Restore recomputes each committed
prefix through the existing coordinator and compares every serialized field.
Changed request/code/configuration identities, corrupt or missing snapshots,
regressed cursors and stale expected heads deny advancement.

An existing private `0700` directory outside the repository is required. The
descriptor-bound publisher retains immutable `0600` snapshots, a hash chain and
a request ownership marker. A nonwaiting filesystem lock excludes concurrent
local writers. SIGKILL tests cover failure before publication, staging bytes,
the publication link and completed publication; retry reconstructs either the
old complete prefix or the new complete prefix without duplicating cash or loss.
Private orphan staging files are validated and ignored, never treated as state.

For example, run these commands in two separate processes, using a private
directory created for this specific synthetic request:

```sh
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research strategy-checkpoint-run --output-dir /absolute/private/research-directory --through-ordinal 753
PYTHONPATH=src .venv/bin/python -m trading_bot.cli.etf_research strategy-checkpoint-run --output-dir /absolute/private/research-directory --operating-cost 0.25
```

The first command retains 0.15 shares and trial reservation, with an incomplete
outcome. The second reconstructs the same request and completes its fabricated
protective sale and explicit settlement: cash $499.63553015, trading P&L
-$0.36446985 and operating result -$0.61446985. Fees/spread are already in the
cash flows and are not deducted again. Partial cancellation and unsettled/open
outcomes remain incomplete. Hypothetical $1,000 uses the same risk reference.

This is durable **offline synthetic process replay**. It does not migrate a
production ledger, implement distributed fencing, reconnect a broker or establish
service recovery. The existing SQLite pathname CLI remains unavailable on the
current platform because it cannot bind journal paths to a checked directory fd.
All outputs remain paused, execution-disabled and nonpromotable.

The checkpoint adapter is intended for short fixture runs with coarse checkpoints,
not a long-running daemon. Every restore replays every retained prefix; a fine-grained
chain therefore accumulates quadratic replay work in checkpoint count. Independent
review measured idempotent restore at 0.193 seconds for 10 checkpoints and 0.565
seconds for 30 initial-bar checkpoints. Those small probes are not an upper-envelope
benchmark. A representative performance regression and a reviewed storage design
are required before expanding the operating envelope; the 10,000-observation input
bound is not a throughput guarantee.

## Actual historical coverage

`execution-coverage-run` reads saved receipt-verified native bar/quote archives
and a hash-bound calendar, then publishes a private report. Repeated
`--quote-capture-dir` and `--quote-manifest-hash` pairs allow at most 128 archives.
It distinguishes recorded quotes from the union of requested session intervals;
neither proves tick completeness, controls or executable liquidity.

The current retained package has 2,514 daily bars matching the calendar and 1,074
quote observations. After the 750-session warmup there are 1,262 development
sessions before 2024. **Zero development sessions have quote observations in this
package, and zero have full-session quote requests.** The quote probe predates the
eligible development period. Coverage report:
`db09a8145ab3582c748f9960c0e18304a7e3c63620fca87e7d92b9bad213a256`.

Missing requested session dates are recorded explicitly in the private report.
Quote conditions, size-era conversion, halt/LULD/gap semantics, corporate-action
continuity, fractional order terms and calibrated execution costs also remain
unqualified. The current capture owner is bounded retrospective acquisition,
not a continuous collector. Its historical scope ends January 1, 2026; it cannot
capture current paper/shadow observations without a reviewed new capture scope.
The quote reader's 10,000-row ceiling also needs an independently tested storage
extension before using larger captures; no truncation or ceiling bypass is used.

## Economic and paper/shadow disposition

The existing development-only mathematical benchmark screen ran again from the
saved bars, calendar and issuer distributions. It evaluated 1,262 records, retained
all 502 holdout records without evaluating them and returned `ECONOMIC_NO_GO`.
Report: `9f447b66da2ececa49dd079f4d0738e2a15513e7dd14e11e418ff6306f43fda0`.
This remains a price/benchmark screen; actual after-cost candidate execution,
matched calibrated fill scenarios, folds and uncertainty acceptance were not run.
The original publication/correction waiver is retained; it does not supply the
missing execution inputs.

The paper/shadow audit confirmed that the ETF study is registered for offline
research only, with execution and promotion permanently false. The public paper
command has no trusted composition and denies before state changes. Connected
shadow probes deliberately lack validated strategy data and complete outcomes.
No qualifying clocks have begun. Accepted research, a reviewed ETF runtime
composition, account/provider/runtime identity and clean reconciliation must
precede the existing 100 unique eligible paper cycles and seven distinct UTC
shadow dates. Fixtures and diagnostic reads cannot create those observations.

The October 1 scoped Robinhood reads remain evidence only of that app session.
No new authenticated broker calls occurred in this increment. October 2 read-only
DigitalOcean SSH inspection again returned `Permission denied (publickey)`, so
the deployed service, authentication renewal and operating state remain unverified.

## Required next work

Extend bounded native storage/capture and the native execution adapter using
verified control, quote-condition/size, action and fractional-order semantics;
acquire the missing development coverage before evaluating candidate outcomes.
Freeze calibrated costs and the complete six-scenario protocol, then evaluate
development/validation and the retained final test according to the study rules.
Implement the trusted paper/shadow composition only after the economic and data
gates can be satisfied, verify the standalone runtime and collect the required
elapsed observations. Production recovery and broker write behavior still need
their own implementation and evidence. Live authorization remains separate.

The requested full project is not complete. Durable synthetic restart and a
measured coverage report are implemented; historical execution, economic
acceptance and qualifying operation remain blocked or unfinished as stated above.

## Verification and integration

Source increment: `0e385b0eb5e93ce414f21ccdcf840c84760eae1d` through
`1ad4526d039b615688b1f6e2ef0226a60563c74a`. The existing unrelated dirty paths
remain outside these commits and are not claimed as reviewed deliverables.

- Local Python 3.12 regression: **7,256 passed, 33 skipped**, one existing warning.
- Separate native-history environment: **20 passed**.
- Combined statement/branch coverage: **90.20%**; all critical modules pass their
  **90% branch** gates. The new checkpoint module covers 17 of 18 branches.
- Independent exact-commit archive review: **58 tests passed**, no Critical or
  Important findings. The nonblocking replay-performance concern is recorded above.
- Ruff, Mypy (307 source files), Bandit, both offline lock checks and both fresh
  locked-dependency advisory audits passed; the audits found no known vulnerabilities.
- SBOM temporary-destination reproducibility passed within the regression suite.
  Compose validation and syntax checks for the four DigitalOcean scripts passed.

The main-environment optional/tooling skips include four encrypted-backup tests
requiring an unavailable `age` executable. No successful backup roundtrip is claimed.
No hosted multi-interpreter matrix was awaited or reported as passing. Existing
branch protections are not bypassed. Private validation logs, input reports and
coverage files are retained outside the checkout. No raw licensed inputs,
credentials, production migration, deployment or broker write is included.
