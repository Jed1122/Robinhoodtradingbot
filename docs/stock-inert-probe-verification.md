# Inert configuration prerequisites: local verification

This increment implements pure prerequisites for a credential-free native image
configuration probe. It does not create/start a container, retrieve logs, produce
trusted native evidence, install a scheduler or enable trading.

## Implemented

`stock_release.normalize_configuration_observation(raw)` validates bounded supplied
JSON and returns its one canonical representation. It rejects duplicate/missing/extra
fields, nonfinite or mistyped values, unsafe bounds and live values other than exact
false. The actual release loader still separately binds hash, run bound and cadence
to its checked manifest. Normalization supplies no source or execution provenance.

`stock_probe_profile.probe_request(image, probe_id)` fixes the existing identity
command, explicit disabled networking, no application/data mounts, image environment,
disabled healthcheck and hardened finite resource/log profile. Supplied created-CID
comparison verifies the complete fixed policy and never-started state. Its copied
CreatedProbe identity grants no CREATE/START or stopped acknowledgement.

Only neutral default fields, disabled-image health comparison and strict common
metadata comparisons were extracted from the existing worker prestart module.
Production worker policy remains byte-identical for its frozen fictional fixture:
`75438f69c605f0ec5edf4154ca2f534f665dd6238cb70a1dd7052d5c29aac2a9`.
Its bridge network, six mounts and application tmpfs remain distinct from the probe.
No launcher/store/transport change was made by this increment.

`stock_probe_output.decode_probe_output(raw)` checks supplied complete bounded Docker
multiplexed body bytes, reassembles stdout and applies the same closed normalizer.
It rejects malformed/truncated frames, nonzero reserved bytes, stderr, daemon errors,
unknown streams, excess frames/output and invalid JSON. A valid JSON prefix followed
by a daemon-error frame denies. Zero-length stdout frames count toward the finite
128-frame budget and cannot themselves create a configuration result. This parser
cannot establish HTTP completion, container identity, exit status or log retention.

The [design](stock-inert-probe-design.md) pins exact fields, limits and primary Moby
sources. Empty inspected application mounts do not assert an empty physical mount
namespace: Docker manages private IPC and an init-executable bind separately.

## Checked locally

- Task 1: 70 new RED cases became GREEN; normalizer/release/identity/worker/control/
  configuration selection passed 231 checks.
- Task 2: 86 missing-profile RED cases became GREEN; the existing worker golden was
  already passing. Profile/image/prestart selection passed 283 checks, with 100%
  branch coverage of the new profile.
- Task 3: 383 missing-decoder RED cases became GREEN. Output plus normalizer passed
  453 checks, with 100% branch coverage of the new output module. Cases split JSON
  across every stdout-frame payload boundary and cover error frames after success.
- Integrated stock deployment, architecture, worker configuration/CLI and persistence
  selection passed 1572 checks in 45.76 seconds.
- Ruff and strict mypy over source plus nine host modules passed (453 files).
- Expanded Bandit over application source and the nine host modules exited zero
  with no findings; existing unused-annotation warnings remain.

Independent whole-increment review and the exact integrated revision's full
repository regression remain separate pending gates at
this checkpoint. The primary's earlier full run remains running on frozen f05dbe8;
no result is inferred for this later code. No native Docker, provider, credential,
account, order, transfer or live operation occurred.

## Next evidence

Freeze and implement the root controller's durable ownership/dispatch/recovery and
absolute run/TERM/KILL/final-observation contract, then the fixed bounded native
transports. Verify intended-host image/created-CID/output/stopped/cleanup behavior
without credentials/network before trusted release production. Actual research
worker compatibility, exclusive OAuth ownership, backup/restore and installed
external scheduling follow separately. Data/strategy qualification, nonempty broker
reconciliation and explicit user-controlled live activation still precede purchases.
There is no fixed paper waiting period.
