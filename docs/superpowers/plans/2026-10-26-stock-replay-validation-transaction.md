# Owned validation transaction for stock replay

## Evidence and goal

The bounded fictional profile measured 1,445 full book validations for 32
advances with 195 retained trace rows and 64 marks. It also measured 610 book
constructions, including 416 discarded no-op adoptions used as validation.
Source parsers perform no work during advance. One 506-step fictional account
took approximately 22–23 minutes. These are software timings, not investment
results; profiler inclusive times overlap.

Remove repeated proof construction within one synchronous owned advance while
retaining full incoming and outgoing integrity checks. Implement this separate
increment only after the retrospective boundary's three correctness findings
have been corrected and independently accepted.

## Architecture and ownership

The engine owner may extend `stock_dividend_book.py`,
`stock_operating_costs.py`, `stock_economic_replay.py` and the narrow owner calls
in `stock_retrospective_replay.py`, plus a new transaction test module and the
existing new retrospective tests. Existing legacy tests and expected hashes
remain unchanged. Root owns documentation, integration and actual invocation.
Independent review precedes broader regression or any actual financial grid.

Use one explicit private book/cost transaction per case and advance. It is
created inside the synchronous owner call, never accepted by a public API,
serialized, retained across calls or stored globally. No caller-supplied trusted
flag or identity-only cache is introduced.

## Required invariants

- Freshly validate complete incoming generic-book and cost/phase/mark history,
  account, calendar and plan. Reuse that validation only inside the invocation.
- Reuse the existing transition arithmetic and trace construction. Validate
  owner-appended rows and new accounts against the checked predecessor: sequence,
  digest, time, account hashes, cash/tax/reserve/rung rules, unique identifiers,
  unchanged prefix and fixed calendar/tax/scope. A checked predecessor cannot
  make arbitrary new rows or accounts valid.
- Require exact current book, plan and clock for a reused cost summary. Any
  fill, settlement, credit, expense, reservation, adoption or closed-risk update
  invalidates the previous current-book proof. Same time or equal amounts do
  not establish ownership. Refresh summaries after such transitions.
- Keep net liabilities separate from the independently current equity/price
  observation. Net/hash/bind operations may reuse a checked cost result; they
  cannot reapply payments or reuse opening equity at the close.
- Fully validate the complete resulting history before publishing the outgoing
  seal. Preserve unknown liabilities, future-only-plan removal rejection,
  zero-plan phase ownership, sticky risk and exact depletion behavior.
- Keep public book/cost helpers, evidence properties, report, finish and resume
  freshly validated. Canonical tags, trace ordering, retained rows, economic
  outputs and literal legacy evidence preimages stay unchanged.

No callback, reentrant or asynchronous suspension may expose an active
transaction. This provides deterministic mutation detection within a pure owner
call; it does not authenticate arbitrary concurrent memory rewrites.

## Test-driven acceptance

- [x] Preserve the corrected boundary and original profile before extraction.
- [x] Add failing equality/mutation and deterministic work-counter tests.
- [x] Extract shared private validated workers, retaining public freshness.
- [x] Compare complete output projections against the fresh route for explicit
  zero, positive, unknown, deferred and underfunded costs; dividends; sales and
  settlement; all profit methods; and opening/closing risk flags.
- [x] Reject altered historical rows/marks/anchors, plans, accounts, cash/lots/
  orders/fills/risk, calendars and predecessors before the next call, and invalid
  new rows or same-clock foreign books/updates inside a transaction.
- [x] Measure the same 8/16/32-step fictional profile after correctness. Target at
  most two full book and cost-history scans per case/advance, no throwaway
  adoptions, and exactly the same retained appends, trace rows and marks. Count
  suffix-row validation and summary derivation explicitly; renaming work cannot
  satisfy a gate.
- [x] Run unchanged literal compatibility and relevant regression tests on
  Python 3.12/3.14, architecture and configured static checks; independently
  review the final increment before choosing any longer run.

The measured 32-step fictional profile retained 194 constructions, 195 trace rows
and 64 marks. It made 64 full generic-book, 64 cost-history and 64 tax-sum checks,
with no discarded validation-only constructions or redundant trace-prefix
comparisons. Instrumented wall time was 21.93 seconds versus the original
42.16 seconds. The original profile lacks a byte inventory; the visible fixture
and retained counts match, while implementation bytes intentionally differ.
Trace-row counters sum lengths at validator entry and do not count every
internal traversal. Independent correctness probes and profile audits passed;
the final scoped suite passed 417 tests on each Python version.

Full history checks per advance still produce growing-prefix work. No linear
horizon or runtime promise follows from this plan. A cross-call cache would need
a separate reviewed design. No source, quantitative threshold, tax/risk,
deployment or live-authority change belongs to this increment.
