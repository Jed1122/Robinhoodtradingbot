# Options observation, reconciliation and expiry monitoring

Development-only continuation from `690a591`. No broker connection, order access,
credentials, paid data acquisition, deployment or production migration is part of
this implementation. Technical observation integrity is not economic validation.

## Implemented boundary

`domain/options_account.py` contains immutable normalized observations for cash,
option positions, order legs, orders, fills, shares, settlement obligations and
lifecycle events. Explicit section-completeness claims preserve the distinction
between an empty result and unavailable/truncated data. These are **not** Robinhood
response parsers. A provider adapter must independently establish mapping, account
scope, complete pagination and a common history window before constructing them.

`reconciliation/options.py` reuses the existing reconciliation result and keyed
comparison machinery. It compares every cash component, contract identity, position,
order, fill (including price and fees), share, settlement and lifecycle row exactly.
It additionally rejects stale/future/partial observations, unknown order outcomes,
missing contracts, inconsistent fill totals, unknown or ambiguous ownership,
unexpected shares, negative cash, pending lifecycle processing and overdue settlement.
Matching two incorrect books is not enough: complete structure ownership and
per-leg fill totals are checked independently. Duplicate identities fail closed.
Settlement sums use exact bounded Decimal arithmetic independently of ambient precision.

This is a comparison/incident subsystem, not full ledger reconstruction or risk
admission. It does not derive cash equity from all lifetime flows, establish fees or
rights from source claims, reconstruct reservations, or certify executable liquidation
marks. Broker marks are compared only as broker marks; a missing mark on a held option
is an incident. No implied trade eligibility is attached to a clean result.

`lifecycle/options_expiry.py` requires an explicit complete, point-in-time calendar
range. A contract's partial fixture list is not a calendar. For physically settled
exposure, the default exit deadline is the preceding eligible session's close before
the contract's last trading session; a strategy may shorten but not extend it. Early
closes and non-trading dates come from supplied sessions, not weekday arithmetic.
The exit session produces a warning; reaching the deadline produces an incident.
Cash-settlement policy is unverified and fails closed. Calendar completeness here is
a validated assertion, not independent proof that an exchange supplied every session.

This conservative policy does not assume guaranteed broker intervention. Robinhood
describes closeouts and other expiration actions as conditional; assignment and
stock-delivery liabilities can remain. [Official expiration, exercise and assignment
reference](https://robinhood.com/us/en/support/articles/expiration-exercise-and-assignment/)
(checked 2026-09-18). No automatic exercise, DNE, share remediation or fictional
end-of-input liquidation is implemented.

## Paused continuous observer

`runtime/options_monitor.py` supplies `PausedOptionsMonitor` with an injected read-only
observation source, existing reconciliation store, alert sink and UTC clock. It validates
the existing canonical configuration and release envelope; only offline options modes
are accepted. No new configuration graph or production adapter is introduced.

- `cycle()` performs a bounded read, comparison, expiry assessment and durable result
  write. Provider and storage failures expose fixed reason codes, not raw exceptions.
- `run(stop_event)` repeats using the existing configured equity reconciliation cadence;
  the options-underlying monitor does not start equity strategies. Each instance uses
  the existing scheduler's overlap guard. This is not a distributed execution lock.
- `status()` ages the original source observations, not the most recent poll time.
  Stale data, backward clocks and alert failures cannot show clean monitoring status.
  Clock regression is measured against the instance's high-water timestamp and remains
  latched for that instance; merely catching up cannot clear it. A rollback detected
  after persistence appends an incident rather than overwriting the prior result.
- Every status is permanently paused, entry-disabled and live-unsupported. Construction
  after restart requires a fresh observation; no saved clean result resumes trading.
- Existing `SqlReconciliationStore` records results append-only. A versioned content hash
  of both normalized snapshots, ownership and calendars is embedded in the reconciliation
  ID. The source artifacts must still be retained by the caller; this is not a new raw
  snapshot archive or complete recovery format. Legacy evidence/schema is unchanged.

No running process was installed. There is no new user-facing activation command.
The API is verified with credential-free fake sources and a real temporary SQLite
database, including restart and append-only enforcement. Tests never read the private
Databento key or call broker tools.

Run the narrow verification from the repository using its verified development Python:

```sh
PYTHONPATH=src python -m pytest tests/unit/reconciliation/test_options_reconciliation.py tests/unit/lifecycle/test_options_expiry.py tests/unit/runtime/test_options_monitor.py tests/integration/persistence/test_options_monitor_store.py tests/smoke/test_critical_branch_coverage.py -q
```

The critical-coverage checker includes these new domain, reconciliation and runtime
modules plus all lifecycle modules at the existing 90% per-file branch threshold.

## Remaining work, separated from external blockers

Engineering still includes complete risk admission (loss latches, stress/Greek limits,
liquidation valuation and reservation composition), normalized lifecycle/settlement
ledger recovery, source artifact backup, official broker response parsing and locked
execution integration, production scheduler/health/heartbeat composition and operator
commands. No claim that only operator permission remains is justified.

Economic evidence still needs licensed point-in-time real data, a preregistered
research protocol, untouched testing, dependent-outcome uncertainty and after-cost
scorecards. Synthetic tests cannot satisfy this requirement. See the
[data acquisition next steps](databento-acquisition-next-steps.md).
