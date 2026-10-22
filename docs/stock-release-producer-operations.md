# Stock release producer operations

Status: local implementation prefixes only. There is no public `produce_release`
function or completed producer CLI yet. Do not invoke private stages manually as a
deployment procedure. No native Docker build/probe/render, installation, credential
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

The unfinished public producer will accept only a source archive SHA-256. Its
inputs belong at `inputs/<sha>.tar`; each source owns one exclusive attempt under
`attempts/<sha>/`. Source preparation is repeated and matched inside the owning
attempt. The current implementation rejects every historical attempt. Successful
distinct-source admission still needs the [terminal closure contract](stock-release-producer-closure.md).
Do not treat this intermediate restriction as the finished product.

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
trusted and present. The intermediate publisher requires an empty release parent
because no completed historical admission exists. Every file is exclusively created,
mode0444, flushed, read back with original inode bindings and checked by the existing
release loader. A consistent readable release is not terminal producer success.

Failure never refunds an attempt or authorizes replay. Do not delete, rename,
replace, prune, chmod or reconstruct its records to make another call pass. Preserve
the private namespace and original failure evidence for root-owned incident analysis.
No automatic cancellation/removal or daemon-termination claim follows from a timeout.
Local process failure cleanup targets only its own newly created process group;
it does not establish that Docker's daemon stopped a build or container.

## Verification and installation gates

The new filesystem/process tests use disposable local Git, harmless local Python
children and local Docker socket fixtures. Native Docker is default-denied; no
provider/credential/account state participates. Narrow verification covers process
capture, source preparation, render, release publication and the existing loader.
Then run deployment, architecture and stock worker regressions plus Ruff, strict
mypy, expanded Bandit, lock and diff checks. The completed producer needs one
whole-branch review and its own frozen full repository run; prior revisions' full
results do not certify it.

Before installation, finish the terminal/history/CLI contract and actual native
build → fresh probe → reviewed render → release → cleanup proof. Then verify an
installation with collector controls paused and scheduling disabled. Scheduled
research with Codex closed, authentication expiry/revocation, monitoring, restart
recovery and encrypted off-host backup restoration remain independent gates.

Stock data/strategy qualification and complete nonempty Robinhood reconciliation
also remain incomplete. There is no mandatory60-day paper wait. Live execution
stays disabled and requires its own user-controlled activation after readiness.
