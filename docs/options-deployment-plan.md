# Options deployment preparation report

This repository provides a credential-free, deterministic preparation report for the unfinished
options deployment milestone:

```shell
PYTHONPATH=src python -m trading_bot.cli.options_deploy_plan
```

The command prints one compact JSON object to standard output. It accepts no configuration,
credential, account, host or cloud arguments. It does not read process environment values, inspect
files or services, open a network connection, write an artifact, invoke Docker or Terraform,
authenticate, deploy, or trade. Because it contains no timestamp or machine-derived values, the
output is byte-for-byte deterministic for this source version.

## Verdicts

The four verdicts are intentionally separate and permanently fail closed in this preparation
slice:

| Dimension | Reported verdict | Meaning |
| --- | --- | --- |
| Technical and operational | `NOT_READY` | Durable options operation, restore, heartbeat, monitoring and command evidence is incomplete. |
| Economic | `ECONOMIC_NO_GO` | No empirical options edge or complete operating-cost evidence exists. |
| Capability | `UNVERIFIED` | Repository declarations do not prove session, account or deployed-runtime capability. |
| Operator authorization | `NOT_AUTHORIZED` | No live deployment or trading authorization is granted. |

`live_deployment_ready` and `live_trading_enabled` are both `false`. The report cannot be used as a
promotion, readiness, capability or authorization artifact.

## Declared resources

The `paused_deployment` section inventories known repository declarations only. Its
`declaration_status` is `NOT_RUNTIME_VERIFIED`. It records the existing paused-shadow startup,
loopback monitoring endpoints, live-disabled flags, Compose limits of `0.75` CPU, `768m` memory and
256 PIDs, fail-closed container/deployment/backup controls, and expected local manifest paths.

These values are not benchmark results and the command does not check whether any manifest exists
on a host. A declared Dockerfile, Compose service, script or Terraform file is not evidence of a
successful build, restore, deployment or running service.

## Required evidence and costs

Every `required_evidence` entry is `MISSING`. The list covers:

- durable options state and restart reconstruction;
- options runtime capability evidence;
- an options process benchmark;
- current hosting, storage, data and monitoring costs;
- an encrypted restore and schema-rollback drill;
- an external heartbeat and verified alert delivery;
- options health, readiness and metrics; and
- complete options operator commands and a runbook.

The `cost_evidence` section contains no monetary values and makes no estimate. Hardware selection,
paid service use and deployment remain blocked until current evidence is gathered and reviewed.

## Scope and limitations

This command is report rendering only. It does not implement durable options lifecycle,
reconciliation, scheduling, monitoring, backup restoration, incident handling, execution or risk.
It makes no profitability claim and placed no live order. The existing paper-safe and paused
defaults remain unchanged.
