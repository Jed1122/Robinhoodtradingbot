# Robinhood Multi-Asset Trading System Implementation Plan

## Current ETF continuation (2026-10-05)

The fixed SPY/cash ETF pilot is the current research priority under the operator's
later instructions; the options implementation and historical plan remain intact.
Alpaca is the selected market-data channel, Robinhood the execution target.
Incremental offline history replay and durable owned execution facts are merged;
the [independent economic owner plan](superpowers/plans/2026-10-05-etf-joint-economic-owner.md)
adds joint cash/allocation/settlement/trial reconstruction. Its
[boundary report](etf-joint-economic-owner.md) distinguishes local fixture verification
from authenticated sources, accepted economics, protected broker composition,
qualifying paper/shadow operation and deployed recovery. Exact release/merge status
is reported by the feature PR; no unmerged work is represented as released here.
All readiness and live blocks remain, with no profitability claim.

## Current governing migration (2026-09-18)

The [options-only master specification](options-only-build-spec.md) and approved
[migration implementation plan](superpowers/plans/2026-09-18-options-only-migration.md)
supersede conflicting multi-asset and earlier long-options-only requirements. See the
[migration map](migration-map.md) and [current validation/progress report](options-migration-validation.md).
Development is authorized; broker calls, account inspection, production migration,
Cloud jobs, paid services, deployment and live activation are not.

The initial options domain/configuration foundation and single-unit synthetic replay
are implemented locally. Complete production pretrade composition, historical research,
capability integration, durable options lifecycle and deployment handoff remain unfinished.
No options live capability or economic readiness is established by this progress.

## Historical implementation plan

This repository is being implemented incrementally from the approved plans. The capability
foundation and the first safety-kernel tasks are executable, but no composed trading
application, broker write, qualifying promotion history, or live order is represented as complete
by this document. A hardened paused DigitalOcean deployment, seven authenticated equity reads, and
a one-shot write-incapable connected-shadow composition now exist.

The approved design is in [`docs/superpowers/specs/2026-07-10-robinhood-multi-asset-trading-system-design.md`](./superpowers/specs/2026-07-10-robinhood-multi-asset-trading-system-design.md).

The executable plan index is [`docs/superpowers/plans/2026-07-10-robinhood-system-implementation-index.md`](./superpowers/plans/2026-07-10-robinhood-system-implementation-index.md). Implement its slices in order:

1. Capability and repository foundation.
2. Safety, persistence, risk, authorization, and recovery kernel.
3. Market data, research, deterministic simulation, and paper mode.
4. Official read adapters and shadow mode.
5. Locked live execution, reconciliation, and operator controls.
6. Operations, deployment, backup, security, documentation, and evidence gates.

Each slice uses test-first steps, exact file paths, narrow verification commands, and focused
commits. A later slice may not bypass an earlier failed gate. Nonempty equity order/position
mapping evidence, an accepted strategy attestation, elapsed qualifying paper/shadow evidence,
micro-live observations and reviews, and normal-live eligibility remain gates until they actually
occur and are separately authorized.

The default remains paused and non-live. Prediction-market live execution remains unsupported. The system makes no profitability claim.
