# Stock monetary inputs: preparatory increment

This increment continues the complete Task 5 strategy/portfolio evaluation.
It adds full-panel source validation and a research-only cash distribution book.
It does not admit an actual dollar backtest, qualify a strategy or enable trading.
The seven required families, portfolio, exits, reinvestment and statistical audit
remain in scope. There is no mandatory paper-trading waiting period.

The prior price-only result is frozen at source86f35b21 and PR56 head6b5b2e9.
Its 12,758-test regression, native study exit and independent numerical audit
passed. The first trend rule demonstrated no edge. This increment must preserve
those historical artifacts and cannot optimize that holdout into a new claim.

## Source panel

- [x] Add `parse_cash_dividend_panel` to the existing economic evidence adapter.
  Validate every original CSV row and global IDs before partitioning. Keep the
  complete original hash on every view; preserve single-symbol compatibility.
- [x] Test mixed symbols, empty views, unknown symbols, duplicates/conflicts,
  altered bytes, unknowns, decimal contexts and permanent nonpromotion.
- [x] Independently review the change and run focused portability/static checks.

## Research dividend book

- [x] Add a pure immutable `research/stock_dividend_book.py` around the existing
  experimental Account. Derive entitlement from a bound prior-ex lot snapshot.
  Record modeled ex/payment clocks separately from the original receipt clock.
- [x] Keep receivables outside buying power. Credit known calendar-bound modeled
  payments once; unknown payment availability remains a receivable. Separate
  dividend income, modeled taxes and capital gains; preserve lots and basis.
- [x] Test ownership/clock causality, ex-date sales, changing current holdings,
  delayed/unknown payments, duplicate/conflicting events, reservations, tax
  assumptions, exact conservation and independent decimal contexts.
- [x] Independently review; no fake quotes, broker permissions or live account.

The book factory binds calendar sessions, their source hash and the explicit
account snapshot time. Account adoption is an externally modeled transition;
it preserves prior fills/orders, sticky risk state and earned dividend rights.
New settlement claims must bind a matching appended sell fill and net proceeds.
The independent review's unsupported-settlement cash-creation defect was
reproduced, fixed and verified before integration.

The existing same-symbol wash-sale awareness helper also now compares inclusive
U.S. calendar trade dates. The original 720-hour calculation missed a purchase
late on calendar day30. Both before/after failures were reproduced, corrected
and independently reviewed against IRS Publication550. This does not determine
cross-account/substantially-identical treatment or final basis adjustments.

## Integration and remaining boundary

- [ ] Run the complete retained stock/shared regression and unchanged coverage
  gates after both components are frozen, plus applicable static checks.
- [ ] Preserve actual terminal receipts and source identity, then integrate.

Before an actual monetary study, freeze the complete source admission and protocol:
currency/security context, lifecycle and distribution coverage, issuer-declared
versus broker-posted dates, settlement calendars, risk/sector/liquidity inputs,
tax/cost scenarios, all comparison families and reused-holdout limitations.
The original source gaps remain explicit. No source-wide qualification, fabricated
financial values or synthetic-data relabeling is permitted.
