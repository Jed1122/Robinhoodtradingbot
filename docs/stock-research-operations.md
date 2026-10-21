# Stock research operations status

The local one-shot worker, explicit collector controls and authenticated dashboard
projection are implemented. A separate supervised stock deployment is not installed
or verified. Existing paused services remain unchanged. Live execution stays disabled.

## Configuration-only observation

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.stock_research_identity \
  --config-root configs
```

This command reuses the canonical configuration load shared by worker startup and
control resume. It reports the full configuration hash, scan interval, run deadline,
source-age and call bounds, with `live_enabled=false`. It makes no code-identity,
attestation, credential, database, control, SDK or provider operation. Invalid policy,
missing files and an unsafe live environment override produce a fixed blocked result.
No caller hash or activation argument exists.

The output is a configuration observation, not executing-image attestation or authority
to start collection. The future root release producer must run it in a credential-free,
network-disabled container and independently inspect that container's exact immutable
image and absent mounts. Only then can it produce the existing canonical trusted-root
attestation. A local CLI result does not prove that image procedure occurred.

The new probe and unchanged worker/control identity paths passed 285 focused and
architecture tests with 97.77% combined branch coverage over probe and worker (probe
individually 85%). Ruff, strict mypy, Bandit, lock and diff checks passed. Independent
review cleared the extraction. An actual local command returned the unchanged full
stock configuration hash and bounded defaults without any provider operation. No
native container or deployed configuration proof is claimed.

## Retained release verification

`compose.stock-research.yml` defines the isolated worker policy. The local Compose tool
rendered it successfully using fictional image/release values, without creating or
starting a container. `infra/hybrid/stock_release.py` now verifies the four canonical
retained release artifacts described in the [container contract](stock-container-contract.md).
Its public loader fixes the production namespace and root ownership; it performs no
Docker, provider, credential, ledger, control or activation operation.

The verifier and Compose policy passed 102 fictional tests with 99% branch coverage over
the verifier. Tests include type-equivalent policy substitutions, jointly invalid bounds,
independently altered attestations, unsafe files/parents, namespace replacement and
operating-system cleanup failures. The latter review finding was reproduced with two
failing tests and corrected. Ruff, strict mypy and the lock check passed; the expanded
Bandit check separately reviews the host verifier as well as application source. Its
Docker tmpfs comparison string has a documented B108 false-positive annotation; no host
temporary file is created and no scanner rule was disabled globally.

This is retained-record verification, not trusted release production, actual container
inspection, deadline enforcement, installation or continuous-operation evidence.

The data-only Engine/image metadata parsers are implemented locally as a separate
precondition to future container creation. They require the fixed API 1.52 range,
matching image/platform, the reviewed inherited environment and absent implicit image
volumes/ports. They retain the disabled-healthcheck timing profile. The parser tests
passed 67 checks with 100% branch coverage, including an independently found and corrected
nonfinite exponent-overflow case. All deployment-related tests passed 245 checks with
four optional local-age skips. Independent review, Ruff, strict mypy (442 files), expanded
Bandit, lock and diff checks passed. These checks made no Docker or provider connection.
The actual pinned image values and native worker/hardening compatibility remain unknown;
an unsupported host must be denied, with no automatic daemon upgrade or API downgrade.

An authorized read-only October 21 check of the existing droplet observed Docker 29.1.3
advertising API 1.44–1.52, Linux amd64 and cgroup v2/systemd. The initial 1.55 profile
would deny that host. Independent review confirmed the required image/container safety
fields and semantics in the official 1.52 schema; source/tests now explicitly pin 1.52
without runtime negotiation or weaker limits. Two changed-version tests were observed
RED before the constant changed; all 67 parser checks then passed with 100% branch
coverage. No image was built, no container was created or started, and no service,
broker credential or trading setting changed. An advertised API range is not
executing-container or capacity evidence.

The subsequent data-only worker request/prestart comparison is implemented and
independently reviewed: 129 tests passed with 100% branch coverage after Docker's
documented null-versus-empty volume normalization was reproduced and corrected.
The fixed GET-only Unix-socket reader passed 53 cases at 97.40% branch coverage;
its shared transport independently rejects unsupported routes before connection.
Independent and central deployment regression passed 427 tests with four optional
age skips. Ruff, strict mypy (444 files), expanded Bandit and lock checks passed.

One separately authorized native `/version` GET through that reviewed reader and
version parser succeeded on the existing host with API 1.52/Linux amd64. No host
file was installed, image/CID inspected, container mutated or broker called.
This is bounded metadata compatibility; worker supervision, immutable-image/CID
verification, durable recovery, installation, timer, actual scheduled acquisition
and encrypted backup/restore remain pending. See the
[exact verification record](stock-research-verification-2026-10-21.md).

The root-private operations attempt store is now implemented locally. It uses a
permanent host lock, exclusive durable intent/CID/start/stop receipts, a bound active
pointer and single-use start fences. Reopening never adopts an unfinished attempt
for execution. Fresh stopped-state reconfirmation and successful file/directory
flushes are required before admitting a later attempt. Review-found persistence,
identity and failed-validation acknowledgement gaps were reproduced and fixed;
independent review cleared the final source at e485be8. Its 72 filesystem tests and
499 deployment regressions passed, with four optional local-age skips. No production
operations namespace was initialized. Supplied inspection objects establish local
consistency only; actual ownership/stopped provenance, native recovery and the
supervisor remain unverified.

The later scoped create/start library is implemented locally, without a CLI or
service composition. Its shared exchange obtains the one-use fresh create claim
or durable start fence internally and rechecks state immediately before sending.
Separate 201/204 response handling preserves uncertainty without retries; the
GET-only reader is unchanged. Independent reviews cleared 7af0a33 after 144
focused filesystem/socket tests and additional negative probes. Central deployment
and architecture checks passed 756 tests with four optional age skips; the mutation
module has 100% combined statement/branch coverage. No native mutation occurred.

The frozen dashboard full run ended with 11,597 passed, 33 optional skips and two
test-context failures. Reviewed test-only fixes and a 131-test ordered regression
resolved the demonstrated interactions without changing production secret/logging
guards. The corrected a63a475 full baseline then passed 11,810 tests with 33 optional
skips, one dependency deprecation warning and 88.77% combined branch coverage in
4,258.53 seconds. The primary now runs a separate full check at f04a63f, covering
later operations/reconciliation work. This subsequent dispatch increment is outside
that frozen candidate and still requires its eventual full integration check; no
deployment readiness is claimed.

The pure stock-minute manifest/reconstruction adapter was independently reviewed at
ae991be and merged locally at 63a988e. It preserves original calendar/response bytes,
canonical hashes and declared clock/request context, and reparses every page through
the existing minute parser. Its 108 new tests plus 92 existing data/technical/screen
tests passed independently; 58 additional negative probes passed. Central deployment,
architecture and stock-data checks passed 956 tests with four optional age skips.
All source/strategy/investment/live flags stay false. There is no private capture
archive, authenticated acquisition or source qualification in this adapter.

The next root-owned increment adds read-only recovery snapshots and a separate scoped
TERM/KILL library. Seventeen missing-behavior snapshot tests and 74 missing-library
tests were observed RED. The complete store/create-start/termination subset then
passed 235 tests, at 98% combined statement/branch coverage over the store and
termination library (97% for termination alone). Central deployment/architecture and
stock-data regression passed 1,047 tests with four optional local-age skips. Ruff,
strict mypy (448 files), expanded Bandit, lock and diff checks passed. Independent
review is still required. No native signal or controller is claimed.

## Next implementation and proof

Follow the [operations plan](superpowers/plans/2026-10-21-stock-research-operations.md).
The container contract freezes the resolved Compose hash preimage, hard deadline and
termination semantics, paused installation precondition and owned orphan-container
recovery receipt. Implement and test the root launcher and trusted release producer next.
Use a sibling stock namespace outside the dashboard's
whole-parent state mount, and keep credentials worker-only. Never initialize or resume
controls from the timer or launcher.

Then verify actual created/executing image, UID/mount/config identity, termination of
the verified container, no overlap/catch-up/replay, authentication lifecycle, encrypted
backup/off-host restoration, command audit and stock freshness alerts. Installation must
leave the timer disabled and controls paused. Actual scheduled collection with the
development client closed is required before claiming continuous operation.

Market-data and stock-strategy qualification, complete nonempty broker reconciliation
and separate live authorization remain additional requirements. No mandatory paper
waiting period is introduced.
