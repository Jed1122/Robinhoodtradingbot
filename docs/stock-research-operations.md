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

## Next implementation and proof

Follow the [operations plan](superpowers/plans/2026-10-21-stock-research-operations.md).
Freeze the resolved Compose hash preimage, hard deadline/termination semantics,
paused installation precondition and owned orphan-container recovery receipt before
the root launcher implementation. Use a sibling stock namespace outside the dashboard's
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
