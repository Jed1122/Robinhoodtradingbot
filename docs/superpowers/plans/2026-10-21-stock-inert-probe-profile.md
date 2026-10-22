# Inert stock configuration profile and output validation

Status: planned, not implemented. Root-owned local continuation after the repeated
research-cycle increment. No deployment, Docker mutation, image build/pull, OAuth,
provider, account, order, control or live operation belongs to this plan.

Spec: [inert probe boundary](../../stock-inert-probe-design.md).
The current repeatable-cycle candidate is `57c819dd24b1a881e91f2557fae91a45fefecb30`;
its Task 4 full regression remains pending. Preserve that acceptance boundary and
the primary's actual running full suite. No duplicate full run.

The product purpose is individual-stock research, qualified selection and eventual
risk-controlled automatic investing. This subplan supplies data-only prerequisites
for native configuration observation; it does not become execution authority.

## Files and interfaces

- A shared pure closed configuration-observation validator, extracted without
  changing current release semantics from `stock_release._validate_observation`.
  The release wrapper still binds config hash/run/cadence to its actual manifest.
- `infra/hybrid/stock_probe_profile.py`: fixed inert request bytes, strict supplied
  created-container comparison and frozen copied identity. It accepts only the
  existing checked ImageProfile, a generated 32-hex probe ID, actual full 64-hex CID
  where needed and raw observation bytes. It accepts no command, mount, environment,
  network, resource, credential, release, path or live override.
- `infra/hybrid/stock_probe_output.py`: pure bounded Docker-frame decoder and closed
  configuration-observation parser. Input is already bounded complete body bytes;
  returned canonical observation is data, never proof of HTTP EOF, image identity,
  actual execution, durability or promotion.
- Focused fictional deployment tests plus a verification note. Keep the existing
  production launcher/store/transports and worker policy unchanged.

## Task 1: One reusable closed configuration observation

Write RED tests for exact scalar types, every bound, cross-field daily/cycle limits,
unknown/missing/duplicate fields, nonfinite values, live not exactly false, malformed
hashes and noncanonical input normalization. The parser returns the complete closed
observation as canonical bytes only after checks. Reuse strict existing JSON helpers;
do not manufacture a manifest or release to validate a probe result.

Extract the shape/range validation into one pure helper. Preserve all existing
manifest-binding checks and byte identities in the release verifier. Run release,
identity CLI and worker/control regressions. Expected: prior release fixtures remain
unchanged; no caller result or hash acquires trusted provenance.

## Task 2: Separate fixed inert request and created-container comparison

Write RED fictional requests/inspections for the exact profile in the spec. Pin the
full request fields and type-sensitive resource/hardening values before implementation.
Share existing pure comparisons only where semantics are identical; do not widen
production worker admission or use a fictitious StockRelease to bypass its dependency.

Check actual never-started state, immutable image/full CID/name/probe labels,
entrypoint/arguments/environment, disabled healthcheck, no requested/declared/resolved
mounts or ports, explicit disabled networking and private namespaces. Reject alternate
identities, implicit image effects, unknown dangerous fields and type-equivalent bools.
Preserve documented field-specific null/empty normalization without broad equivalence.
Supplied valid JSON returns only copied identity; it cannot authorize a START.

Run new profile plus current image/prestart/worker request tests. Expected: both
profiles retain distinct commands/network/mounts; no new Docker connection occurs.

## Task 3: Strict finite multiplexed-output decoder

Write RED tests for JSON split across every stdout-frame payload boundary, multiple
stdout frames, zero/excess frames, 16 KiB body/128 frame/4 KiB stdout boundaries, truncated
headers/payloads, wrong stream/reserved bytes, stderr, daemon errors after valid stdout,
extra garbage/JSON, invalid UTF-8, duplicate keys and false-equivalent values.

Decode only complete bounded bytes. Reassemble stdout in order and validate exactly
one closed successful configuration JSON observation through Task 1. Reject every
stderr/daemon/unknown stream and incomplete framing. Do not accept a successful JSON
prefix followed by an error frame. Retain raw framed bytes separately at the eventual
controller boundary; normalization does not replace transport or source evidence.

The later transport must implement the exact fixed route, content type, absolute
deadline, bounded headers/body and final EOF from the spec. This task adds no transport,
logs method to StockEngineReader, controller, persistence or native probe.

## Task 4: Integrated local verification and independent review

Run new tests with meaningful branch coverage, current deployment and architecture
regression, Ruff, strict mypy including new host modules, expanded Bandit and diff
checks. Root independently checks the production launcher/store/request diff is empty.
Obtain one fresh whole-increment review. Regrade findings, address Important/Critical
ones with one root RED/GREEN pass and disclose limits. Do not equate this local
acceptance with a successful native probe or the earlier candidate's full run.

Next contract: root persistence/ownership, fixed run/TERM/KILL/observation caps,
closed native transports, one-use START, ambiguous-response recovery and observed
stopped cleanup. Only after that reviewed implementation may an inert intended-host
probe produce evidence for the separate trusted release producer. No timer or live
activation follows automatically.
