# Recorder and historical coverage checkpoint — October 7

This checkpoint records implementation and bounded acquisition, not live
readiness. The target remains the fixed SPY/cash ETF study with Alpaca data.
No broker review/place/cancel, real-money order, deployment, purchase or risk
configuration change occurred in this work.

## Local implementation

The reviewed lifecycle observer covers partial/final fills, cancellation races,
expiry and exact duplicate delivery. It rejects future facts, incomplete starting
anchors, mismatched ownership, duplicated fill identities and changed facts.
The joint accounting/receipt integration commits the existing SQLite economic
and execution journals before invoking the private observer. Interrupted or
failed recording cannot undo accounting or regenerate original receipt times.
Explicit final-fee component observations can be attached to closed recorder
sessions without changing their original clocks. Private `attach-fees` and
`link-costs --fee-attachment-hash` commands expose that offline path.

See [the lifecycle contract](etf-recorder-lifecycle-integration.md). These are
local, credential-free integration capabilities, not an authenticated Robinhood
adapter or real execution-cost sample.

The independent, pure [coverage planner](etf-capture-coverage.md) now partitions
required request spans into covered, missing, empty and blocked intervals. It
never credits a page-limited prefix or retries failed/uncertain intervals.
Its declarations require independent retained-receipt verification by the owner.

## Verified historical acquisition

Using the existing native one-shot owner at archived committed revision
`6fab76f788f4e1810fc87a3e1dc61d9011083fa9`, the coordinator completed the remaining
five-minute windows of the first eligible development session, December 26, 2018,
14:30–21:00 UTC. Each new request used a fresh consumed manifest and existing
Alpaca credentials locally; no credential or original licensed payload was
delegated or included in Git. The original first five-minute capture was reused,
not downloaded again. Every completed window was re-read through the native
manifest/receipt/raw-hash verifier.

The private catalog and calendar/bar comparison were independently produced
with archived committed revision `9abeddc04c87d7f424b51f3232df333aec11d2b2`:

| Measured item | Result |
|---|---:|
| Complete five-minute requests | 78 |
| Quote observations | 2,563,121 |
| Retained response pages | 2,604 |
| Original raw bytes | 290,071,939 |
| Complete requested development sessions | 1 of 1,262 |
| Remaining requested development sessions | 1,261 |

Calendar and daily-bar dates match. The 750-session warmup and pre-2024 development
boundary are unchanged; the 2024–2025 holdout was not evaluated. The resulting
five-minute-ceiling bisection plan contains 160,832 missing requests. Its request
count is a planning bound, not a latency, storage or acquisition-cost guarantee.

Private evidence identities, without source payloads or account identifiers:

- Catalog: `0e0acdc15f28359fb558a6fec3a7ac31ee6b74b828abed3e3579060507e12715`.
- Day index: `661b38e53f1796bb0977e1c222bc15f018535f360091c81b952479a300fb65f7`.
- Inventory: `18de3f4b3a38b10d2d5b85aa5237cba6675518aa6efed7ad11b7a210a646f274`.
- Plan: `fc7f6a1504914764797043b1b3d21164a82832a53d0a001b2816c3dde64ab4c6`.

The inventory records about 261 GB free at capture time. Extrapolating this one
session's 290 MB across 1,262 sessions would be about 366 GB raw, before overhead;
this is an uncertain sizing estimate, not measured full-study demand. Unbounded
bulk acquisition must not exhaust the user's disk. A reviewed compressed/archive
and acquisition-budget design is needed before the whole-study run. Existing
original bytes are preserved; no cleanup or deletion was used to create space.

Complete request pagination does not establish all market ticks, executable
sizes, dated condition semantics, fractional execution terms, corporate-action
coverage, final customer costs or accepted economics. Existing publication and
halt/LULD/gap waivers remain applicable to exploratory research. They are not
reintroduced as exploratory blockers, and missing facts are not invented.

## Remaining work and independent gates

1. Integrate durable acquisition intent/outcome recovery and explicit aggregate
   storage/time budgets with the coverage planner, then finish the remaining
   development session requests without touching holdout outcomes. Adaptation
   requires verified page-limit chains, never a claimed callback success alone.
2. Establish authenticated nonempty broker mappings and operation-specific
   review/place/cancel behavior on the actual standalone runtime, plus protected
   pre-send reservations, final risk/fencing and recurring worker composition.
   Codex-session schemas do not establish that runtime capability.
3. Obtain genuine causally recorded executions and final fee documents through
   that protected, independently authorized path. A legacy CSV or manual fill
   alone cannot reconstruct the original decision/submission/arrival clocks.
4. Run the frozen after-cost evaluator with accepted input/cost evidence, then
   separately verify qualifying paper/shadow operation and deployed recovery.

Source/cost qualification, authenticated integration, calibrated economics,
promotion eligibility and live readiness remain unestablished. A local passing
test, full request span or merged PR must not be reported as those outcomes.
