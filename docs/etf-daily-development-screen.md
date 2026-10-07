# Fixed daily ETF development screen

This is a separately identified, permanently non-promotable SPY/cash research
screen. It cannot satisfy the legacy 750-bar study, qualify data or customer
costs, authorize an order, or satisfy paper/shadow promotion. Live remains blocked.

## Frozen inputs and assumptions

The receipt-verified Alpaca daily archive must match the saved 2016–2025 calendar
and 40 issuer distribution quarters. Inventory validation includes retained
2024–2025 records, but only pre-2024 prices/distributions enter the evaluator.
Original publication/correction chronology and historical controls remain
unobserved. Full-window date matching is not executable-data qualification.

The first decision is May 26, 2016, using 100 completed prior bars; scheduled
entries repeat every five supplied sessions. Features reuse the full canonical
20/100 momentum predicate. ATR uses the same 100-bar slice; stop/target, maximum
holding and regime exits retain canonical settings. Raw unadjusted prices are
used separately for assumed execution and feature input under an explicitly
unverified no-splits assumption. Session-close availability, fractional units
and T+2 session settlement are assumptions, not broker facts.

Execution is next-session adverse opening price. A gap below a stop receives the
worse opening price, and a daily range crossing both stop and target receives
the stop first. Missing sessions interrupt rather than invent fills. Full
cash/trial/fee reservation and the shared account reducer remain authoritative;
generic sizing does not evade an account admission denial. No additions or
terminal forced sale occur; open positions/receivables/settlements stay incomplete.

## Economics

All $500/$1,000 tiers and 0/5/25-basis-point cost assumptions are reported without
selecting a winner. Explicit assumed per-side fees are charged once; spread and
slippage are embedded once in prices, not subtracted again from NAV. Current
$0/$99 data and $0/$12 compute budgets are counterfactual operating scenarios,
not historical bills or verified cheaper account access. Whole monthly renewals
start on the first decision date; sunk research costs and measured cash yield
remain unknown. Cash yield is assumed zero.

The mathematical constrained buy-and-hold reference matches retrospective mean
dollar exposure up to the canonical cap; it is not a tradable allocation or risk
approval. Paired uncertainty uses fixed-capital daily P&L fractions and the
existing seeded 20/100-session block protocol. Completed episodes and bootstrap
draws do not establish independent opportunities. Daily close drawdown/occupancy
does not establish intraday protection or recovery.

`REJECT`, `INSUFFICIENT_EVIDENCE` and `PROCEED_TO_FURTHER_RESEARCH` are screening
verdicts only. Economic admission and source/cost/execution/promotion flags are
always false. Untouched final testing needs eligible sources and protected actual
cost calibration first; this command has no holdout or qualification override.

## Private command

Use existing private captures and reference files (`calendar.json` and
`ssga-distributions.xlsx`) with their verified hashes; do not paste secrets.

```sh
PYTHONPATH=src uv run --frozen python -m trading_bot.cli.etf_research daily-screen-run \
  --capture-dir /absolute/private/capture \
  --manifest-hash CAPTURE_MANIFEST_SHA256 \
  --reference-dir /absolute/private/references \
  --calendar-hash CALENDAR_BYTES_SHA256 \
  --issuer-hash ISSUER_WORKBOOK_SHA256 \
  --report-dir /absolute/private/reports \
  --config-dir configs
```

The existing canonical configuration loader is used; no alternate risk loader or
credential/network transport is constructed. A content-addressed preregistration
is published before evaluation. Reports are outside Git, current-user owned and
mode0600 in a private0700 directory. Publication retains the verified directory
descriptor even if its pathname is replaced. Stdout contains sanitized hashes,
verdict counts and false flags, not raw prices, fills or customer data.

If the candidate fails, stop unnecessary data/execution expansion. If it survives,
the next work is eligible-source and protected cost evidence, untouched final
testing, trusted paper/shadow and chosen-runtime recovery, followed by separately
authorized bounded live operation. No profitability claim follows from this screen.
