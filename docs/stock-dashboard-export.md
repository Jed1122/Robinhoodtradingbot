# Stock research dashboard export

The individual-stock worker can publish a bounded, sanitized research projection for
the authenticated hybrid dashboard. The dashboard opens only that projection. It
receives no research ledger, raw archive, brokerage credential or provider session.
This local integration is implemented and tested; it has not been deployed as a
scheduled service.

## Data and freshness contract

`StockDashboardExport` is a strict version-1 document. It contains the canonical
stock configuration and code identities, verified ledger state digest, recorded
worker status and call reservations, source report/manifest digests, original source
timestamps, up to 20 research priorities and up to 20 company evidence-gap lists.
Only six numerical screening factors are allowed: return on equity, net margin,
annual earnings growth, quarterly revenue growth, earnings yield and free-cash-flow
yield. Exact values are finite, bounded decimal strings; absent values stay unknown.
There is no provider prose, account identifier, instrument identifier or raw payload.
Registered secrets are checked before publication and again before presentation.
Qualification, investment eligibility and live-enabled flags must all be exactly false.

The exporter holds the raw archive lease, reads the durable job state, and rehashes
and recomputes both available cache heads against the current code/configuration.
An inconsistent or tampered source blocks export. Export failure does not rewrite
an already committed acquisition outcome or refund its reserved calls.

The export timestamp is the ledger read's own UTC observation time. This binds its
daily budget to the same UTC day even if serialization crosses midnight. The API
rejects a future export, an export older than the canonical stock source-age limit,
or a budget from a previous UTC day. Unavailable budget figures are null, not zero.
Discovery and company evidence also retain their original claim/source ages: writing
a new projection cannot make an old opportunity fresh. Stale opportunities disappear;
a stale-source label does not replace the worker's actual failure reason.

Call reservations describe charged plans, not confirmed provider calls. Pending claims
describe unresolved records, not proof of a running process. A successful recorded
cycle does not establish continuous operation or an investment advantage.

## Private filesystem boundary

Select an existing, canonical, owned mode-0700 export directory outside the checkout,
distinct from the raw archive. The publisher accepts only its recognized bounded
inventory, serializes cooperating publishers with a stable private lock, and publishes
`stock-research.json` using an exclusive mode-0600 temporary file, file fsync, atomic
replacement, directory fsync and canonical readback. Unknown files, unsafe metadata,
symlinks, hardlinks, excessive size or inventory, and path substitutions fail closed.
It does not repair permissions or delete orphans automatically.

The reader requires a private, owned, single-link regular file of at most 256 KiB.
It performs no SQLite operation, network request, broker call, refresh or directory
creation. It checks canonical encoding and the configured stock policy hash on every
read. Missing or invalid exports produce a sanitized unavailable research view.
These are cooperating same-host filesystem protections, not protection against a
compromised owner or root. Actual container UID and read-only mount compatibility
still require deployment verification.

## Explicit local composition

Append the export option to the existing one-shot worker invocation:

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.stock_research_worker \
  --config-root configs \
  --database /absolute/private/state/ledger.sqlite3 \
  --oauth-store /absolute/private/oauth-stock-research \
  --archive-dir /absolute/private/archive \
  --control-dir /absolute/private/stock-controls \
  --export-dir /absolute/private/dashboard-export
```

To recompute and publish only the verified cache projection, add `--export-only`.
That path creates no claim, SDK or credential connection and makes no provider call.
The current CLI still syntactically requires `--oauth-store`; export-only does not
open it. The existing ledger and clean-Git or verified deployed-image identity gates
still apply. A failed export returns exit 2 and reports its status separately from a
committed acquisition result.

Add `--stock-export-dir /absolute/private/dashboard-export` to the existing
`trading_bot.hybrid.cli serve` invocation. `compose.hybrid.yml` supplies the fixed
`--stock-export-dir /stock-exports` argument and mounts only the collector's
`/var/lib/hybrid-stock-research/exports` directory there read-only. It never mounts the
stock parent, raw archive, ledger, controls or OAuth store. Both services use UID/GID
10001, preserving the owned 0700 directory and 0600 projection contract. The dedicated
export directory must already exist; Compose cannot create it. Its actual native
mount and ownership remain deployment-verification requirements.

The opt-in reader uses the same canonical stock policy. Without the CLI option,
existing dashboard behavior remains unchanged. Feed reads
occur only after API authentication; health/readiness do not inspect the feed.
The projection appears in both snapshot and control responses, without changing
portfolio state, trade authorization or live readiness.

## Controls and verification

The dashboard displays stock priorities, original timestamps, factors, missing
company evidence and recorded collector status on desktop and mobile. The existing
Pause/Resume/Kill controls still govern the hybrid portfolio journal. Labels and
notices explicitly say they do not control the separate collector. Authoritative
collector's own [CLI admission controls](stock-research-controls.md) are implemented
locally; their fixed path and deployed behavior must be verified before scheduling.

Central local verification passed 417 tests with 93.63% combined branch coverage over
the dashboard DTO/export, API, worker and research job store, plus 57 frontend tests
and a production frontend build. Independent backend and UI reviews cleared the
bounded change. A rendered desktop/mobile check used fictional data through the
actual private publisher, file reader, authenticated API and built dashboard; it
observed no browser errors, warnings, external requests, storage use or page overflow.
It made no provider or credential calls. These checks do not establish deployed
mounts, scheduled acquisition, market-data qualification or live readiness.

Next: integrated collector-control verification, immutable executing-image/configuration proof, supervised
completion-relative scheduling, encrypted backup/restore and freshness alerts. Stock
point-in-time datasets, out-of-sample strategy/cost/tax evidence and nonempty broker
reconciliation remain separate requirements before live authorization.
