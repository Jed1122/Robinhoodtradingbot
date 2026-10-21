# Hybrid equity research primitives

This additive subsystem is **partial, research only**. It has no broker, credentials,
execution, risk, promotion, or production persistence dependencies. It does not
establish profitability or permit strategy promotion. `research_snapshot()` performs
no I/O and returns an unknown regime, seven unavailable strategies, empty opportunities,
empty sources, and empty comparisons. Explicit typed inputs and UTC `as_of` are required
before descriptive research appears. The snapshot deliberately does not invent a macro
regime or automatically run comparisons.

The implementation dependency chain is structured source facts → availability filtering
→ screening and descriptive features → separately invoked illustrative comparison.
The integration application remains responsible for authenticating source provenance,
coverage, periods, price basis, universe membership, and freshness before using any output.

## Public-source normalization

`PublicResearchClient` requires an injected `httpx.BaseTransport`; it has no default
network transport, retries, redirects, credential inputs, or provider writes. Tests use
only `httpx.MockTransport`. Network use requires separately authorized caller composition,
including an appropriate SEC identifying User-Agent and provider rate limits. The optional
FRED adapter leaves any necessary authentication entirely to that external transport.
No key enters a returned source URL. HTTP failures return a generic error.

Schema references:

- [SEC submissions and XBRL company facts](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [FRED observations and realtime vintage fields](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)

SEC normalization supports four explicit USD concepts: assets, equity, net income, and
revenue. Duration start/end and accession are preserved in event identity; a quarterly
amount and an annual amount are never implicitly treated as interchangeable. Submissions
support only 10-K, 10-Q, and 8-K structured filing events. An 8-K is not automatically an
earnings event or an earnings surprise. Free-text labels, company narratives, and filing
text are discarded, never interpreted as instructions. The fixed HTTPS endpoints and
validated CIK/series identifiers prevent caller-selected arbitrary URLs.

`SourceFact` validates finite bounded Decimals, UTC periods and availability, and public
source URLs without queries or credentials. Exact duplicates collapse; conflicting values
for one event reject the entire input. FRED missing-value markers are skipped. Availability
is the later of receipt time and the next UTC midnight after date-only filing/vintage
information. Current fetched aggregates cannot be relabeled as historical point-in-time
evidence. Historical backfills need archived receipts and source verification outside this
module. Original public date fields have day-level precision; this conservative convention
does not assert an exact dissemination time. No source authenticity, complete history,
licensing, or freshness qualification is claimed.

## Screening and seven feature families

`screen_universe` accepts explicit positive price and dollar-volume thresholds from its
caller. Missing or future liquidity stays unavailable, duplicates reject, and low price
or volume is excluded. Research eligibility is unrelated to execution eligibility.
Thresholds are call parameters for experiments; no competing application config is added.
A complete point-in-time universe and exchange/listing metadata are not inferred.

All feature families require at least 21 ordered completed prices and reject future bars.
The fixed windows below are descriptive hypotheses, not tuned or validated strategies:

| Family | Descriptive score | Additional input |
| --- | --- | --- |
| Momentum | latest close / close 20 bars earlier - 1 | none |
| Trend | latest close / 20-close mean - 1 | none |
| Breakout | latest close / preceding 20-close maximum - 1 | none |
| Quality momentum | momentum × nonnegative ROE | supplied ROE |
| Mean reversion | 20-close mean / latest close - 1 | none |
| PEAD | supplied earnings surprise | point-in-time earnings-surprise fact |
| Revision momentum | supplied estimate revision | point-in-time analyst-revision fact |

PEAD and revision momentum are feature hypotheses only: no event-window trading policy,
consensus-estimate history, revision series reconstruction, or drift performance is claimed.
SEC raw financial facts do not supply consensus surprises or analyst revisions. Missing
inputs leave those families unavailable. Ratios and changes must be supplied as structured,
source-backed, period-matched facts by an upstream reviewed derivation. The module does not
derive ROE from arbitrary mixed-duration SEC amounts. Fundamental ranking requires ROE,
revenue growth, and debt/equity, and sorts their explicit illustrative combination
`ROE + revenue growth - debt/equity`; missing metrics do not get zero-filled.

## Comparison limits

`compare_returns` accepts binary, exogenous research targets and a matched benchmark,
executes each completed-close decision only on the next bar's open, accounts for overnight
returns on existing holdings, charges explicit one-way bps on entries/exits, and liquidates
at the final close with costs. The last decision is unexecuted. Optional explicit signal
availability timestamps reject signals known after their decision close. Without timestamps,
signal chronology stays unverified. The supplied bars must be uniquely ordered, finite,
positive and use the same benchmark completion timestamps.

Missing or mismatched histories return `insufficient_evidence`, without metrics. Computable
comparisons remain `illustrative_only`, including synthetic fixtures: fractional fully filled
allocations, unqualified open/close execution prices, no bid/ask or latency calibration,
no tax modeling, no statistical acceptance, and no verified corporate actions or universe
history. Cost assumptions are supplied explicitly and never calibrated from absent samples.
No Sharpe ratio, probability of profitability, or expected live return is fabricated.

## Verification and next steps

Local tests cover availability/lookahead, duplicates, missing fundamentals and estimates,
structured source parsing, deterministic features, screening, delayed execution, explicit
costs, and same-period benchmarks. These are synthetic/local checks only.

Before a meaningful study, integrate qualified market history, point-in-time universe and
corporate-action receipts; derive period-matched fundamentals; obtain legitimate historical
consensus and revision evidence; enforce explicit freshness and event-window policies;
register validation windows and cost assumptions; and run out-of-sample comparisons with
adequate sample sizes. Research output cannot automatically select an execution strategy.
No mandatory paper-duration rule is introduced. Any live authorization remains a separate,
explicit operator decision governed by the repository's existing controls.
