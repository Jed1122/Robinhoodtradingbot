# Options operating-cost assumptions

**Status: documentation-only, not an invoice, deployment plan, purchase approval, or
economic go/no-go.** This is a public-source pricing snapshot taken on **2026-09-18
UTC**. It does not inspect a DigitalOcean account, provision resources, or establish
that any service is in use. Prices, product availability, taxes, credits, exchange
rates, and account-specific adjustments can change.

## Repository scope and discrepancy

`infra/digitalocean/main.tf` declares one Droplet with Droplet Monitoring enabled.
`infra/digitalocean/variables.tf` currently defaults its size to `s-1vcpu-1gb`.
The requested `s-1vcpu-2gb` is therefore a **separate public-price scenario**, not a
claim about the configured or running host. The deployment preparation report remains
`ECONOMIC_NO_GO` because validated options trading-edge evidence and complete
operating-cost evidence are absent ([deployment plan](options-deployment-plan.md)).
Operational readiness separately requires an options runtime benchmark. Nothing here
selects hardware: the repository has no such benchmark.

The manifests declare no Volume, Snapshot, Spaces bucket, backup schedule, alert
destination, external monitoring provider, market-data subscription, or model service.
`backup.sh` can create an encrypted application archive and its planned destination is
operator-configured; it does not establish an off-host storage provider or its size.

## Public DigitalOcean price inputs

| Item | Public price input | How it applies here |
| --- | --- | --- |
| Basic CPU Droplet `s-1vcpu-2gb` | **USD 0.01786/hour; USD 12.00/month; 2,000 GiB transfer quota**. [CPU Droplet pricing](https://www.digitalocean.com/pricing/droplets) (accessed 2026-09-18 UTC). | Conditional base-compute scenario only; a continuously existing bundled Droplet is billed per second, with a 672-hour monthly cap. [Billing terms](https://docs.digitalocean.com/products/droplets/details/pricing/) (last verified 2026-08-25; accessed 2026-09-18 UTC). |
| Droplet transfer over allowance | **USD 0.01/GiB outbound**; inbound is free. [Droplet pricing](https://docs.digitalocean.com/products/droplets/details/pricing/) (last verified 2026-08-25; accessed 2026-09-18 UTC). | Actual pooled team usage and included allowance consumption are unknown. |
| DigitalOcean Monitoring / Metrics Agent | **USD 0.00 additional cost**; DigitalOcean describes Monitoring as a free opt-in service and says it is provided at no additional cost. [Monitoring pricing](https://docs.digitalocean.com/products/monitoring/details/pricing/) (last verified 2026-07-13; accessed 2026-09-18 UTC). | The Terraform `monitoring = true` declaration requests the agent at Droplet creation, but neither installation nor alert configuration is runtime-verified. This does not price external application heartbeat or alert delivery. |
| Basic Droplet backups | Weekly: **20.0%** of that Droplet's monthly cost; daily: **30.0%**. [Backup pricing](https://docs.digitalocean.com/products/backups/details/pricing/) (last verified 2026-03-09; accessed 2026-09-18 UTC). | Not declared in Terraform. For the USD 12.00 scenario: weekly addition = `12.00 × 0.20 = USD 2.40/month`; daily addition = `12.00 × 0.30 = USD 3.60/month`. |
| Usage-based Droplet backups | Weekly **USD 0.04/GiB-month**, daily **USD 0.03/GiB-month**, every 12 hours **USD 0.02/GiB-month**, every 6 hours **USD 0.015/GiB-month**, every 4 hours **USD 0.01/GiB-month**. [Backup pricing](https://docs.digitalocean.com/products/backups/details/pricing/) (last verified 2026-03-09; accessed 2026-09-18 UTC). | Not declared. Monthly addition is the selected rate times the backup's restorable GiB; that size is unknown. |
| Block Storage Volume | **USD 0.10/GiB-month**, charged hourly while it exists, attached or not. [Volume pricing](https://docs.digitalocean.com/products/volumes/details/pricing/) (last verified 2026-07-13; accessed 2026-09-18 UTC). | No Volume is declared. If added, the conditional monthly amount is `GiB × USD 0.10`. |
| Droplet Snapshot | **USD 0.06/GB-month** (note the vendor states **GB**, not GiB). [Snapshot pricing](https://docs.digitalocean.com/products/snapshots/details/) (generated 2026-09-18; accessed 2026-09-18 UTC). | No Snapshot is declared; resulting billed GB are unknown. |
| Spaces Standard Storage | Subscription **USD 5.00/month** including **250 GiB** storage and **1,024 GiB** outbound transfer; additional storage **USD 0.02/GiB-month**, additional outbound **USD 0.01/GiB**. [Spaces pricing](https://docs.digitalocean.com/products/spaces/details/pricing/) (last verified 2026-07-13; accessed 2026-09-18 UTC). | No Spaces bucket is declared or selected. It is only one possible destination, not an assumed backup cost. |

## Conditional scenarios (USD before tax and account adjustments)

| Scenario | Arithmetic | Conditional monthly subtotal |
| --- | --- | --- |
| 2 GiB Droplet only | `12.00` | **USD 12.00** |
| 2 GiB Droplet + weekly Basic backups | `12.00 + (12.00 × 0.20)` | **USD 14.40** |
| 2 GiB Droplet + daily Basic backups | `12.00 + (12.00 × 0.30)` | **USD 15.60** |

These subtotals deliberately exclude overage transfer, Volume, Snapshot, object storage,
taxes, credits, support, and all non-DigitalOcean costs. DigitalOcean says automatic
backups are disk images and that they do not include Volumes; application-level backup
may be more appropriate for active database writes ([backup limits](https://docs.digitalocean.com/products/backups/details/limits/), last verified 2025-06-17; accessed 2026-09-18 UTC).

## Unknowns that block an actual operating-cost claim

- No account invoice, active resource inventory, region, tax treatment, credits, or team-wide
  transfer consumption was examined; public list prices cannot determine an actual bill.
- DigitalOcean Monitoring has a documented USD 0.00 additional cost, but its actual
  installation and alert configuration are unverified. Application heartbeat, external alert
  delivery, and any third-party monitoring cost are also unknown.
- Options data, brokerage/exchange fees, market-data rights, model/inference usage, operator
  time, incident recovery, and off-host encrypted-backup storage/egress are not established.
  A zero purchase or undeclared resource is not evidence of zero economic cost.
- The quoted 2 GiB scenario does not show that the 0.75 CPU / 768 MiB Compose limits, the
  current 1 GiB Terraform default, or any options workload is sufficient. Benchmark and
  restoration evidence remain required for operational readiness; validated edge and complete
  cost evidence remain required for an economic decision.
