# Offline options research: first engineering slice

This is working synthetic engineering software, not historical performance evidence,
an accepted options strategy, a live adapter, or the completed six-milestone migration.
It reuses existing 20/100-window features and momentum decisions, strict config loading,
canonical hashes, Decimal arithmetic and the common order-transition function.

## Commands

From the repository root in the locked development environment:

```sh
PYTHONPATH=src uv run python -m trading_bot.cli.options_research capital-feasibility
PYTHONPATH=src uv run python -m trading_bot.cli.options_research capital-feasibility --premium 0.10
PYTHONPATH=src uv run python -m trading_bot.cli.options_research options-replay
PYTHONPATH=src uv run python -m trading_bot.cli.options_research options-replay --research-capital 2500
PYTHONPATH=src uv run python -m trading_bot.cli.options_research options-replay --research-capital 2500 --scenario unknown
```

The $100 default denies the fixture's $11 premium-plus-fee risk because its 0.50% budget
is $0.50. At hypothetical $2,500 research capital the fixture pays $10 premium and $0.50
entry fee, receives $15 on closing and pays $0.50 exit fee: final cash $2,504 after an
explicit settlement event. These prices, depth, sessions, fees and holding period are
fabricated inputs, not estimates of achievable returns or a recommendation to add funds.
The $100/$150 live assumptions remain unchanged.

Scenarios: `completed`, `loss`, `open`, `unfilled`, `unknown`, `unsettled`, `cancel_race`,
`canceled`, `rejected`. Incomplete scenarios return exit code 2; malformed input returns
1 with a value-free error; completed/no-trade outcomes return 0. No end-of-input exit
is invented. Reports include exact cash/receivables, fees, transition history, hashes,
trial reservation, and permanently false promotion/production eligibility.

Fill eligibility is tied to a new quote observation after acceptance and configured
latency, not merely a later replay envelope carrying an old quote. Closing orders get
their own session-bounded deadline. Settlement is an explicit event, including when
closing proceeds and fees net to zero; numeric zero alone cannot release a reservation.

`capital-feasibility` uses the requested eight hypothetical capital tiers. Its default
$0.25 premium, multiplier 100 and $1 round-trip fee reserve are unvalidated assumptions.
The existing $15 absolute order-notional cap is retained: therefore this particular
$25 premium example remains denied even at higher tiers. `--premium 0.10` demonstrates
whole-unit feasibility at some tiers without raising any ceiling. The report is only a
necessary capital filter; Greek/scenario/liquidity/account/research/operational gates
remain unsatisfied. Annual operating cost defaults to an explicit hypothetical zero,
not a statement that operation is free; supply `--annual-operating-cost` to show drag.

## Configuration and compatibility

`configs/options/simulation.yaml` is an overlay for the existing canonical loader.
Base settings retain legacy modes for compatibility; this options overlay disables
standalone asset entries and cannot enable broker-connected or live options modes.
All new thresholds are in the required `options` subtree of base/release config.
Environment override names follow existing paths, for example
`TRADING_BOT__OPTIONS__MAX_PER_TRADE_LOSS_USD`; only tightening is accepted. The isolated
research CLI intentionally ignores ambient environment overrides and credentials.
No changed configuration reuses the old hash. Historical intent serialization is unchanged.

The new module entry point is temporary deliberate isolation from the pre-existing
unfinished `trader` CLI changes. It is not a second configuration loader or live service.
The main CLI integration is still pending.

## Saved synthetic inputs and reports

`export-options-fixture` saves the same fabricated engineering inputs, including supplied
trial history, as a closed `synthetic-options-replay-input-v1` JSON document. It is not a
vendor data importer. The document contains a canonical configuration hash, not config
overrides. Monetary values are canonical decimal strings, timestamps are UTC with six
fractional digits and `Z`, counts are integers, and unknown fields are denied. Config
changes require newly exported inputs; neither historical records nor old hashes change.

Create a private directory outside the repository, then export and replay:

```sh
options_artifacts=$(mktemp -d /private/tmp/options-research.XXXXXX)
PYTHONPATH=src uv run python -m trading_bot.cli.options_research export-options-fixture \
  --output-dir "$options_artifacts" --research-capital 2500 --scenario completed
# Substitute the document_hash printed by export; do not include angle brackets.
PYTHONPATH=src uv run python -m trading_bot.cli.options_research replay-file \
  "$options_artifacts/inputs/<document_hash>.json" --report-dir "$options_artifacts"
```

Use an absolute, non-symlink directory (`/private/tmp` on macOS; `/tmp` on Linux).
The root must already exist, be owned by the current user and have mode `0700`. Inputs
and reports are `0600`; subdirectories are `0700`. Symlinks, FIFOs, relative paths,
parent traversal, repository-local storage and public permissions are rejected. Identical
content-addressed writes are idempotent; differing existing bytes are never overwritten.
The implementation reuses the existing private bundle-storage primitives.

`replay-file` prints a `synthetic-options-replay-report-v1` envelope. Optional saved reports
go to `reports/<report_hash>.json`, including incomplete outcomes before exit code 2.
Without `--report-dir`, output is stdout only. The content hashes detect changes; they
are not signatures, vendor provenance, or proof that a supplied trial history is complete.
This format must never be used to reconstruct or authorize a live account's trial budget.

The canonical options settings `replay_max_bytes` (4,194,304), `replay_max_records` (5,000
total JSON array items) and `replay_max_json_depth` (16) are release ceilings, not market
limits. Files are size-bounded before reading/JSON decoding; nesting and duplicate keys,
numeric floats/nonfinite values and excessive array items are denied before domain
construction. Output is also size-bounded. Environment names follow the existing
`TRADING_BOT__OPTIONS__REPLAY_MAX_BYTES`, `...__REPLAY_MAX_RECORDS` and
`...__REPLAY_MAX_JSON_DEPTH` convention; the module CLI still ignores ambient overrides.
New required fields intentionally change the config identity; there is no silent upgrade.

## Known limits

This slice handles one synthetic long-call unit per episode. Spreads/condors have validated
identity records only, not validated payoff engines or execution. It does not yet support
historical/vendor data imports, bearish/put selection, partial complete-package quantities,
continuous/restarted episodes, real calendars, real fee schedules, dividends, exercise,
assignment, settlement calendars or broker intervention. Fixture bars deliberately are
fabricated daily observations, including non-market dates; they are not exchange history.

An episode is complete only when flat, orders terminal, and settlement/fees final. The
in-memory trial state retains all supplied prior episodes and sums their losses without
offsetting profits. Durable append-only persistence, event deduplication across restarts,
deposit/rolling tests and live reconciliation are separate unfinished milestones.

The simulator's risk/review transitions are explicitly simulated stages: they are not
full 24-check production pretrade passes, broker reviews, executable pricing or evidence
that any account is connected. Every result remains `ECONOMIC_NO_GO`.
