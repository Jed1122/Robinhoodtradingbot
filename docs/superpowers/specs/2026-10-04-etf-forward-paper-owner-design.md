# Versioned forward paper owner and joint recovery

## Intent, scope and readiness

Continue the operator's native ETF build without repetitive approval prompts.
This is architectural work under the standing uninterrupted-build authority,
not deployment or trading authority. The current harness has no Plan Mode switch;
this saved design and its implementation plan provide the planning boundary.

The sealed historical study and account replay are implemented. A growing forward
economic owner is absent; the paper promotion composition is blocked. Historical
source qualification and actual customer costs remain blocked by evidence, not
operator approval. The critical software path is a new forward identity → shared
economic reducer → durable joint prefix verification. Source/cost qualification
is independent and must not be relabeled as passed by this increment.

## Selected approach

Use a separate `etf-forward-paper-v1` plan, cycle tape and private atomic owner.
The plan freezes the canonical policy, code/config identity, a bounded forward UTC
window, capital and simulated provenance. Future cycles do not change plan identity.
The existing historical dates/types/serialized identities remain unchanged.
Reusing the historical request by widening its dates is rejected. Coordinating
multiple independent stores would add partial-restore hazards; a single joint
commit is preferable for this transport-free increment.

This owner consumes explicit fictional economic cycle inputs. It does not claim
to produce or verify strategy signals, executable market observations, genuine
fills or accepted research. Strategy/input hashes are recorded diagnostic bindings,
not authentication. No native Alpaca frame is converted into a synthetic fact.
The future qualified strategy factory and recurring worker remain separate.

## Models and economic reuse

`ForwardPaperPlan` contains an exact validated historical `EtfStudy` as a frozen
canonical-policy reference only, explicit `starts_at`/`ends_at` (both on/after
2026-01-01 UTC, at most 31 days), and hypothetical initial cash of $500 or $1,000.
The nested study is never edited; its dates still denote historical research.
The $100 risk reference and all canonical controls remain unchanged.

`ForwardPaperCycle` contains its causal UTC boundary, source-receipt identity and
monotonic cursor, a diagnostic strategy-state hash and explicit `EtfAccountEvent`
facts. Source progress may occur with no economic mutation. The internal account
namespace remains `etf-offline`, never a customer account. Every cycle/receipt
and economic identity is bounded, reconstructed and serialized canonically.

`ForwardPaperTape` validates exact types, chronological/append-only source and
economic cursors, the forward window, and a maximum of 1,000 cycles/10,000 economic
facts. Explicit unknown orders/reservations/unsettled obligations survive end of
input. Complete tape replay reuses the sole account reducer, with an explicit
origin time and independently domain-separated run identity; no second sizing,
exposure, fee, trial-loss, settlement or loss calculator is created.

## Durable joint owner

The owner uses an existing owner-private root outside the repository, fixed new
namespace, descriptor-relative no-follow I/O, 0600 files and 0700 directories.
Hold a nonwaiting single-host flock through reconstruction and publication.
An immutable owner marker binds the plan. Every new sequence first durably claims
the candidate prefix before calculation, then publishes one immutable commit
containing the full consumed tape, replayed account, source cursor, diagnostic
strategy binding, previous head and nonqualifying observation. No callback or
broker capability can be injected into this owner.

Recovery replays all committed prefixes from retained inputs, comparing exact
canonical bytes and hashes rather than restoring cash alone. This preserves
deduplication, trial episodes, peak/day/week loss history, reservations and latches.
The original typed tape must remain available; stored inputs are verified against
it, not decoded into trusted new facts. An incomplete claim is quarantined; no
timeout or missing commit permits re-execution. A fully published commit followed
by a sync error is recovered exactly on retry. Required caller `expected_head`
detects stale writers and partial rollback when the external head is retained;
hashes alone cannot detect complete host rollback or same-UID compromise.

Recovery never advances new cycles. `advance` verifies the whole prior prefix,
rejects shortened/conflicting inputs, then admits only the next prefix. All states
remain paused; source/cost/execution/promotion/live eligibility stay false.
The new namespace is not covered by the old deployment backup script; preserve
the complete private namespace AND original tape jointly. No production backup,
migration, deployment or restart drill is included.

## Qualification and verification

Privately rehash existing historical archives and rerun the existing input/cost
assessment commands from a clean committed revision. Preserve missing vs explicit
zero and separate source from cost verdicts. No downloads, provider writes,
history polling or test trades are authorized. Report exact retained coverage
and supported charges only; absent fills and local order clocks remain absent.

Test forward dates versus sealed historical rejection; independent cash-flow
expectations; pending/partial/cancel/uncertain/unsettled states; cumulative losses
without profit replenishment; future-prefix stability; stale head, conflicting
duplicate, plan/code/config mismatch, concurrent owners and corrupt/partial state;
failure before/after atomic publication; process restart; and private I/O denial.
Run scoped RED→GREEN tests, local full regression, Ruff, Mypy, Bandit, frozen
dependency/security checks and manifest checks. No green offline test grants
trusted paper/shadow composition or live eligibility.
