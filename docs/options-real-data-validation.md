# Options research and readiness checkpoint — 2026-09-30

This is a development checkpoint, not evidence of profitability, deployment, or live
authorization. The implementation remains paper/offline by default. No broker call,
order review, placement, cancellation, exercise, credential access, production migration,
deployment, data acquisition, or charge was made for this checkpoint.

## Independent verdicts

| Dimension | Verdict | Evidence and remaining gap |
| --- | --- | --- |
| Imported episode engineering | Implemented; final verification recorded below | Native-file fixture runs compose source verification, shortlist, shared momentum features, canonical entry feasibility, modeled lifecycle, independent journal and expiry exits. |
| Continuous full-policy research | Incomplete | An episode is not an ongoing account. Multi-session/account composition, ongoing liquidation marks and daily/weekly/drawdown history must precede full-policy qualification. |
| Actual historical sources | `BLOCKED_INPUTS` | The installed actual-source rulebook is empty. Actual native/reference semantic adapters and era evidence are not complete. |
| Genuine after-cost economics | `ECONOMIC_NO_GO` — insufficient evidence | No qualified real-price study ran. Effective-date costs, operating/cash benchmarks, dependent-outcome uncertainty and untouched holdout evaluation remain necessary. |
| Broker account and behavior | `UNVERIFIED` | Current declarations and dated empty reads do not establish nonempty order/fill/fee/settlement or account-restriction behavior. |
| Standalone runtime | `UNVERIFIED` | September 22 paused-host observations are historical, not a fresh unattended-authentication, renewal, restart or lifecycle verification. |
| Live authorization | Blocked | Development and credit-only purchase authority do not authorize real-money orders or live activation. |

## What the new episode runner establishes

`simulation/options_historical.py` accepts retained, hash-bound native inputs and a
privately frozen study, rather than caller-selected orders. It re-verifies source
preimages, joins the exact prior close and fixed call/put shortlist, prices both
candidates, and uses the existing 20/100 momentum hypothesis. Mixed signals produce
no candidate. Canonical integer sizing, cash, trial reservations, existing stricter
order limits, quote quality, tick and expiry controls remain active.

The engineering fixture uses manufactured DBN/Parquet data and fabricated calendar,
reference and calibration facts. It deliberately does **not** represent historical
market evidence. Its $10,000 capital tier is hypothetical; it does not change authorized
capital. Buying one 100-multiplier contract at $0.10 plus a $0.50 fee and closing at
$0.09 minus a $0.50 fee produces exactly **-$2.00**. The $100 case submits no intent:
the unchanged 0.5% per-trade budget is $0.50. Passing these assertions proves arithmetic
and integration for the fixture, not a trading edge.

Orders execute only at later eligible events. Rejection, no-fill, ambiguous acceptance,
settlement delay, expiry deadlines and open input-end exposure remain distinct outcomes.
The runner does not synthesize an end-of-file closing fill. Repeated records at one native
quote timestamp cannot replenish consumed liquidity merely by changing source ordinal,
receipt time or projection hash. XNAS archives reject other publisher identities.
Protective closes may rearm after a confirmed-terminal unsuccessful attempt, using
only a current owned-contract quote whose native timestamp is strictly later than
that terminal transition. Pending or unknown acceptance never permits a replacement.
Each new intent remains limited to the owned unit; the canonical event cap and frozen
outcome horizon bound the attempt count. This is offline lifecycle handling, not a
transport retry, live closing authority, or an increase in entry/exposure limits.

Restart has two separate offline contracts:

- The internal clock's bounded private JSON checkpoint replays closed actions and
  independently checks cash, reservations, orders, timers and consumed-liquidity state.
  It binds code/configuration, genesis, journal prefix, scenario and seed. It is not a
  pickle or trusted serialized balance.
- The public episode continuation receipt re-verifies retained source inputs and
  replays the exact event prefix before continuing from genesis. This is intentionally
  CPU-costlier than trusting a cached decision. It is **not production recovery** and
  cannot resubmit a broker order. Disk publication remains outside the repository,
  content-addressed and no-overwrite.

All episode results retain literal false production, promotion and economic eligibility.
The pure entry helper accepts loss-reason inputs, but the genesis-only episode does not
yet reconstruct ongoing loss history; it must not be advertised as a full risk runner.

## Genuine-data prerequisites and purchase boundary

The fixed research requirements remain unchanged: 750 observed warmup bars and a
3,650-day verified history span are separate requirements. The existing 2018–2025
underlying scope cannot alone establish the latter. A purchase receipt, valid byte hash
or operator permission does not establish historical publication/correction semantics.

For the smallest engineering pilot, select an eligible session from source/calendar
availability without inspecting prices or outcomes. Retain both fixed candidate
contracts' OPRA `cmbp-1` event quotes plus matching XNAS `mbp-1` SPY observations through
initialization, entry, monitoring, exit/expiry and settlement. Label the underlying feed
exchange-specific, not NBBO. Sampled CBBO-1m/EQUS.MINI estimates from September 22 are not
compatible substitutes for this consumer. Complete definitions, prior-close/warmup data,
sessions, actions/dividends, deliverables/ticks, dataset-condition metadata, availability,
correction and reset/gap semantics must be bound to retained evidence.

Current [Databento definitions documentation](https://databento.com/docs/schemas-and-data-formats/instrument-definitions)
describes daily snapshots; later intraday additions still cannot enter earlier decisions.
[OHLCV documentation](https://databento.com/docs/schemas-and-data-formats/ohlcv) distinguishes
interval timestamps from publication/correction behavior. The [OPRA supplement](https://databento.com/docs/venues-and-datasets/opra-pillar)
does not offer event-level CMBP-1 before March 28, 2023. [Historical reprocessing](https://databento.com/blog/opra-improvements-coming-soon)
makes acquired version/condition identity important. [Corporate-actions documentation](https://databento.com/docs/venues-and-datasets/corporate-actions)
supports point-in-time revisions; a latest-only default must not replace them.

These current public observations narrow implementation work; they do not install actual
source rules or prove historical completeness. No support outreach is planned. Existing
credit-only purchase authority remains recorded, but no current all-in package estimate,
applicable balance or cash-charge exclusion was verified here. Buy only after those
conditions and a usable complete package can be established.

## Separate broker/runtime declaration update

Do not overwrite dated negative findings. A September 30 public-document/catalog-only
audit found that Robinhood's [current official tool list](https://robinhood.com/us/en/support/articles/trading-with-your-agent/)
now lists `exercise_option` and `cancel_option_exercise`, also declared by `robinhood-2`.
This is public/session discovery only, **not** verified behavior or permission to invoke
them. Specific account/position/cash-impact confirmation would be independently required.
The same public page documents account trade-approval settings; runtime support must not
assume those settings or automatic placement. Connector order declarations still differ;
the initial single-leg long-call/put boundary is unchanged.

No current account or host state was read. Dated empty account collections do not validate
nonempty schemas, fill/fee mapping, intraday restrictions or settlement. Public onboarding
does not verify this deployment's unattended authentication, renewal, revocation, fencing,
monitoring, backup restoration or restart. The standalone options adapter and production
lifecycle composition remain incomplete, and `OPTIONS_LIVE_SUPPORTED=false` remains.

## Verification and remaining sequence

Local verification: 6,122 primary tests passed, with 33 skips and one pre-existing
Starlette warning; the complete native research selection passed 904 tests with no skips.
Combining primary and native episode coverage produced 88.99% overall coverage and
passed the unchanged 90% per-critical-file branch gate. The episode, clock, policy and
restart branches measured 47/48, 59/60, 8/8 and 16/16 respectively. Ruff, Mypy (282
source files), Bandit, both offline lock checks and diff checks passed. Native dependency
skips in the primary environment were covered by the research environment. Four encrypted
backup cases remain unverified because local `age` is unavailable. The SBOM test confirms
temporary reproducible output and preserves the tracked artifact; its current empty
component list is not a validated complete dependency inventory.

The operator separately approved a lockfile-only security fix: PyJWT 2.15.0 in both
environments and urllib3 2.8.0 in the main environment, committed as `58a5286`. No other
package entries changed. Both locked audits then found no known vulnerabilities; 113
offline broker/compatibility/smoke tests and bounded local dependency checks passed.
The primary/research full-suite runs above preceded this dependency-only update; the
16-test native coverage append and compatibility checks used the updated environments.
A subsequent full primary run at `0d80510` with the updated dependencies again passed
6,122 tests (33 skips, one existing warning). A fresh exact-head review independently
passed 336 focused tests and identified the same-session protective-close defect;
the subsequent correction is subject to new verification rather than inheriting those
earlier results.
These are local checkout results, not exact-head remote CI or deployment claims.

CI retains the 80% overall and 90% per-critical-file branch floors, combining primary
coverage with mandatory native-research episode coverage. No skipped source/runtime
work becomes approved because software tests pass.

Next: finish continuous account/risk composition; qualify actual-source protocols and the
complete usable pilot; add effective-date fee/operating/cash attribution and dependent
outcome/holdout evaluation; expose private study reports; then separately verify account,
adapter and standalone runtime behavior. Paper, shadow and explicit live authorization
remain later independent stages. This project is not yet complete or live-ready.
