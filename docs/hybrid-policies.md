# Frozen v1 equity research policies

`hybrid_policies.evaluate_policies(PolicyInput)` is an independent, pure hypothesis
module. It produces immutable `StrategyProposal` or `UnavailablePolicy` records, never
broker orders. There are no broker, risk, persistence, credentials, networking, or LLM
inputs. `qualified=False` is an invariant, and the proposal version is
`hybrid-policy-v1`. These policies have not been tuned against retained study results.
No profitability, validation, promotion, or live authorization follows from a proposal.

## Observation contract

The caller supplies immutable tuples of:

- `CalendarSession`: consecutive integer session identities and explicit UTC open/close
  timestamps, including the next session. The caller must supply a verified exchange
  calendar and `calendar_verified=True`. The flag declares caller verification; this
  module does not authenticate it. Calendar-day arithmetic never substitutes for sessions.
- `SessionObservation`: symbol, session identity, existing immutable `PriceBar`, and
  observed share volume (or explicitly missing volume). Each bar completion must equal
  the identified session close. Every required history window must be consecutive through
  the decision session; missing observations are never interpolated.
- `UniverseMembership`: effective and available UTC timestamps, inclusion flag, and source
  event identity. Only records effective and available by the information cutoff enter
  the universe. The latest visible record controls inclusion; conflicting records reject.
- Existing `SourceFact` financial metrics with point-in-time availability and source
  references, and `PolicyEvent` structured earnings surprises or estimate revisions.
  No company narrative or natural-language recommendation is consumed.
- Optional explicit `(symbol, family)` held-position identities. These are caller
  declarations for research decisions, with no account identity, size, or broker state.

The information cutoff must be after a completed session close and before the next
session opens. Proposals carry `information_at` and `execute_not_before` equal to that
next verified session open. A completed-close change never proposes execution on that
same bar. A missed next-session window rejects rather than inventing an earlier fill.
A proposal is a decision, not a fill; execution prices, gaps, liquidity, account funding,
risk approval, reconciled holdings, and order authority remain outside this module.

Future bars, facts, or events reject the entire request, including observations unrelated
to a particular family. Exact duplicate bars/events collapse; conflicts reject. Event
identity is symbol plus event ID; changing an event's type/value/timestamp under that
identity is a conflict. Event anchors cover the identified session open through, but
excluding, the next session open: an after-hours or next-premarket release belongs to
that preceding session anchor. Its actual occurrence and availability timestamps must
already be known at the information cutoff. This allows confirmation at the following
session close without backdating a release to an earlier tradable moment.

Provider authenticity, complete universe/event coverage, financial derivation correctness,
corporate actions, adjusted price consistency, source licensing, and freshness are caller
responsibilities. An event list is supplied evidence, not proof of complete event history.
The output never asserts those properties or silently fills their gaps with model data.

## Frozen hypotheses

All thresholds below are explicit experimental v1 rules frozen before evaluation.
They are not a competing application configuration schema or accepted production policy.
Holding-session ranges are stated research horizons, not broker deadlines or enforced
position-age controls; this interface does not receive an authoritative lot age.

| Family | Entry hypothesis | Required observations | Holding horizon |
| --- | --- | --- | --- |
| Cross-sectional momentum | Positive `close[t-21]/close[t-252]-1`, ranked in top 20% (rounded up, at least one) | 253 consecutive completed observations for **every** included universe member | 20–252 sessions |
| Trend | Latest close above 200-session average and 50-session average above 200-session average | 200 consecutive closes | 1–252 sessions |
| Breakout | Latest close strictly above preceding 20-close maximum, latest volume at least 1.5× prior 20-volume average; baseline volume must be positive | 21 consecutive closes and nonmissing volumes | 1–20 sessions |
| Quality momentum | Momentum leader plus ROE ≥10%, revenue growth ≥0, debt/equity between 0 and 1 inclusive | Full momentum cross-section and three financial ratios with matching period starts/ends | 20–252 sessions |
| Selective mean reversion | Five-session close return ≤−5%, while latest close is above 200-session average | 200 consecutive closes | 1–5 sessions |
| PEAD | Supplied earnings surprise ≥5%, a strictly positive latest close-to-close confirmation, and evaluation 1–3 verified sessions after event anchor | Supplied timestamped surprise and two consecutive closes | 1–20 sessions |
| Revision momentum | At least two distinct supplied revision events in current/trailing 29 session anchors, with summed fractional revisions ≥2% | Source-backed revision events and verified session anchors | 1–30 sessions |

Momentum ties use ascending symbol order, independent of input order. Missing any
included competitor's required momentum history makes momentum and quality-momentum
unavailable for the whole cross-section; the universe is never silently shrunk.
The recent 21 sessions are excluded from momentum's return calculation. Quality metrics
are already-derived structured ratios; mixed reporting periods yield unavailable output,
and arbitrary SEC amounts are never relabeled as ROE or growth. Missing estimates or
volumes stay missing. PEAD needs a later-session price confirmation; a same-session
surprise cannot immediately enter. An expired known earnings event yields a hold/exit
condition rather than a new entry. Insufficient recent revision events remain unavailable.

A met entry hypothesis yields `enter` when flat and `hold` when already held in that
family. A failed hypothesis yields `hold` when flat and `exit` when held. Missing required
inputs yield a typed unavailable outcome, with no decision or execution timestamp.
Unavailable output is never substituted with a sell or a new position. Existing account
risk/reconciliation owners must independently govern any real exposure.

Every proposal includes a deterministic SHA-256 evidence reference binding the decision
cutoff, declared calendar, normalized observations, visible membership, financial facts,
deduplicated events, and declared held identities. This provides reproducible input
identity, not source authentication or a confidence estimate.

## Validation and next steps

Synthetic tests cover each policy's positive/denial paths, missing observations/volume/
financials/events, future rejection, duplicate event identity, cross-sectional ties,
period mismatch, after-hours release timing, universe removal, and next-session proposals.
These tests establish local behavior only.

Next, the integrating owner must review the exact diff, run the narrow and integrated
checks, and connect a qualified point-in-time observation producer before evaluating
these hypotheses out of sample. The research proposal seam does not authorize orders,
promote a strategy, establish a paper-duration requirement, or permit live trading.
