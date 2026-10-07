# Broker recorder and historical coverage integration

Base: `6fab76f788f4e1810fc87a3e1dc61d9011083fa9`.
Coordinator branch: `codex/etf-recorder-coverage`.

## Scope and dependency chain

The operator has requested implementation of the broker/recorder integration and
remaining Alpaca history in parallel. Existing catalog, incremental replay,
private receipt sink, owned execution journal and economic journal are retained.

Current classification: those local foundations are implemented; authenticated
nonempty broker mapping, the complete recorder lifecycle, delayed fees across
process sessions and whole-study quote coverage are incomplete. Production
write capability remains blocked on independently verified behavior and runtime
composition. The existing diagnostic trade grant does not supply this evidence.

The coordinator owns execution, reconciliation, persistence, authentic provider
access and acquisition. A credential-free parallel task owns only a pure coverage
planner and its fixture tests. No customer data or credentials are delegated.

Critical paths:

1. Checked owned lifecycle -> same-session recorder fill/terminal projection ->
   immutable terminal checkpoint -> separate delayed-fee attachment -> replay and
   privacy/failure verification. Receipt failures cannot repeat an order or alter
   a committed economic outcome. Original execution clocks never change.
2. Frozen required intervals + verified retained capture inventory -> bounded
   uncovered requests -> existing native one-shot owner -> independent receipt
   verification -> resumable coverage accounting. An uncertain attempt is retained
   and blocks automatic replay; page-bound captures contribute no covered prefix.
   Empty completed responses remain explicit unqualified evidence.

## Frozen contracts

- Preserve historical wire schemas and hashes, exact Decimal arithmetic, one
  canonical risk configuration, local clock ownership and private file rules.
- Keep historical publication/correction and halt/LULD/gap waivers applicable to
  exploratory research; unavailable evidence remains unavailable.
- A lifecycle observer accepts checked local owned events after their durable
  publication. It uses the common lifecycle reducer and stable execution identity;
  duplicates preserve the first receipt and conflicts latch a denial.
- Fees require all explicit components and a retained source; aggregate observed
  broker charges cannot imply finality or missing component zeros.
- A later fee attachment references an immutable original terminal checkpoint.
  It cannot append to or rebase an earlier clock session.
- Historical requests remain SPY/SIP, ascending, USD, asof=-, half-open windows
  bounded by approved sessions. Dataset completion and request pagination are
  separate facts; no unqualified observation gains promotion eligibility.
- Acquisition must respect explicit request, duration, storage and disk-reserve
  budgets. Existing attempts and raw bytes are never removed to retry.

## Work and acceptance

- [x] Implement and review lifecycle observer completion with red/green tests.
- [x] Implement immutable delayed-fee attachment and fresh-process verification.
- [x] Integrate pure historical interval planning and test gaps, boundaries,
      incomplete attempts, empty captures and deterministic resume.
- [x] Freeze private acquisition inventory/plan; acquire only supported bounded
      requests and reverify original bytes. Record actual remaining coverage.
- [ ] Verify the available standalone broker surface and preserve any unsupported
      operations as explicit blockers; no declaration-only unlock.
- [ ] Run focused tests, Ruff, Mypy, relevant security checks and broad regression.
- [ ] Independent integrated review; update current handoff with implemented and
      externally unverified boundaries before publication.

Complete means demonstrated behavior and verified inputs. A finished local
implementation does not itself establish authenticated broker integration,
complete historical coverage, calibrated costs or live readiness.

## Current measured acquisition boundary

The first full eligible development session is privately captured and indexed:
78 complete requests, 2,563,121 quotes, 2,604 pages, 290,071,939 original raw bytes.
Remaining development request coverage is 1,261 of 1,262 sessions. See
`docs/etf-recorder-coverage-checkpoint-2026-10-07.md` for hashes and remaining
durable-acquisition, storage-budget and authenticated-runtime work. No qualified
economic or genuine customer execution-cost result was manufactured.
