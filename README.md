# Robinhood multi-asset system

This repository currently implements a paper-safe, fail-closed foundation: canonical
domain records, one strict configuration graph, capability evidence and sanitized
schema-capture primitives, broker protocols, and pre-serialization structured-log
redaction. A pure, immutable-table order state machine now rejects invalid lifecycle
events and routes detected drift on known active orders through explicit reconciliation.
Pure position sizing now resolves thresholds only from canonical config and instrument
metadata, caps risk against the lesser of reconciled and authorized equity, rounds exposure
downward, applies mode-specific absolute order limits, and evaluates projected exposure
without gain-based cap auto-scaling. The repository also includes an Alembic-owned SQLite
WAL ledger foundation with canonical Decimal and UTC storage, no-affinity safety-scalar
checks, and database-bound provenance across authorization and economic-effect records. It
does not yet implement a trading application. A single-use async unit of work currently
supports lossless order-intent and secret-screened audit writes; repository commands for
later execution, fills, data quality, authorization, reconciliation, and evidence workflows
remain deliberately absent until their complete domain records exist.

## Current safety status

- The default remains paused and cannot submit an order.
- Trading MCP is not configured. The committed capability baseline comes only from
  official public documentation; it is not schema or authenticated evidence.
- Prediction live execution is unsupported.
- No live order has been placed by this implementation or its tests.
- Trader CLI is not implemented, even though packaging reserves its future entry point.
- Broker adapters are not implemented.
- Account access is not implemented.
- This repository makes no profitability claim.

The [capability matrix](docs/capability-matrix.md) keeps five states distinct:
implemented local foundations, publicly documented operations, operations locked while
external evidence is pending, externally pending verification, and explicitly unsupported
operations. A documented operation is not an implemented or usable operation.

Structured logging also fails closed: future application bootstrap must install the
canonical validated `logging.max_event_bytes` setting before configuring a logger. The release
safety envelope caps that value, and oversized events are replaced only after recursive
secret redaction and before the final JSON renderer. Stdlib formatting arguments,
exceptions, filters, record factories, and last-resort output are also normalized behind
the fail-closed sink. Bootstrap must finish this configuration in the single-threaded
entry point before importing any module that materializes or binds a Structlog logger and
before starting workers; pre-bound Structlog objects are unsupported trusted pre-bootstrap
code because Structlog does not expose a registry through which they can be revoked.

## Local foundation checks

Python 3.12, 3.13, or 3.14 and `uv` 0.11.28 are required. These commands exercise local
code only; they do not configure or contact an account or a trading endpoint.

The ledger requires SQLite 3.31 or newer for stored generated identity columns. Exact
Decimal, Boolean, and safety-counter columns deliberately declare SQLite `BLOB` affinity
while storing runtime `TEXT` or `INTEGER` values; this prevents SQLite from silently
coercing raw numeric input before the database checks execute.

Every application connection also verifies recursive-trigger enforcement. Database triggers
make audit events, order transitions, risk evaluations, configuration versions, live
authorizations, kill-switch events, and reconciliation events insert-only. Corrections append
a distinct row referencing an existing original; updates, deletes, self/missing corrections,
and SQLite replace/upsert mutation paths fail closed and roll back the transaction.

```shell
uv sync --all-groups
make lint
make typecheck
make test
```

`make format` updates formatting. `make security` runs Bandit and the locked dependency
audit. Do not place credential values in environment variables, fixtures, logs, command
arguments, or committed files; the safe template contains file references only.

## What comes later

Broker adapters, authenticated reads, market-data providers, strategies, portfolio target
construction and the remaining risk gates, the remaining workflow-specific persistence
commands, simulation and paper runners, review and order-submission services, reconciliation
services, operator controls, deployment, and every opt-in live gate remain future work. Their
presence in the implementation plans is not evidence that they exist.

The executable plans live under `docs/superpowers/plans/`. Later slices may not bypass a
failed foundation or capability gate.
