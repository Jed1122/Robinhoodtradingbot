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

The first full run at990bce4 ended with12,860passes and one architecture failure:
the conservative capability scanner rejected a reflective sticky-field lookup.
The implementation now uses three explicit typed attributes with identical
semantics/error ordering. The architecture rule is unchanged. The observed
failure is retained; the full retry is still required before completion.

- [x] First full retry at `6606a590`: 12,861 passed, no failures/skips,
  36 warnings, 91.57% combined line/branch coverage; unchanged critical/host
  coverage gate passed. Native exit 0 and unchanged source inventory are retained
  in receipt `97b9482d228ca7038e7cc4d7fa576ab15418caaf6d3d19a518660bfcb0cd2c9f`.
  Repository Ruff, mypy (469 source files) and expanded Bandit also exited 0;
  existing Bandit annotation warnings remain visible.
- [x] Close the subsequent independent review's three adoption-history gaps:
  preexisting tax reserve release, active buy reservation release without a
  matching fill/cancellation, and lost partial-exit/allocation episode history.
  Preserve legitimate fill, settlement and cancellation operations.
  The 26 new rejection cases first failed, then passed after narrow guards.
  All 105 dividend-book cases passed on Python 3.12/3.14; 362 compatibility and
  architecture cases passed on both versions. Root independently reviewed the
  diff and passed 492 related cases, followed by 105 at the final source bytes.
  Focused Ruff, mypy and Bandit passed. Current full-suite CI remains required.
- [ ] Verify those corrections at their own source revision with the retained
  regression and unchanged coverage gates. The earlier pass does not cover them.
- [ ] Preserve actual terminal receipts and source identity, then integrate.

Before an actual monetary study, freeze the complete source admission and protocol:
currency/security context, lifecycle and distribution coverage, issuer-declared
versus broker-posted dates, settlement calendars, risk/sector/liquidity inputs,
tax/cost scenarios, all comparison families and reused-holdout limitations.
The original source gaps remain explicit. No source-wide qualification, fabricated
financial values or synthetic-data relabeling is permitted.
