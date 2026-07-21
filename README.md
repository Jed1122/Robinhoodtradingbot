# Robinhood multi-asset system

This repository currently implements a paper-safe, fail-closed foundation: canonical
domain records, one strict configuration graph, capability evidence and sanitized
schema-capture primitives, broker protocols, and pre-serialization structured-log
redaction. A pure, immutable-table order state machine now rejects invalid lifecycle
events and routes detected drift on known active orders through explicit reconciliation.
Pure position sizing now resolves thresholds only from canonical config and instrument
metadata, caps risk against the lesser of reconciled and authorized equity, rounds exposure
downward, applies mode-specific absolute order limits, and evaluates projected exposure
without gain-based cap auto-scaling. Pure loss, drawdown, consecutive-loss pause, and
activity gates now enforce canonical mode settings and deterministic UTC windows. Drawdown
requests kill-switch activation without liquidation, while daily/weekly/pause entry blocks
preserve only eligible exit intents. Loss evidence is account-bound and activity evidence is
account-and-instrument-bound. A broker-neutral pretrade engine now evaluates one shared,
ordered checklist: the preliminary pass records 23 checks and the post-review pass records
all 24 without short-circuiting. It captures one injected UTC clock value per evaluation,
binds costs and exposure projections to exact evidence identities, and explicitly denies
missing, stale, mismatched, or unsafe evidence. Non-live modes waive only the live-lease
requirement; matching config, code, research, and alert evidence remain mandatory. The
execution package now also provides an exact review-only wrapper, deterministic internal
SHA-256 submission keys, and non-waiting per-account exclusion for single-process fake and
simulation brokers. Its broker-neutral `ExecutionService` durably records the proposed intent,
the 23-check preliminary decision, the exact broker review, and a fresh 24-check final decision.
Under the account exclusion, an allowed non-live attempt atomically records its unique pending
reservation before calling the injected placement capability exactly once, then records an
accepted, rejected, or ambiguous outcome before releasing the exclusion. Transport errors,
response mismatches, and broker states that are not an exact acceptance or rejection remain
ambiguous for later reconciliation. The in-process exclusion is explicitly not a live-host
mutex. A persisted reviewed order distinguishes non-live provenance (fencing token zero and no
lease claim) from live provenance (a positive fencing token and complete lease identity and
evidence), and this service rejects both live modes at construction until the later authorization
and leadership layers exist. A separate equity-only Robinhood Trading MCP adapter can perform
the seven reviewed read operations through an encrypted OAuth store. Its connected-shadow
composition has no review, place, or cancel adapter: an SDK-session allowlist and a second
transport allowlist independently reject every tool outside those seven reads. This is a local
software boundary, not a broker permission boundary. The OAuth flow requests and pins Robinhood's
sole official `internal` scope, whose bearer credential must be treated as trading-capable. A
stolen credential or compromised host could trade in the Agentic account outside this client.
The probe writes append-only, identity-bound promotion evidence to the ledger. The repository also
includes an Alembic-owned SQLite
WAL ledger foundation with canonical Decimal and UTC storage, no-affinity safety-scalar
checks, and database-bound provenance across authorization and economic-effect records. It
does not yet implement a live trading application. A single-use async unit of work currently
supports lossless order-intent, risk-evaluation, review, lifecycle-transition, submission-attempt,
broker-order, and secret-screened audit writes. Repository commands for fills, data quality,
authorization, reconciliation, and evidence workflows remain deliberately absent until their
complete domain records exist.

## Current safety status

- The default remains paused and cannot construct a live submission path.
- Authenticated, value-free equity MCP response-shape evidence has been captured for the reviewed
  read surface. Runtime OAuth state is never committed to the repository and must be bootstrapped
  explicitly by the operator.
- Prediction live execution is unsupported.
- No live order has been placed by this implementation or its tests.
- Offline `backtest`, `simulate`, and one-cycle `paper` CLI commands are implemented with
  deterministic hashes and no live placement capability.
- Official Crypto v2 read DTOs, exact signing, and read adapters are implemented against
  reviewed schema fixtures and mock HTTP; no authenticated account read is claimed.
- The connected client invokes equity reads only because of two local allowlists and the absence of
  review, placement, and cancellation adapters. The broker token itself is not read-only. Nonempty
  position and order collections remain locked until their authenticated shapes are observed and
  reviewed.
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

## Offline research modes

Run `make backtest`, `make simulate`, or `make paper`. These commands validate the selected
configuration against the immutable safety envelope and emit a canonical mode, seed,
configuration hash, and result hash. See [strategy research](docs/strategy-research.md) and
[limitations](docs/limitations.md). No result is a profitability claim.

## Robinhood read and shadow setup

Bootstrap the standalone runtime against the official Trading MCP endpoint from a trusted
workstation. The command requests and pins the sole official OAuth scope, `internal`. That scope is
not a broker-enforced read-only grant; treat the bearer credential as trading-capable. The bootstrap
parent must already be a service-owned directory with mode `0700` or stricter, and the `oauth`
destination must not exist. The command stages encrypted OAuth state and the SHA-256 account
fingerprint together, then atomically commits the complete directory:

```shell
umask 077
mkdir -p "$HOME/.local/share/robinhood-trading-bot"
chmod 700 "$HOME/.local/share/robinhood-trading-bot"
test ! -e "$HOME/.local/share/robinhood-trading-bot/oauth"
PYTHONPATH=src uv run trader mcp-oauth-bootstrap \
  --oauth-store "$HOME/.local/share/robinhood-trading-bot/oauth" \
  --account-fingerprint-file \
    "$HOME/.local/share/robinhood-trading-bot/oauth/account-fingerprint"

mkdir -p "$HOME/.local/share/robinhood-trading-bot/evidence"
chmod 700 "$HOME/.local/share/robinhood-trading-bot/evidence"
```

Then run one write-incapable connected probe with an immutable local image digest:

```shell
TRADING_BOT_IMAGE_DIGEST=sha256:<64-lowercase-hex-image-id> \
PYTHONPATH=src uv run trader shadow \
  --config configs/shadow.yaml \
  --once \
  --oauth-store "$HOME/.local/share/robinhood-trading-bot/oauth" \
  --account-fingerprint-file \
    "$HOME/.local/share/robinhood-trading-bot/oauth/account-fingerprint" \
  --ledger "$HOME/.local/share/robinhood-trading-bot/evidence/ledger.db"

make shadow-smoke
make live-readiness
```

Crypto v2 reads use only `ROBINHOOD_CRYPTO_API_KEY_FILE` and
`ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE`; each referenced service-owned file must be mode `0600`.
Raw credential environment variables are rejected. The OAuth directory must be service-owned mode
`0700`; its encrypted files and its `account-fingerprint` file must be mode `0600`. Treat the entire
directory as a trading credential: stealing the token or compromising a host that can read it may
permit trades in the Agentic account. The probe emits only sanitized hashes and status.
`make shadow-smoke` uses sanitized local evidence and is never promotable. The connected probe is
also deliberately non-promotable today: it verifies locally constrained read connectivity and
zero-state reconciliation but does not fabricate an accepted strategy attestation, complete trading
outcomes, or elapsed shadow history.

Promotion progress is derived only from append-only observations matching the exact account,
provider declaration, strategy, configuration, and image-code identity. The configured minimums
are 100 eligible paper cycles, seven distinct UTC shadow dates, and—before normal live—100 combined
eligible observations across 30 distinct UTC dates including micro-live evidence and a separate
current micro-order review summary that proves every configured ten-order boundary was reviewed,
plus current security, acknowledgement, runtime-control, slippage, and drawdown attestations. A
code, config, strategy, provider, or account identity change starts a different evidence series.
These thresholds are prerequisites, not permission to trade.
Normal-live evaluation retains the paper and shadow prerequisites; normal-live observations do not
add progress, and their latest dirty state blocks re-promotion.

## What comes later

Provider-connected order review, submission, and cancellation, complete strategy scheduling, and
every opt-in live gate remain locked. The default deployable service is a health-visible paused
process with no host volumes or credential access and deliberately reports `/readyz` as unavailable.
An explicit `connected-shadow` Compose profile runs one authenticated, locally write-incapable probe
with no published port and then exits.
The broker-neutral execution service accepts only injected capabilities; current adapter evidence
does not grant permission to trade.

The executable plans live under `docs/superpowers/plans/`. Later slices may not bypass a
failed foundation or capability gate.

## Operations and deployment

See the [operations runbook](docs/operations-runbook.md), [live activation](docs/live-activation.md),
[risk policy](docs/risk-policy.md), [incident response](docs/incident-response.md), and
[disaster recovery](docs/disaster-recovery.md). Containers and cloud deployment always start
paused, expose administration only through host loopback, and never activate live trading. A
successful default paused deployment has a healthy `/healthz`, a `503` `/readyz`, and the metric
`trading_bot_live_enabled 0.0`. The default service has no host volumes and cannot access OAuth or
evidence state. The connected-shadow profile is explicit and locally write-incapable; its evidence
ledger does not by itself authorize or activate live execution.
