# Stock release producer operations

Status: locally implemented producer, pending final acceptance and native qualification.
Do not invoke private stages manually as a deployment procedure.
No native Docker build/probe/render, installation, credential
movement, research start or live activation has been performed by these changes.

## Available interfaces and fixed policy

`infra.hybrid.stock_source_prepare.prepare_source(output: Path) -> str` owns one
clean committed Git archive from the installed checkout. It exclusively writes a
new mode0600 file under a trusted existing parent and returns its SHA-256 after
readback and cleanup. The output is data identity, not build or deployment authority.
Use an independent private staging directory outside the producer namespace; do
not add an arbitrary staging file to the producer's exact root inventory. No secret,
provider capture, account state, untracked file or environment file is selected.

`infra.hybrid.stock_release_producer.initialize_producer()` explicitly initializes
the fixed Linux UID0 `/var/lib/hybrid-stock-producer` namespace once. Its parent
must already be trusted and present. Initialization does not build or install
anything. Partial/existing namespaces are denied, never repaired automatically.

The public `produce_release(source_sha256: str) -> Path` accepts only an archive SHA-256. Its
inputs belong at `inputs/<sha>.tar`; each source owns one exclusive attempt under
`attempts/<sha>/`. Source preparation is repeated and matched inside the owning
attempt. Completed histories require complete closed-chain validation and fresh
flush/readback under the permanent actual lock before admitting a different source.
Partial histories and same-source replay are denied. The narrow
[spent-build operation](stock-failed-build-reconciliation.md) can add negative facts
for one qualified incident; it never supplies a successful release. See the
[terminal closure contract](stock-release-producer-closure.md).

The host profile is fixed Docker29.1.3/API1.52/Linuxamd64 and Compose2.40.3. The build
uses the reviewed Dockerfile and immutable base, with no registry authentication,
tag, remote context or extra build arguments. Frozen public dependencies may require
network access during build; `pull=false` does not establish an offline build.
The separate inert configuration probe is network-disabled and credential-free.

Rendering owns the original template, an explicit empty env file, empty private
Docker config/HOME/executable-PATH directories and a scrubbed environment. It fixes
the local socket, project and paths and disables image resolution. It retains both
raw bounded streams and exact invocation intent; only the complete exact reviewed
model can advance. Installed CLI/plugin identity and compatibility remain native
verification requirements. No authenticated service or brokerage call is needed.

## Files and incidents

The private attempt keeps source, native build evidence, fresh probe/configuration,
render workspace/streams and publication intent/file receipts. These records are
separate from the four immutable release files:

- `stock-configuration.json`
- `stock-compose.resolved.json`
- `runtime-image-attestation.json`
- `manifest.json`

The release directory is fixed at
`/opt/hybrid-stock-research/releases/<source-sha256>/`; its parent must already be
trusted and present. The release parent's inventory must match exactly the admitted
successful completed histories only; spent-failed attempts have no release.
Unknown or existing target releases are denied.
Every file is exclusively created,
mode0444, flushed, read back with original inode bindings and checked by the existing
release loader. A consistent readable release is not terminal producer success.

Failure never refunds an attempt or authorizes replay. Do not delete, rename,
replace, prune, chmod or reconstruct its records to make another call pass. Preserve
the private namespace and original failure evidence for root-owned incident analysis.
No automatic cancellation/removal or daemon-termination claim follows from a timeout.
Local process failure cleanup targets only its own newly created process group;
it does not establish that Docker's daemon stopped a build or container.

## Production command

After independent native qualification, use a trusted root-owned clean checkout on
the reviewed Linux host. The fixed producer and release parents must be explicitly
prepared; normal production never initializes or repairs them. Stage the input with
the existing `prepare_source` helper: first obtain its SHA in a separate private
staging directory, then prepare the still-clean same HEAD into the absent
`inputs/<sha>.tar`, checking that the returned SHA matches. This avoids an overwrite
or unacknowledged copy; a changed HEAD or mismatching filename must stop the procedure.
The owning producer still repeats and matches source preparation before its build.

```sh
PYTHONPATH=src python -m infra.hybrid.stock_producer <source-sha256>
```

The only positional input is that digest. Root, image, account, mode, endpoint,
configuration and deadline overrides are unsupported. The production namespace
boundary requires Linux/UID0. On success, one bounded JSON object contains `status`
and the fixed derived `manifest` path. Require actual exit0 as well as complete JSON;
a blocked/partial/late output is not acknowledgement. Formatting, descriptor and
handler cleanup, identities and output checks share the original producer window.
Failures may additionally emit one canonical stderr diagnostic up to1024bytes:
allowlisted first phase, exception family/errno and bounded secondary cleanup facts.
It contains no exception text, paths, response bytes, arguments or credentials.
Success stderr remains empty. A diagnostic is never a retry instruction or evidence
that the daemon completed a mutation.
No credential, research start, service/timer, worker control or live-mode write follows.

## Verification and installation gates

The new filesystem/process tests use disposable local Git, harmless local Python
children and local Docker socket fixtures. Native Docker is default-denied; no
provider/credential/account state participates. Narrow verification covers process
capture, source preparation, render, release publication and the existing loader.
Then run deployment, architecture and stock worker regressions plus Ruff, strict
mypy, expanded Bandit, lock and diff checks. The completed producer needs one
whole-branch review and its own frozen full repository run; prior revisions' full
results do not certify it.

Before installation, complete final review/full acceptance and actual native
build → fresh probe → reviewed render → release → cleanup proof. Then verify an
installation with collector controls paused and scheduling disabled. Scheduled
research with Codex closed, authentication expiry/revocation, monitoring, restart
recovery and encrypted off-host backup restoration remain independent gates.

Stock data/strategy qualification and complete nonempty Robinhood reconciliation
also remain incomplete. There is no mandatory60-day paper wait. Live execution
stays disabled and requires its own user-controlled activation after readiness.
