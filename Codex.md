# Codex implementation rules

## Current repository boundary

Only the paper-safe, fail-closed foundation is implemented: domain and configuration
primitives, capability evidence and sanitized schema capture, broker protocols, and safe
structured logging, plus the Alembic-owned async SQLite ledger schema. Persistence
now includes an explicit single-use unit of work, lossless order-intent writes,
secret-screened audit appends, and database-enforced append-only guards for the seven
critical correction tables. A broker-neutral pure order state machine validates lifecycle
events, keeps terminal states closed, and requires explicit reconciliation after detected
active-order drift. Pure sizing and projected-exposure checks use factory-bound canonical
config and instrument inputs, the lesser current/authorized risk-equity reference, and
downward Decimal quantization. Other workflow repositories and runtime composition are not
implemented.
Trading MCP is not configured. Prediction live execution is unsupported.
No live order has been placed. This code makes no profitability claim.

Trader CLI is not implemented. Broker adapters are not implemented.
Account access is not implemented. Do not represent planned modules, modes, commands, cloud resources,
elapsed evidence, authentication, review, or execution as completed.

## Safety rules

- Keep the default paused and unable to submit.
- Do not add a provider implementation from public prose or a schema declaration alone.
- Do not authenticate, inspect an account, review or submit an order, provision
  infrastructure, or contact an external service without separate explicit authority.
- Keep provider transports out of broker-neutral domain, strategy, risk, and portfolio
  logic.
- Keep read, review, place, and cancel-only capabilities independently injectable.
- Never put credential material, authorization headers, signatures, private keys,
  account identifiers, or provider payloads in logs, fixtures, errors, reports, or Git.
- Redact structured event data before JSON serialization and fail closed on unknown
  objects or redaction errors.
- Install logging limits only from the canonical validated config graph. Sanitize stdlib
  formatting inputs and exception arguments before interpolation, normalize existing
  handlers and filters to the single redacting sink, replace raw record-factory and
  last-resort paths, suppress formatting-error diagnostics, and apply the configured
  event-size bound only after redaction.
- Configure logging in the single-threaded entry point before importing modules that
  materialize or bind Structlog loggers and before starting workers. Treat pre-bound or
  custom-processor Structlog objects as unsupported trusted pre-bootstrap code.
- Preserve the capability matrix distinction between implemented, documented, locked,
  externally pending, and unsupported.
- Keep tests deterministic, local, and selected by the default non-authenticated Pytest
  configuration.

## Baseline verification

Use the narrowest relevant test first, then run `make lint`, `make typecheck`, and
`make test`. `make security` includes a dependency audit that may require package-index
access; do not silently skip or weaken its recipe. Record any externally blocked step
explicitly.
