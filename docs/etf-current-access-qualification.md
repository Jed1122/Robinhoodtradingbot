# Current-access ETF input and readiness checkpoint

Date: 2026-10-01. This checkpoint records narrower verified facts, not complete
source qualification, strategy acceptance, a profitable system or live readiness.
No new subscription, data purchase, broker write or deployment followed these checks.

## Available inputs

- Retained native Alpaca SPY SIP raw daily-bar capture: 2,514 records for the
  requested 2016–2025 period, complete recorded pagination and immutable response/
  receipt hashes. The reader never opens the credential path in the manifest.
- A fresh read-only Alpaca connector calendar returned 2,514 sessions. Every
  retained bar's exact New York date matched, with zero missing or unexpected
  dates. This is a provider-calendar comparison, not proof of complete symbol
  controls, native calendar transport receipts or regular-session-only prices.
- The retained public State Street workbook parses 40 SPY distributions in the
  explicit 2016–2025 window, four per year; 96 out-of-window SPY records are
  explicitly excluded and counted. Financial validation applies to the requested
  window; whole-archive ZIP/XML security checks still apply. No date is repaired.
- The previously recorded narrow quote probe demonstrates historical SIP access
  only. It does not cover all entries, monitoring, stops, exits or settlement.

Original publication/correction chronology is explicitly waived for latest-vintage
research under the October 1 operator amendment. Receipt time is not historical
availability; original versions are not invented and later-correction bias remains
disclosed. Calendar/source/action qualification flags remain false.

The public issuer source is [State Street's historical distributions workbook](https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx),
with [issuer distribution context](https://www.ssga.com/us/en/individual/resources/documents/etf-dividend-distributions).
Private retained inputs, financial values and receipts stay outside Git and Cloud agents.

## Execution-data boundaries

The current public API contract does not establish complete historical executable
state merely from successful quote pagination. Historical quotes expose prices,
sizes, exchanges, tape and conditions, but no sequence/gap, historical halt/LULD
events or quote-correction chronology. Zero prices mean an inactive side; conditions
are side-specific. Size units change from round lots to shares on November 3, 2025.
Raw archived sizes are not silently normalized or treated as universal share counts.
See [Alpaca historical quotes](https://docs.alpaca.markets/us/reference/stockquotes-1),
[condition metadata](https://docs.alpaca.markets/us/reference/stockmetaconditions-1) and
[size-unit change](https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change).

The connector calendar has naive projected local times and does not expose the
market/timezone options of the current v3 contract. Legacy v2 and current v3
schemas are not interchangeable. An omitted row is not a symbol-halt proof.
See [legacy calendar](https://docs.alpaca.markets/us/reference/legacycalendar) and
[current calendar](https://docs.alpaca.markets/us/reference/calendar-2).

Corporate-action API record/pay dates are optional, sorting uses process date,
and complete-quality responses can still include incomplete processed records.
No universal ex-date filter or current historical coverage guarantee is inferred.
See [corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1).
The public issuer import does not prove split/ticker continuity or every action type.

## Independent progression gates

| Gate | Current posture |
|---|---|
| Engineering | Account/lifecycle fixture and private checkpoint/restart increment reviewed; source adapters and exploratory references are separately verified increments. |
| Data | Hash/receipt-verified latest-vintage bars, exact provider-calendar date match and issuer distributions; executable/fractional/control/action continuity coverage remains unqualified. |
| Economics | No accepted candidate after-cost result. Mathematical reference marks and descriptive uncertainty cannot approve the strategy. |
| Broker session | Scoped read-only Agentic account/SPY observations succeeded; no review/place/cancel operation occurred. |
| Standalone runtime | Existing 2 GB droplet metadata read succeeded, SSH authentication did not; actual service health/image/authentication remains unverified. |
| Qualifying paper/shadow | Not begun by fixtures or daily-price reference calculations. Keep 100 eligible paper cycles and seven distinct UTC shadow dates unchanged. |
| Live authority | False. No automatic promotion, real-money test or production change. |

## Next steps

Finish exact-revision integration and regressions for the available-data research
commands. Continue implementing the causal strategy/risk owner using the common
account lifecycle and truthful data-quality denials, then calibrate and evaluate
actual matched after-cost candidate outcomes when executable evidence supports
them. Keep the final holdout untouched until independent acceptance criteria are
met. Complete broker/runtime and qualifying paper/shadow evidence separately.
Unknown facts remain unknown; the instruction to finish with current access is not
authority to fabricate them, increase risk or bypass a gate.
