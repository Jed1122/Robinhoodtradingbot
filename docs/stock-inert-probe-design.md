# Inert stock-configuration probe boundary

Design checkpoint after `57c819dd24b1a881e91f2557fae91a45fefecb30`.
This path is not implemented or native-verified. It supplies the missing configuration
observation for trusted release production; it is separate from the research worker.
The product objective remains continuous individual-stock research followed by
qualified, risk-controlled automatic investing after separate live activation.

## Scope and dependency

The existing configuration command loads canonical policy without OAuth, provider,
database, control or execution operations:

```text
python -m trading_bot.runtime.stock_research_identity --config-root /app/configs
```

The research-worker request cannot be used for this check: it fixes a different
entrypoint, bridge networking and six host mounts, including OAuth. A release cannot
be fabricated to call that builder because the configuration observation is itself
a prerequisite for the release. Keep the production launcher, worker policy and
operations history unchanged.

Use a separate fixed inert request and created-container comparison, sharing only
pure strict parsing and hardening comparisons where their semantics are identical.
Do not introduce a general arbitrary-command container launcher. Do not make the
configuration hash, bounds, live state or successful observation caller-selectable.

## Required profile

- An independently read immutable local image ID, accepted by the existing image
  and Engine verifiers. No automatic build, pull, tag resolution or daemon upgrade.
- Exactly the command above, image-owned UID/GID `10001:10001`, `/app` workdir and
  the reviewed image environment, including both live flags set to `false`.
- `NetworkMode=none` and an explicit disabled-network configuration, checked against
  the actual created container. No caller proxy, host entry, DNS or network override.
- No declared volumes, binds, mount requests, resolved host-data mounts, published
  ports, devices, Docker socket, OAuth, account data or attestation mount. Docker's
  kernel-managed process filesystems are not a claim of an empty mount namespace.
- Read-only root filesystem, all capabilities dropped, no-new-privileges, private
  IPC/cgroup namespaces, default isolated PID/UTS mode, init forwarding, 128 pids,
  0.5 CPU, 512 MiB memory with no additional swap, bounded json-file logs, disabled
  healthcheck, no restart and no automatic removal. No application scratch mount
  is needed by this read-only command.
- A separate generated probe name/label identity, never a production worker name
  or a fabricated release/attempt identity. Actual policy comparison must include
  the immutable image, full returned CID, exact command/environment, namespaces,
  declared and resolved mounts, hardening and resource limits before START.

The no-network profile must first be tested against pinned Docker API 1.52 source.
Request declarations and supplied inspection fixtures establish local consistency;
only intended-host observations establish applied compatibility.

## Native evidence and uncertainty

The eventual root controller must retain intent before CREATE, the original bounded
dispatch attempt, full CID when acknowledged, actual prestart inspection, one START
attempt, actual stopped inspection, bounded stdout/stderr and owned cleanup outcome.
Fresh filesystem acknowledgement and inspection remain distinct from readable bytes.
No ambiguous response may cause blind retry, name-based adoption, a second START,
deletion of an unknown container or a claim of process absence. An unfinished probe
is an incident to resolve before another probe; it cannot publish a release.

Each Engine exchange keeps an absolute five-second maximum. Freeze the controller's
finite run and TERM/KILL/final-observation caps, persistence schema and exclusive
ownership before adding any native mutation. Those operational contracts are the
next design step, not authority supplied by this data-only profile.

Only after an observed clean exit may output be interpreted. Retain complete bounded
binary log bytes and their original framing. Non-TTY Docker logs multiplex stdout,
stderr and possible daemon-error frames; HTTP 200 and `follow=false` alone do not
establish complete successful output. The future retrieval route must be exact,
finite, full-CID scoped and byte/deadline bounded, with final EOF and strict frame
validation. Reject daemon error frames, stderr, truncation, unexpected output,
additional JSON values, unknown fields and nonfinite numbers. Do not reuse the
current GET reader as an arbitrary logs client or silently strip framing.

The frozen future retrieval is one HTTP/1.0 `Connection: close` request to
`/v1.52/containers/<owned-full-CID>/logs?stdout=true&stderr=true&follow=false&timestamps=false&tail=all&details=false`.
Omit time filters. Require non-TTY multiplexed content type, no transfer encoding,
an 8 KiB header limit, a 16 KiB framed-body limit, at most 128 frames, at most 4 KiB
combined stdout and one absolute five-second exchange budget. Content-Length or
connection-close framing may delimit the body; both require final EOF and complete
eight-byte frame headers/payloads. The stream byte must be stdout `1`; stderr `2`,
daemon error `3`, unknown streams and nonzero reserved bytes deny. Frame boundaries
need not align with socket reads. These are chosen conservative local limits, not
provider guarantees.

This follows the pinned API 1.52 [route implementation](https://raw.githubusercontent.com/moby/moby/d105562beff448ae44d6e3a2f7738b235fd197b5/daemon/server/router/container/container_routes.go),
[frame writer](https://raw.githubusercontent.com/moby/moby/d105562beff448ae44d6e3a2f7738b235fd197b5/daemon/internal/stdcopymux/writer.go)
and [log/error writer](https://raw.githubusercontent.com/moby/moby/d105562beff448ae44d6e3a2f7738b235fd197b5/daemon/server/httputils/write_log_stream.go).
The route sets a multiplexed content type and errors may arrive after status 200.
Actual intended-host HTTP framing, driver retention and flush behavior still need
native verification; a complete received response does not prove an infallible log
store or native process identity.

The one successful JSON result must satisfy the existing closed configuration
observation schema and exact scalar/range checks. Preserve emitted bytes separately
from its canonical normalized JSON. A successful probe supplies a configuration
observation only. It does not prove source provenance, an executing research worker,
authentication refresh, strategy merit, broker reconciliation or live authorization.

Cleanup requires a fresh matching owned stopped observation of that exact full CID,
then non-force removal without volume deletion and closed acknowledgement. Preserve
probe evidence before cleanup. A later scoped missing-container result may resolve
only an already stopped owned resource, subject to the same native lookup caveats
as the research-worker protocol. Never substitute a missing name for stopped proof.

## Acceptance order

1. Complete the repeated-cycle increment's revision-specific full regression.
2. Implement and independently test the separate pure inert request/comparison and
   strict multiplexed-output decoder using fictional observations only.
3. Freeze and review the controller's root ownership, persistence, deadlines and
   recovery contract, then implement its bounded transports and controller.
4. Verify an intended-host inert run without credentials/network and retain actual
   image, created/executed container, output, termination and cleanup evidence.
5. Produce the immutable release through the separate trusted producer; then verify
   paused research-worker compatibility, exclusive OAuth ownership, backups/restore
   and external scheduling. Installed timers must initially remain disabled.

No implementation, installation, scheduled-operation, market-data qualification or
investment-readiness claim follows from this design. There is no fixed paper waiting
period. Data/strategy evidence, deterministic risk, nonempty broker reconciliation
and explicit user-controlled live activation remain required before stock purchases.
