# Repository orchestration rules

This repository is an existing, safety-gated Robinhood multi-asset trading system. Extend it in place. Do not restart it, replace its architecture, or describe planned behavior as implemented.

## Persistent authority and safety rules

- The primary orchestrator owns the integration branch, dependency graph, final review, and release decision.
- The operator has authorized automatic integration and merging of in-scope project work without another per-merge approval. Review the exact diff and current CI first; do not bypass checks, include unrelated dirty work, or interpret a merge as deployment/live authorization. The standing grant and established integration target are recorded in [Operator authority](docs/operator-authority.md).
- The existing Databento grant covers necessary historical data using all remaining authorized credits, without another per-purchase approval inside that scope. Verify exact coverage, fresh applicable credits, outstanding charges, and the complete quoted cost before submission; no cash spending, subscriptions, upgrades, or new agreements are included. See [Operator authority](docs/operator-authority.md) and the [acquisition controls](docs/options-data-validation-handoff-2026-09-25.md).
- The default service stays paused, fail-closed, and unable to submit orders.
- Live operation is explicit opt-in only and remains blocked until every documented promotion, authorization, lease, reconciliation, runtime-control, and manual-review gate is satisfied.
- Never weaken or bypass risk limits, capability boundaries, evidence requirements, code/config identity checks, or elapsed-time gates.
- Never introduce martingale behavior, averaging down, hidden size escalation, or automatic recovery that can increase exposure.
- Do not claim or imply profitability in code, documentation, logs, tests, or reports.
- Treat the Robinhood OAuth bearer credential as trading-capable. Never call it read-only.
- Never place secrets, tokens, authorization headers, signatures, private keys, account identifiers, production payloads, or production-ledger contents in Git, task prompts, fixtures, logs, or Cloud workspaces.
- External broker calls, credential operations, production-ledger access, DigitalOcean mutations, and live-mode operations require separate explicit operator authority.

The detailed implementation and safety contract remains in [Codex.md](Codex.md). Review these documents before changing their domains:

- [Architecture](docs/architecture.md)
- [Capability matrix](docs/capability-matrix.md)
- [Known limitations](docs/limitations.md)
- [Live activation gates](docs/live-activation.md)
- [Risk policy](docs/risk-policy.md)
- [Strategy research requirements](docs/strategy-research.md)
- [Operations runbook](docs/operations-runbook.md)
- [Threat model](docs/threat-model.md)
- [Incident response](docs/incident-response.md)
- [Disaster recovery](docs/disaster-recovery.md)

## Before substantial work

1. Inspect the current branch, exact base revision, worktree status, and relevant tests and documentation.
2. Preserve unrelated work. Do not overwrite or fold another task's dirty changes into your task.
3. Classify the affected subsystem as complete, partial, blocked, deprecated, or unverified.
4. Write the dependency chain and identify the critical path before implementation.
5. Split only genuinely independent, non-overlapping work. Keep sequential or shared-state changes under one owner.
6. Establish a task contract before delegation.

## Delegation boundaries

Cloud or parallel agents may receive self-contained, secrets-free work based on an exact committed revision. Never assume the repository's default branch contains the current integration state. Good candidates include documentation, fixture-only parser tests, static audits, CI portability, coverage analysis, research-bias review, data-provenance design, simulation tests, and observability design.

Keep these components under one authoritative owner and do not delegate decisions about them:

- strategy selection, pricing, sizing, exposure, and risk gates
- live runtime composition and mode transitions
- broker review, place, replace, or cancel behavior
- authorization, leases, leadership locks, and kill controls
- reconciliation, recovery, and submission idempotency
- production persistence schemas and promotion evidence
- credential handling and authenticated provider evidence
- safety-envelope and live configuration
- production deployment, executing-image attestation, and rollback state

Use separate branches or worktrees for parallel implementation. Freeze shared interfaces in the task contract. Parallel agents must not edit integration branches, rebase other work, broaden their path ownership, or perform external writes.

## Required task contract

Every delegated task must state:

- **Objective:** one bounded outcome.
- **Owner:** one task and one responsible agent.
- **Base revision:** exact commit SHA and branch/worktree assumptions.
- **Owned paths:** the only files the agent may modify.
- **Read-only dependencies:** files it may inspect but not change.
- **Frozen interfaces:** names, schemas, flags, and behavior that must not move.
- **Prohibited actions:** especially broker calls, secrets, live controls, risk changes, and deployment writes.
- **Acceptance criteria:** observable conditions for completion.
- **Verification:** exact narrow and broad commands.
- **Return contract:** summary, diff/commit, tests, assumptions, risks, unresolved blockers, and an explicit `READY_FOR_INTEGRATION` or `NOT_READY` disposition.

If ownership or interfaces overlap, do not run the tasks in parallel.

## Integration and review

- Agents return commits or review findings; they do not declare a release safe.
- The primary orchestrator inspects every diff, checks ownership, resolves conflicts deliberately, and reruns relevant tests centrally.
- A change is not complete while required CI is red, evidence is missing, external verification is unperformed, or documentation overstates capability.
- Run the narrowest relevant tests first, then the repository baseline:
  - `uv run ruff check .`
  - `uv run mypy src`
  - `uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80`
  - `uv run bandit -c pyproject.toml -r src`
  - `uv lock --check`
- Record skipped or externally blocked checks explicitly. Never weaken a check to obtain green status.
- Before any deployment, verify the exact immutable image digest, executing-image attestation, paused health, readiness denial, live-disabled metrics, rollback metadata, and absence of unintended secret or ledger mounts.

## Current transition snapshot

The authoritative handoff is [PARALLEL_ORCHESTRATION_TRANSITION_REPORT.md](PARALLEL_ORCHESTRATION_TRANSITION_REPORT.md). It records current blockers, GO/NO-GO state, critical path, protected components, and Cloud-ready task contracts. Refresh it when those facts materially change.
