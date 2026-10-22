# Stock release producer: prerequisite audit

This audit uses source `8629cad95d9d9bea1661f1fefc73d37741eebe5e`. It does not
implement a producer, prove a native build, approve deployment or activate research.
The product remains continuous individual-stock research, qualified selection and
risk-controlled investing after separate explicit live authorization.

The controller checkout remains frozen for its actual Task5 full regression. This
follow-on work reuses the completed stock dashboard/submissions checkout on branch
`codex/stock-release-producer`. Its prior5504be7 patch is already represented in the
controller branch; the original branch is preserved. The new checkout passed246
release/container/controller baseline checks in13.71seconds. It has no local virtual
environment; root reused the matching locked interpreter from the frozen runtime
checkout without installing or changing dependencies.

## Existing contracts

Use `Dockerfile`, not the dashboard-specific `Dockerfile.hybrid`. The stock image
contains source/config/migrations and the trusted `/run/trading-bot` directory.
The [container contract](stock-container-contract.md), canonical stock configuration,
existing release loader and unchanged worker risk/control boundaries remain binding.

Exactly four closed-schema artifacts belong under
`/opt/hybrid-stock-research/releases/<source-archive-sha256>`:

| File | Identity and dependency |
| --- | --- |
| `stock-compose.resolved.json` | Whole canonical resolved model, at most65,536bytes; immutable image and derived final attestation path |
| `stock-configuration.json` | Canonical image-observed configuration identity/bounds, at most4,096bytes; not the complete config graph |
| `runtime-image-attestation.json` | Existing five-key canonical image/config/Compose identity record, at most4,096bytes |
| `manifest.json` | Existing nine-key record binding archive/image/config/Compose/observation and observed run/cadence bounds, at most4,096bytes |

All files require mode0444, root ownership, single-link regular files, canonical
compact JSON plus newline, trusted ancestors and no symlink traversal. The public
loader fixes the production root and verifies consistency and post-read identities.
It does not establish archive contents, build history or fresh native execution.
Additional build/template/render-version/probe provenance cannot be inserted into
these four closed schemas without a separately reviewed version change.

## Provenance gaps

The fixed probe controller owns bounded metadata, CREATE/prestart/START, observation,
finite output, non-force removal and durable closure. Its public `run_probe(image_id)`
returns configuration only after the final original-cap/clock/shutdown gate. A future
producer must invoke that fixed operation itself; supplied CLI JSON, a supplied
`ProbeResult` or reopening successful receipts cannot substitute for a fresh call.
The producer needs its own bounded publication contract; extending the controller's
original completion cap would weaken the reviewed boundary.

No current component links exact source-archive bytes causally to an immutable image
ID. Accepting independent caller-supplied hash/image values would create an assembler,
not trusted production. The initial implementation must either own the supported
build operation or consume a separately established trusted build receipt. The latter
cannot be invented merely to make the file verifier pass.

The existing dashboard `prepare.py` creates an archive after an npm build. It neither
builds the stock image nor supplies that missing relationship and should not be
repurposed for a stock-only release without a coherent reviewed change.

## Decisions before implementation

Freeze the build path against official Docker/Moby behavior, including base-image
resolution, registry/credential access, final image identity and ambiguous or timed-out
builds. A client timeout must not be treated as daemon termination. Keep all native
operations outside this audit.

Then specify separate build/probe/renderer provenance, exclusive publication locking,
bounded original inputs, nonreplacement and partial-write handling. Derive all four
artifacts from actual owned operations, publish durably, and pass the resulting
manifest through the existing loader before reporting a usable release.

Acceptance must compose the actual producer/controller/loader seams and cover missing
or mismatched build provenance, supplied/replayed probe results, poisoned rendering
environment, policy drift, failed/recovery-only probes, competing publishers, namespace
replacement and write/fsync/close failures. Native image/isolation/lifecycle proof,
paused installation, OAuth lifecycle, backups/restore and scheduled acquisition remain
later operational gates. Data, strategy and nonempty broker reconciliation remain
independent gates; no test or release promotes live trading.
