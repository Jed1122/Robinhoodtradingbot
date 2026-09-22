# SPY underlying-data preflight — 2026-09-22 UTC

Status: estimates and source assessment only. No data request was submitted, no
credits were spent and no subscription was created. The temporary portal selection
created for these estimates was cleared and the portal showed no selected products.
Billing was not inspected; no fresh credit balance or hard spending limit is claimed.

## Fresh portal estimates

All three observations concern **SPY, XNAS.ITCH (Nasdaq TotalView-ITCH)**. Dates below
are UTC, start inclusive and end exclusive. The portal's end-date `24:00` means the
following midnight. These are displayed rounded estimates, not exact API prices.

| Schema | Start | End exclusive | Displayed estimate | Displayed size |
| --- | --- | --- | ---: | ---: |
| `bbo-1m` | 2023-01-01 | 2026-01-01 | $0.20 | 54.93 MB |
| `ohlcv-1m` | 2023-01-01 | 2026-01-01 | $0.35 | 31.39 MB |
| `ohlcv-1m` | 2018-05-01 | 2026-01-01 | $0.89 | 79.62 MB |

Source: the authenticated [SPY catalog estimate panel](https://databento.com/portal/catalog/us-equities/XNAS.ITCH/etf/SPY),
inspected under the existing estimates-only authority. No credential file or API-key
page was accessed. Public catalog samples were not used to evaluate strategy returns.

The longer bar request includes the shorter bar request: **do not buy both**.
The longer bar request plus minute BBO has a displayed **$1.09 underlying-only
subtotal**, not a complete research budget. It excludes options quotes, corporate
events, repairs, session enrichment and any applicable additional charges. It does
not establish licensed access, usable row counts or a maximum charge.

## Source fit and gaps

| Source | Public SPY history start | Limitation |
| --- | --- | --- |
| [XNAS.ITCH](https://databento.com/catalog/us-equities/XNAS.ITCH/etf/SPY) | 2018-05-01 | Nasdaq-only prices and volume, not national NBBO or consolidated volume. |
| [EQUS.MINI](https://databento.com/catalog/us-equities/EQUS.MINI/etf/SPY) | 2023-03-28 | Selected-venue derived BBO; misses pre-2023 warmup and early study dates. |
| [EQUS.SUMMARY](https://databento.com/catalog/us-equities/EQUS.SUMMARY/etf/SPY) | 2024-07-01 | Daily summaries/definitions/statistics; no matching underlying bid/ask history. |

The parallel public-source audit independently confirmed these dates and identified
the timestamp limitations below. It received no private account data or licensed
files. XNAS.ITCH is a plausible **venue-specific research candidate**, not an approved
replacement for national consolidated data. Coverage from 2018 cannot satisfy a
3,650-day history ending in 2023 or 2026; research requirements remain unchanged.
Actual usable history/session counts have not been measured.

## Timestamp semantics affect the design

Databento's [BBO/CBBO specification](https://databento.com/docs/schemas-and-data-formats/bbo)
identifies `ts_recv` as the interval-end label and `ts_event` as the last trade's
timestamp. Trade or quote components may be forward-filled. Neither is automatically
the last quote-update timestamp. This applies to the proposed underlying BBO and
option CBBO: a minute sample cannot prove quote age or intervening execution paths.
Do not map these fields mechanically into fresh executable `Quote`/`OptionQuote`
records or weaken existing freshness checks to accept them.

Ordinary [OHLCV](https://databento.com/docs/schemas-and-data-formats/ohlcv) is aggregated
using trade receive times; its timestamp labels the interval start. Daily buckets
use UTC dates, not the exchange's regular session. Minute bars can support a future
explicit regular-session aggregation, with verified calendar, gaps and availability;
that normalizer is not implemented here. Never make a completed bar visible at its
start timestamp or call a venue's last trade the official consolidated close.

## Remaining complete-package dependencies

- Historical contract mapping, chain membership and eligible sessions still require
  verification; native definitions alone are not normalized executable contracts.
- Corporate actions/dividends, as-of revisions and linkage remain unpriced and
  unverified. Databento's [corporate-actions product](https://databento.com/corporate-actions)
  describes a separate subscription offering. Do not presume this is included in
  usage-based price requests, costs $1 for a one-symbol base plan, or is covered by
  current credits. No subscription or reference-data request was made.
- The approved research-shortlist brief needs a written specification and review.
  No option symbols have yet been selected or priced using this rule.
- A final quote scope must retain exit/expiry coverage, disclose incomplete settlement,
  and be re-estimated with current credits before a separate acquisition decision.

No production code, configuration, risk limit, broker capability or deployment changed.
The current verdict remains `ECONOMIC_NO_GO`; this preflight is not a historical test.
