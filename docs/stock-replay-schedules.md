# Retrospective stock replay schedules

`trading_bot.research.stock_replay_schedule` prepares finite, conditional calendar
tables for the stock portfolio study. It preserves the original 706 market
sessions from January 2, 2024 through October 23, 2026. Calendar-only padding ends
November 12, 2026 and supplies no prices, volume, signals, trades or extra returns.
The module has no account, network or broker interface.

## Source boundary

`prepare_retrospective_replay_schedule` accepts an original `StockDailyCalendar`,
immutable source packets and the fixed `RetrospectiveScheduleRule`. It freshly
parses the original calendar and checks packet bytes, hashes, source spans,
representations, clocks, axis-specific vocabulary and finite date coverage.

Packets retain complete successful original HTTP bodies or complete indexed or
rendered primary-source receipts. Original HTTP bodies require status 200.
Indexed receipts retain their own representation and have no original HTTP
status. Optional outer-receipt hashes and companion manifests distinguish a
retained receipt file from its decoded source text. Missing capture clocks stay
missing. Neither a file-save time nor a document publication date replaces them.

Exact byte spans bind reviewed transcriptions. The vocabulary check is narrow;
it does not independently establish the meaning, origin or completeness of a
document. Source hashes and URLs are caller-declared integrity bindings. Failed
HTTP bodies cannot supply service eligibility. Anticipated holiday tables do not
establish that every later service amendment is known.

## Three independent service tables

Market, ordinary CNS settlement and dividend funding each have a separate dated
table. Rows retain native-calendar, reviewed-source, modeled-weekday, unknown or
conflicting provenance and the applicable compact packet commitments.

The fixed rule permits named normal-weekday assumptions only inside the supplied
source coverage. Future regular sessions use 09:30–16:00 America/New_York under
an explicit model, including DST conversion. These are conditional schedule
rows. The original market-session prefix remains unchanged.

Service-specific notices can resolve an annual limited-service entry. Equal
priority contradictions remain conflicts. A general facility opening or CNS
settlement day does not supply dividend-funding support. Dividend funding
defaults to unknown.

Examples requiring separate axes include January 9, 2025 exchange closure with
ordinary settlement, exchange sessions on Columbus and Veterans holidays, and
limited holiday services. Every interpretation retains its original or indexed
source provenance. Such examples do not establish full historical coverage.

## Conservative claim dates

`modeled_settlement_availability` accepts only native executable session indices
200 through 705. The fixed post-May 28, 2024 rule counts one supported settlement
day after the trade. Modeled cash becomes available at the first known market
open strictly after that settlement date. An unknown, conflicting or unresolved
limited-service counting day keeps the date unavailable. Padding cannot create
another executable trade.

`modeled_dividend_availability` requires separate positive funding support on
both the native pay date and the exact first market open after it. An unknown
intervening market day blocks that candidate; unknown funding cannot move cash
to a later convenient day. The accounting consumer retains any earned right as
a receivable. These dates are conservative research timing, not broker posting
attestations.

## Validation and consumers

Consumers call `revalidate_replay_schedule` at their source boundary. It rebuilds
the schedule from complete retained bytes and rejects altered derived state.
Claim queries verify compact consumed date commitments instead of rehashing
complete documents for every order. These checks address inconsistent stored
state; they do not authenticate an arbitrary wholesale rewrite of an in-memory
object and its commitments.

An incomplete market tail or contradictory native market evidence produces a
derived unavailable status. Invalid original bytes, types or bindings raise
`ReplayScheduleError`. Every source-qualification, strategy-qualification,
investment-eligibility and live-authority flag remains false.

This increment supplies an input dependency for the distinct retrospective
portfolio boundary. Actual monetary comparisons, full source admission and the
complete strategy study remain separate unfinished work. Live execution remains
disabled.
