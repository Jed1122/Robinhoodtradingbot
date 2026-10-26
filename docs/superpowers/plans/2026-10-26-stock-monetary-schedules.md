# Finite schedules for retrospective stock portfolio research

Continue the approved lean first release by connecting retained stock observations
to the existing accounting engine. This increment supplies calendar facts for
that connection; it does not run a strategy, grant source qualification or enable
trading. Keep actual inputs separate from fictional fixtures and preserve all
unavailable constrained comparisons.

## Architecture and ownership

Add one pure research module, `research/stock_replay_schedule.py`, with immutable
packet, rule, schedule and unavailable-result types. The existing daily-calendar
parser owns the original market rows. The new module retains complete source
bytes, exact transcription spans and separate market, ordinary CNS settlement
and dividend-funding axes. One preparation validates each packet and builds
compact date tables; due-date helpers consume those tables. No new service,
dependency, provider call or second cash ledger is required.

The engine worker owns that module and its new unit test. An independent reviewer
owns the retained-source inventory and then reviews the implementation. Root
integrates the documentation, independently checks the composed behavior and
verifies the final source. Existing accounting and fictional-replay interfaces
remain unchanged in this increment.

## Fixed conventions before outcomes

- Preserve the exact native 706 market sessions ending October 23, 2026.
- Add calendar-only padding through November 12, 2026. No padded row supplies a
  price, volume, strategy observation, fill or additional return.
- Restrict the ordinary-equity settlement model to post-May 28, 2024 T+1.
  The first permissible trade is October 17, 2024.
- Model sale cash at the first known market open strictly after its supported
  settlement date. Unknown counting days or intervening market days keep that
  date unavailable; do not skip them to obtain a later convenient date.
- Require separate funding support for both a dividend's native pay date and
  the exact first market open after it. Otherwise retain an earned receivable.
- Keep fetched originals, indexed primary extracts and conditional normal-weekday
  assumptions distinct. A failed HTTP body is not an original service notice.
- Bind original bytes and exact source spans. Missing original capture clocks
  remain missing; a later file-save time cannot replace them.
- Retain unknown and conflicting service facts. Facility opening does not imply
  ordinary settlement or dividend funding. Dividend funding defaults to unknown.
- Keep all qualification, investment eligibility and live-authority fields false.

## Implementation and verification

- [x] Write failing fictional tests before implementation, covering the native
  prefix, padding boundaries, source hashes/spans/clocks, unknown/conflicting
  dates, DST and output authority flags.
- [x] Implement finite preparation and fresh result revalidation, with bounded
  inputs and invocation-local packet validation rather than per-date source
  rehashing.
- [x] Test January 9, 2025 exchange closure with settlement open; Columbus and
  Veterans exchange sessions without CNS settlement; limited Good Friday; and
  July 3, 2026 ordinary settlement versus dividend funding.
- [x] Test terminal sale claims and post-horizon dividend candidates without
  extending the price horizon or assuming a 2027 schedule.
- [x] Run new and relevant existing calendar/accounting tests on Python 3.12 and
  3.14, plus architecture, lint and typing checks.
- [x] Independently review source semantics and behavior, correct material
  findings, and verify the final integrated diff.

The corrected increment passed 276 focused cases on each Python 3.12 and 3.14,
168 architecture checks and configured static checks. Independent review passed
72 new tests and 654 separate probes on each version. A stored trade-date
consistency finding was reproduced and corrected before acceptance. The actual
17-packet input assembly has a separate source-only receipt; it did not invoke
the schedule factory or compute financial outcomes. Complete regression and CI
still follow the committed integration.

## Subsequent required work

After schedule acceptance, add a distinct retrospective input profile and reuse
the same account/lot/dividend/cost engine. Wire original price/volume prefixes
and accepted annual evidence without inventing historical risk fields. Freeze
the actual source, code, protocol and cost/comparison manifests before calculating
portfolio outcomes.

The full seven-family, long-term quality, hybrid, exit, reinvestment, benchmark
and statistical evaluation remains unfinished. Missing required evidence remains
explicitly incomplete. No mandatory prospective paper wait or elaborate
operational drill is introduced; live activation remains a separate user decision.
