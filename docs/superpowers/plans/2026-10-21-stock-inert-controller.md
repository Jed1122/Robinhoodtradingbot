# Bounded inert stock configuration controller implementation

Root inline implementation from `0af76874d8b57356b840ce96c29e52d5c2883c2f` on isolated
`codex/stock-inert-probe-controller`. Spec: [controller contract](../../stock-inert-controller-design.md).
No native mutation, deployment, image build/pull, credential/provider/account/order,
control change or live activation is performed during these local tasks.

Prior probe-profile branch remains frozen at 0af7687; source there is independently
reviewed 68ed801. Primary f05dbe8 full35732 completed exit0:13008passed/33optional skips/89.04%coverage.
Root fast-forwarded the accepted frozen prior branch0af7687 and started one new full
(session4761, /tmp/stock-operations-full-suite-0af7687.log). Do not mutate that frozen
primary revision or start a duplicate full while this isolated controller continues.
This plan's final integrated source requires its own later full before readiness.

## Task 1: Pure probe ownership/lifecycle observations

Add `infra/hybrid/stock_probe_observation.py` and fictional deployment tests. Define
frozen copied ProbeObservation fields for probe ID/full CID/image, status, PID, exit,
OOM/error presence and native lifetime. Public `observe_probe(raw, *, probe_id,
container_id, image_digest)` performs no native operation or mutation.

Write RED for fixed probe name/labels/image/CID, exact scalar/state types, platform,
restart/auto-remove, all accepted created/running/exited/dead states, unknown/paused/
restarting states, malformed/nonfinite JSON and contradictory timestamps/PID. Include
the important distinction: full prestart hardening drift denies START while minimal
owned stopped observation can support cleanup. A copied result grants no authority.

Implement minimal fixed ownership/state validation; reuse pure bounded JSON, scalar
and timestamp helpers only. Do not manufacture a worker Attempt or StockRelease.
Run new observation, existing strict probe/profile/prestart and worker lifecycle tests.
Expected: actual data-only behavior and existing worker policy remain unchanged.

## Task 2: Separate durable probe store and single-use fences

Add `infra/hybrid/stock_probe_store.py` with explicit fixed-root initialization and
operations context; private fictional root/UID helpers only for tests. Write filesystem
REDs before source. Freeze exact record keys, fixed artifact slots and typed fence
interfaces from the spec before each implementation step.

Implement namespace/lock identity, 128-probe complete lineage, immutable intent/head,
bounded original artifacts, exclusive flush/readback, one entry classification and
fresh-session acknowledgement state. CREATE/START/log/retirement fences are exact
issued one-use objects, not copied data. Distinguish CID retention from strict prestart
acknowledgement. Existing complete bytes after failed fsync grant no dispatch.

Recovery burns all admission/CREATE/START before fallible work and never returns
success. Only valid no-CREATE intent can abandon; contradictory/torn/name404 cases
remain unresolved. Scope STOP to actual lifetime/start presence and DELETE to stored
own full CID. Preserve historical CID uniqueness. Closed success requires actual
normal owner, clean RUN exit, strict prestart/output and acknowledged removal.

Exercise every write/crash window, lock/path/mode/link/substitution, changed bytes,
clocks, copied/reopened tokens, historical corruption, cleanup-only reopening and
retained-history deadline headroom. Expected: no unsafe capability can be reconstructed
from records or pure dataclasses; no worker-store/config path changes.

## Task 3: Fixed bounded Engine transports

Add `infra/hybrid/stock_probe_engine.py`. Use actual fixed Unix socket/root checks,
API 1.52, strict HTTP/1.0 close framing and exact probe routes only. No caller method,
body, path, socket, UID, CID or phase-extension override.

Write RED socketpair/fictional-wire cases for metadata, CREATE/CID retention, strict
prestart, one START, fresh owned inspection before signals, exact finite logs and
non-force retirement. Transport owns fence preparation/ack/recheck before wire.
Use one absolute five-second exchange cap shortened by phase cap; no retry on timeout,
partial send, rejection or ambiguous acknowledgement. Logs require multiplexed content
type, 8 KiB headers, 16 KiB complete body and final EOF. Shared body helpers may gain
only an earlier/smaller bounded limit while preserving original defaults/routes.

Scope typed 404 to already-stopped removal chains. Validate full ID/lifetime before
DELETE. Retain response/raw artifact hashes only after complete transport evidence.
Expected: fixed actual transport paths, no widening of production worker authority.

## Task 4: Controller composition, shutdown and fixed-root CLI

Add `infra/hybrid/stock_probe_controller.py`, composition tests and operational docs.
Public operator CLI accepts only one exact immutable image ID; it constructs fixed
store/Engine dependencies internally, and never initializes a missing namespace.

Write RED complete fictional-wire/filesystem flows for setup->CREATE->prestart->START
->natural exit->logs->retirement->closed success, all failed/ambiguous states, reopen
cleanup-only, no CREATE/START retry, fixed deadlines, first/repeated shutdown, old boot/
rollback, invalid output and failed persistence. Do not replace the actual pure/store/
transport seams with fake loader/controller results. Only the native boundary is fictional.

Implement fixed setup20/RUN30/TERM10/KILL5/final5/logs5/retirement15-second caps, original
timing and one shared shutdown state. Report lifecycle/configuration observation only
after success; preserve safe failure/recovery results and durable incidents. Every
recovery invocation ends without a new launch or configuration publication.

## Task 5: Integrated review and acceptance

Root reviews protected diffs and native assumptions, runs focused meaningful coverage,
stock deployment/architecture/worker/persistence regression, Ruff, strict mypy including
new host files, expanded Bandit and diff checks. Obtain one fresh whole-increment review.
Regrade/exhaustively rule on exclusions; fix Important/Critical with one root RED/GREEN
pass. Record deferred minors. Queue the actual integrated full only after any prior
full terminates; never infer this source's result from another revision.

Actual credential-free intended-host run, image/source provenance and trusted producer,
paused installation, deployed OAuth ownership, backups/restore, scheduled stock research,
source/strategy qualification and nonempty broker reconciliation remain external gates.
No live activation follows from implementation or successful local tests.
