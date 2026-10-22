# Bounded inert stock configuration probe

This locally tested controller is not yet approved or installed on the intended host.
Whole-increment review, a source-specific full regression, native isolation/lifecycle
verification and trusted source/image provenance remain gates. The commands below are
an operator interface reference, not a record that a native probe has run.

The probe observes the image's default stock-research configuration using no application
mounts, credentials, network, ports or brokerage calls. It does not run stock acquisition,
qualify strategies, enable a worker, deploy the application or enable trading. A successful
probe is only one prerequisite for a later trusted release producer.

## Prerequisites and invocation

Use an independently reviewed immutable image ID already present on the selected Linux
host. The supported Engine profile is API1.52/Linux amd64, as checked by existing
verifiers. No image pull, tag resolution, build, Docker upgrade or fallback is performed.
Run only from the reviewed source checkout with its locked Python environment available.

The root-owned fixed namespace is `/var/lib/hybrid-stock-probes`, with exact0700
directories,0600 single-link files and permanent exclusive lock. An administrator must
explicitly initialize a new namespace with `initialize_probes()` from
`infra.hybrid.stock_probe_store`; the normal CLI never creates or repairs it. This
initialization and any native run require the later intended-host operational gate.
Do not initialize over an existing or partial namespace.

From that checkout, the sole CLI argument is the exact immutable image ID:

```sh
PYTHONPATH=src .venv/bin/python -m infra.hybrid.stock_probe_controller sha256:<64-lowercase-hex-digits>
```

The placeholder must be replaced with the independently verified ID. There are no
root, socket, user, deadline, mode, credential, retry or live-trading flags. Root peer
checks use only `/var/run/docker.sock`; no TCP endpoint, proxy or authenticated session
is available. No service or timer invokes this CLI automatically in this increment.

## Outcomes and retained evidence

Exit0 emits one JSON result with `kind=stock_probe_result`, owned probe/CID/image,
`status=succeeded` and canonical configuration. It is available only after original
setup/START deadlines, clean observed exit, complete finite valid logs, acknowledged
non-force removal, terminal durability, store closure and handler restoration.
The original configuration and framed bytes remain in the private namespace, bound
by immutable receipt hashes. Treat stdout as data, never as deployment authorization.

Exit2 emits a safe failed or recovery-only result without configuration. An unfinished
entry always consumes the invocation as cleanup-only; it never starts a replacement.
No-CREATE intent can be abandoned only when the complete history is valid. Uncertain
CREATE uses the generated name only to discover owned cleanup state; name404 cannot
resolve it. A retained START is never repeated and queued-created state is not STOP.

Exit1 emits only `{"status":"unavailable"}` to stderr. Ambiguous HTTP, torn/changed
artifacts, unknown ownership, persistence failure or missed caps can leave an incident.
Do not infer physical termination/removal from a response or failure reason. In particular,
a lost DELETE acknowledgement gets no same-invocation retry. A later explicit invocation
may resolve only an already-stopped/removal chain using exact full-CID404 and fresh
unchanged durability, then closes failed without configuration.

A signal during terminal success persistence can leave complete succeeded bytes while
publication is denied. Reopening never republishes those bytes. Any later new probe
requires fresh predecessor absence and a new acknowledged setup/dispatch chain.

## Timing, shutdown and incident handling

Setup20seconds begins before metadata reads. START has one original RUN30second cap.
Normal STOP must be acknowledged within RUN; output and entry into retirement must
occur before STOP+5seconds. Each retirement has one15second persistence-inclusive cap.
Every native exchange is at most5seconds and shortened by its current phase.

First shutdown or a failed/expired RUN starts cleanup at the earlier relevant origin.
TERM/KILL/final deadlines are origin+10/+15/+20seconds. Each signal requires a fresh
owned-running inspection; neither ACK proves STOP. Polls are spaced at least one second
without catch-up. Repeated signals cannot renew grace. Initially reopened/changed-domain
recovery has one bounded current-domain cleanup origin and retains the original START.
These caps cannot forcibly interrupt blocked kernel/filesystem work or guarantee daemon
scheduling; actual host performance remains unverified.

Keep the namespace, immutable artifacts and receipts after failure. Do not erase locks,
edit receipts, repair torn inventory, mark an incident closed manually, infer ownership
from a shortened CID or force-remove a resource through this controller. A trusted operator
must inspect actual host state when automatic evidence remains unresolved. Full history
is capped at128probes; exhaustion denies admission and requires a separately designed
retention procedure rather than automatic evidence deletion.

After native qualification, the remaining project work includes trusted release
production, paused research installation, deployed OAuth lifecycle, backups/restore,
scheduled24/7stock acquisition, qualified market data/stock strategies and nonempty
Robinhood reconciliation. Live investing remains separately user-controlled.
