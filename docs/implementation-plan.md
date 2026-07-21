# Robinhood Multi-Asset Trading System Implementation Plan

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
