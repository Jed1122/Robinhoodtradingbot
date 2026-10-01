# Focused ETF study registration

The first implemented part of the approved ETF plan is an offline configuration
and immutable-record contract, not a historical runner or an accepted strategy.
No new CLI command, acquisition adapter, broker capability or runtime is added.

`equity_strategies.etf_pilot` belongs to the existing canonical configuration and
release envelope. All values must be present in YAML. The base profile is disabled;
the release envelope permits only the fixed offline profile. Enabling it is valid
only in paused backtest/simulation mode, with live disabled and options inactive.
Its `execution_enabled` and `evidence_promotable` fields cannot be true.

For offline callers, the documented environment mapping is
`TRADING_BOT__EQUITY_STRATEGIES__ETF_PILOT__ENABLED=true`. This is not a service or
trading activation command. Other leaves use the same canonical nested mapping;
fixed policy values cannot be changed to make a study succeed.

`freeze_etf_study` binds the complete validated config/envelope preimage and hash,
code identity, source/cost plan identities, fixed 2016–2025 window, 2024–2025 final
holdout, seed and prior holdout-access declaration. Its version is `etf-study-v1`.
Hashes identify content; they do not prove a provider license or data authenticity.
The record preserves the $100 risk reference and hypothetical $500/$1,000 cash tiers.
The four-ETF candidate universe remains separate; adding the new profile correctly
changes the current full config hash and invalidates old authorization identities.
Historical fixture identities retain their original schema/policy and expected hashes.

`EtfCostInterval` requires exact bounded Decimal values, UTC validity/knowledge
times, source identity and role-specific units. `EtfCostEvidence` rejects missing
roles and overlapping schedules. Spread is already part of fill prices; the extra
slippage role must not duplicate it. Zero is acceptable only as an explicit value,
never as the default for missing evidence. `recorded` is a provenance declaration,
not qualification; calibration remains unverified and both capability flags false.
Coverage, original/revision visibility, effective-date fee rules and calibration
still need the later source/cost loaders and evaluators.

## Local verification — 2026-09-30

The current main suite passed 6,276 tests with 33 optional-dependency skips on
each of Python 3.12, 3.13 and 3.14. A native research run passed 70 cases, including
the options historical-episode cases and ETF contracts. Python 3.14's combined
branch-inclusive coverage was 88.62%; the existing 90% critical-module branch
gate passed. Ruff, Mypy (284 source files), Bandit and both frozen-lock checks
passed. These are local dirty-worktree results, not clean hosted CI or economics.

Independent review found that direct record reconstruction could contradict
the canonical configuration. Its reproductions failed before the fix. Both the
factory and record boundary now require and revalidate the canonical policy;
the configuration preimage, seed and risk reference cannot be replaced by an
inconsistent record. Python-version-specific missing-InitVar exception types
are accepted in tests without weakening the required rejection.

The profile changes the current canonical hash, as required for new policy.
Historical expected hashes remain unchanged. No source qualification, economic
calibration, historical runner, restart store or ETF CLI is claimed by this step.

Next: qualify the selected provider and implement source ingestion, then causal
risk/lifecycle replay, durable restart, benchmarks/uncertainty and offline commands.
Actual data and accepted economics remain prerequisites for qualifying paper/shadow
work, and live authorization remains independent. No profit or launch date is implied.
