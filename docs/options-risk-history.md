# Offline options loss-history rehearsal

This is engineering validation, not genuine economic evidence or a live operator.
No broker, account, credential, network, existing ledger, deployment or purchase is used.
The canonical simulation configuration and release envelope remain authoritative.

Run from the repository root:

```sh
uv run python -m trading_bot.cli.options_risk_history demo
uv run python -m trading_bot.cli.options_risk_history replay-file /private/path/risk.json
```

Both commands use a newly created private temporary SQLite database, migrate only that
database, append observations under execution leases, close the engine, and reconstruct
the same report through a new engine. Temporary files are removed afterward. They do
not store ongoing operational state or update any pre-existing account database.
Reports mask account identity and explicitly keep entries and production eligibility false.

Exit 0 means the rehearsal completed, including when a loss limit is latched. Exit 2
means reconstruction completed with incomplete/stale/out-of-session evidence. Exit 1
means invalid input or a storage/reconstruction failure; the generic error deliberately
does not echo input, paths or exception contents. No exit status authorizes trading.

## Loss and reset semantics

- Adjusted equity is declared liquidation equity minus cumulative external deposits
  net of withdrawals. Funding cannot erase an observed loss or increase the initial
  risk-equity ceiling. Exact Decimal arithmetic is independent of ambient precision.
- Daily and weekly losses use their declared opening/previous-close basis. New sessions
  require the preceding session's exact close observation; missing closes latch an
  incomplete-history reason instead of inventing a reset. Overnight losses count.
- Daily halts persist through same-session recovery. Weekly and drawdown halts never
  automatically clear on new dates, recovery or restart. There is no manual-clear API.
- Drawdown uses the flow-adjusted high-water mark. Zero limits mean zero budget.
  Negative equity and losses beyond starting cash remain visible.
- Incomplete observations permanently mark this history incomplete. Subsequent complete
  observations cannot authenticate earlier gaps. Derived numbers are conditional fixture
  calculations, not assurance of their accuracy.
- Session calendars, marks, external flows and their completeness are declared synthetic
  inputs. A source hash binds identity, not authenticity. Full pretrade checks, consecutive
  loss controls, Greek limits and the separate non-replenishing trial budget are not
  replaced by this observer.

## Durable library and closed input

`OptionsRiskJournal` uses additive migration `0007_options_risk_history`. It binds each
versioned point to account, config, source hash, sequence, fencing token and prior hash.
Expected-head comparison prevents lost updates. Exact tip retries are idempotent;
changed identity/content, stale leaders, clock regression and altered history fail closed.
Lease validity is checked after lock acquisition and again before commit. SQL triggers
reject update/delete/replacement and downgrade refuses nonempty history.

The separate synthetic `OptionsTrialJournal` now applies the same lease chronology
checks, including acquisition/heartbeat time, time spent waiting for SQLite, history
reads, and the pre-commit boundary. An exact duplicate may return only the current
journal tip; an explicitly supplied retry head must be that tip or its predecessor.
Replaying an older event after intervening history fails, even when supplied with the
latest head. The v1 event encoding and existing hashes are unchanged; no migration or
reservation-policy change is required. This is recovery hardening, not a broker adapter.

Only a future separately reviewed composition may use this library outside synthetic
rehearsals. It does not establish production state migration or deployment readiness.
History bounds fail closed; there is no truncation or rolling-window loss forgiveness.

File inputs must be regular owner-private files under an owner-private directory outside
the repository; symlinks and broad permissions are rejected. They have a 1 MiB byte limit
and at most 1,000 observations, also subject to canonical replay bounds. The closed root
schema is `options-risk-rehearsal-v1` with exactly `schema`, `source_kind` (`synthetic`),
`as_of` (canonical UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`) and `points`. Each point is the closed versioned JSON object
produced by `persistence.options_risk.encode_point(OptionsLossPoint(...))`. Decimal
fields are strings, all timestamps UTC, and no document-provided configuration is loaded.

## Still required for live readiness

Real point-in-time option and underlying prices, approved research design and out-of-sample
economic testing remain missing. Imported Databento contract definitions alone cannot
provide price-based returns. Authenticated broker/runtime capability evidence, full
production lifecycle integration and operational drills also remain separate work.
No subscription, new data download, deployment or live order is authorized by this tool.
