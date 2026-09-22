# SPY options research shortlist design

Status: **Native implementation verified; synthetic research only, live gates closed**.
Prepared 2026-09-22 UTC against `24472cc0aa67aac85ce23de815a1faa2ed0a8030`.
No implementation, data purchase or live authorization follows from this document alone.

## 1. Intent and scope

The operator wants genuine options research at a lower data cost. The approved brief
is a daily research-only shortlist: one SPY call and one put, using the previous
completed session's close, nearest strikes, and an expiration closest to 30 calendar
days within 21–45 days. Missing inputs yield no candidate; ties are deterministic.

This is an **acquisition universe**, not two positions, an entry signal, a payoff
prediction or a broker instruction. It intentionally retains both directions before
examining option returns. The existing unvalidated 20/100 momentum hypothesis can
later choose direction in a separately reviewed historical replay. No research
threshold is claimed optimal or empirically supported.

The coordinator owns selection, configuration and integration. Credential-free
fixture/parser tests and report-format review may be delegated after interfaces
are frozen. Raw licensed records and account information stay local and private.

### Alternatives considered

1. **Fixed shortlist across the intended history — selected.** Reduces candidate
   coverage before observing returns; requires causal prices, mappings and coverage.
   Savings must be measured, not assumed.
2. **Full-chain short pilot.** Avoids strike-selection engineering for an early
   pipeline test but provides less temporal breadth; it is not final validation.
3. **Subscription-backed wider history.** Allows broader exploration but has separate
   underlying-data cost/entitlement questions and recurring expense. Not selected.

### Explicit exclusions

No market-data acquisition, authentication, cost API call, order intent, broker
transport, live deployment, account inspection, strategy P&L or promotion decision.
Do not implement a second configuration loader or change existing numeric, quote,
order, risk, persistence or historical evidence validators.

## 2. Existing state and dependency chain

| Component | Current classification |
| --- | --- |
| Options contracts, source records, `point_in_time`, `select_chain` | Implemented provider-neutral primitives; source completeness is not certified. |
| Native Databento definitions staging | Implemented; mapping, complete-chain and session enrichment remain partial. |
| 20/100 options direction | Implemented unvalidated hypothesis; not a contract selector. |
| Exact-symbol cost diagnostic | Implemented for bounded standard SPY raw symbols; no acquisition capability. |
| Native underlying normalization and real-data shortlist | Not implemented. |
| Existing options replay | Synthetic-only by construction; real data must not be relabeled to enter it. |

Critical path for an actual shortlist: permitted underlying inputs and session
calendar -> verified completed-session close and point-in-time chain -> this pure
selector -> private candidate manifest -> separately approved cost/acquisition stage.
Synthetic input validation and selector tests can proceed without buying anything.
Do not require genuine data to finish the pure selector, or call fixture success
proof that genuine data dependencies are resolved.

The [underlying preflight](../../options-underlying-data-preflight-2026-09-22.md)
records an indicative $1.09 venue-specific underlying subtotal, not a full budget.
Source selection and corporate-event coverage remain separate acquisition decisions.

## 3. Deterministic selection policy

The version is `spy-prior-close-atm-30d-v1`. No parameter grid is searched.

1. **Decision session and time.** An explicitly supplied, source-bound calendar
   identifies the target regular session, its immediate preceding eligible underlying
   session, closures and early closes. Decision time is the target regular-session
   opening instant. All stored instants are UTC; date arithmetic uses the session's
   `America/New_York` trading date. Never infer weekdays or hard-code a UTC open.
2. **Reference close.** Use only an unadjusted, non-interpolated completed SPY
   session bar for that immediate prior session, with positive finite Decimal close,
   matching source/coverage, exact session boundaries, source hash and an availability
   time no later than the decision. A source-specific last trade is labeled as such,
   not an official consolidated close. Missing prior-session observations deny the
   session; do not fall back to an older day, current spot, daily UTC bucket or future
   revision. Known splits, mergers or denomination/deliverable changes effective
   between the prior close and target open deny this version; do not invent continuity.
   Cash dividends are retained as event context, not used to adjust the reference
   close or select a different candidate. This is an unadjusted prior-close hypothesis.
3. **Visible chain.** Reuse `select_chain` at the decision instant for one explicit
   source and SPY. Require complete declared membership, matching visible definitions,
   retained provenance and reviewed source/availability semantics. A caller's
   completeness flag is not independent certification. Synthetic and imported lanes
   are distinct; unresolved imported source evidence returns a denial.
4. **Eligible contract observations.** Standard USD SPY options, multiplier and
   deliverable exactly 100 SPY shares, unadjusted, American, physically settled and
   PM settlement; contract is known and has a supplied eligible session covering the
   decision instant. Preserve existing `OptionContract` validation. Duplicate or
   conflicting economic identities are invalid inputs, not a tie to hide with sorting.
5. **Expiry.** Compute `expiration - target_trading_date` in calendar days. Eligible
   expirations are inclusive 21 through 45 and must contain at least one eligible
   call and put. Rank by `(absolute(days_to_expiry - 30), expiration_date)`; the
   earlier expiry wins an equal-distance tie. Select one common expiry for both
   sides. If there is none, emit no candidates.
6. **Strike.** Within the selected expiry, rank each side by
   `(absolute(strike - prior_close), strike)` using Decimal arithmetic. Lower strike
   wins an equal-distance tie for either side. This is an arbitrary reproducibility
   rule, not a directional optimization. Emit exactly one call and one put, in that
   order, or no pair if either side cannot be resolved.
7. **No quote/outcome filter.** Option bid/ask, observed return, future survival,
   profitability, Greek estimates and current account balance are not selection
   inputs. Do not replace a chosen contract with another because the chosen contract
   is later expensive, illiquid, unavailable or losing. Record those later outcomes
   distinctly; capital/risk checks can still allow zero tradable contracts.

The input calendar must distinguish underlying regular sessions from options sessions
that may close later. Do not repurpose an option's session close as the underlying
close. Reuse `OptionSession` for validated interval identities where appropriate and
`OptionExpiryCalendar` only for its contract-bound expiry role, not as an underlying
calendar with a fabricated contract identity.

## 4. Interfaces and configuration

Keep the pure policy under `research/options_shortlist.py`, not the data-client or
broker layer. Planned immutable research-only records:

- `ShortlistSessionInput`: current/prior session identities and interval bounds,
  calendar evidence/availability, a `Bar` plus explicit close availability and price
  basis/source coverage, relevant action-coverage evidence, source identifier, visible
  options records and source-provenance classification. It contains no credentials,
  broker account, order type, size or execution capability.
- `OptionsShortlistCandidate`: session identity, as-of, kind, canonical contract
  identity, exact standardized symbol, expiry, strike, reference-close identity and
  hashes of the selected visible inputs. It contains no executable limit or quantity.
- `OptionsShortlistResult`: version, config/code/input identities, ordered candidate
  tuple, selected-input decision hash, per-session reasons and aggregate counts.
  `production_eligible`, `evidence_promotable`, `download_authorized` and
  `live_authorized` are permanently false, not caller-writable flags.

Reuse strict Decimal, UTC and hash validators, canonical serialization, `Bar`,
`OptionContract`, `OptionsDataRecord` and the existing point-in-time functions. A
research-only envelope supplies missing bar availability and source evidence without
changing historical `Bar` or options-record serialization. Full-file integrity hashes
can differ when files change, but a session's decision hash must depend only on its
visible selected evidence and policy—not irrelevant future records or input order.

Extend the existing configuration graph with an `OptionsShortlistSettings` block
under `options.research_shortlist`: disabled by default; SPY only; min/target/max DTE
21/30/45; fixed selection version; previous-close reference, lower-strike tie and
earlier-expiry tie enums; and resource ceilings of 25,000 input records, 16 MiB of
decoded input bytes, JSON depth 16 and one decision session per invocation. These
are separate resource settings in the same graph, not changes to replay limits or
trading limits. The codec must enforce bounded reads before decoding; an oversized
chain is denied, not truncated or relabeled complete. A larger study is processed
session by session; any future resource increase requires its own benchmark/review.
The enabled block is permitted only in the explicit simulation/research
composition. The release envelope fixes this version's policy values and live locks;
no live profile can enable the shortlist as an entry source.

New resolved configurations receive new hashes. Do not regenerate stored historical
hashes or change legacy evidence readers to make old data appear current.

The planned CLI is an offline `options-shortlist` command on the existing options
research CLI, not the already-dirty general operator CLI. It reads a strict versioned
local envelope and writes a private content-addressed manifest using the existing
owner-only, outside-repository, no-symlink/no-overwrite pattern. Standard output is
limited to sanitized status, counts, reason codes and manifest hash, not licensed
rows or private paths. Invalid schema/type/limits return a sanitized nonzero denial;
valid but unselectable sessions remain explicit `no_candidate` results.

## 5. What this does not resolve

This milestone does not normalize the native definitions archive, infer original
quote-update times from sampled BBO/CBBO, or construct executable quotes. Provider
bar/quote importers and their timestamp semantics require their own reviewed work.
The pure selector accepts strictly validated normalized inputs or synthetic fixtures;
it cannot upgrade unverified imports merely because they have valid shapes/hashes.

The selector needs one previous session close; this does not reduce the downstream
20/100 feature window or any applicable 3,650-day history request, 750-bar minimum,
five-fold, effective-sample, uncertainty or untouched-test requirements. It produces
no strategy returns. In particular, the existing synthetic-only replay stays
synthetic-only; no source-name rewrite or validator bypass is allowed.

The requested selection dates remain a manifest input, not an implicit discovery
range. A future cost-manifest stage must group/deduplicate exact symbol/time windows,
preserve every source selection/denial, apply the existing 100-symbol request bound,
and retain exits/expiry and unresolved settlement obligations. This design does not
pretend that entry-date quotes alone suffice or that a 45-day expiry cap verifies
economic settlement. Exit/holding policy and formal study splits are not selected
by this acquisition shortlist and must be preregistered before return evaluation.

The current $100 assumption, $150 live-account ceiling, 0.5% per-trade budget,
$50 outer per-trade cap, $50 non-replenishing cumulative trial-loss ceiling and all
stricter limits remain intact. One call plus one put in a data manifest does not
authorize two entries, a straddle, multiple open positions or paired execution.

## 6. Verification requirements

Failing tests first, then narrow and broader existing checks:

- Exact 21/30/45-day boundaries, ties at 29/31 days, lower-strike ties, separate
  call/put strike availability and stable output under input permutation.
- No common expiry, no prior close, wrong prior session, unknown calendar/action
  coverage, adjusted contracts, duplicate/conflicting identities and missing chain
  members all deny with stable, sanitized reasons.
- Future bar/definition/chain revisions never change an earlier decision; a source
  revision available only after the open cannot enter that day's shortlist.
- Friday/Monday, holidays, early close and both DST transitions use explicit sessions.
  A UTC daily bar cannot masquerade as a regular-session bar.
- No option quote or return input is accepted for ranking. Subsequent missing quote
  coverage cannot silently select a replacement contract.
- Reject floats/bools where exact Decimal/int values are required, non-finite prices,
  mixed origins, unsupported schema versions, input-limit abuse, symlinks and unsafe
  output directories. Neither duplicate invocations nor output conflicts overwrite data.
- CLI tests deny network and credential reads; all manifest authorization/promotion
  flags remain false. Research-only activation cannot be loaded as a live entry path.
- Existing point-in-time, momentum, capital-risk and historical serialization tests
  remain unchanged in meaning and continue to pass.

Implementation verification retains Ruff, Mypy, full pytest with 80% overall coverage,
the existing 90% critical branch gates, Bandit, locked-dependency audit, SBOM and
manifest checks in proportion to changed paths. No production migration or deployment.
Implementation test results and adjudicated plan deviations are maintained in
[the operator guide](../../options-research-shortlist.md); synthetic verification
does not establish real-data, economic, broker or live readiness.

## 7. Review checkpoint

- Context, scope and dependency classification: complete.
- Research-only design brief: explicitly approved by the operator.
- Written specification and inline consistency/ambiguity review: prepared.
- Written-spec operator review: approved by the operator's “proceed” on 2026-09-22.
- [Implementation plan](../plans/2026-09-22-options-research-shortlist.md): approved for
  Native execution by the operator's “do native”; all four tasks, independent review
  corrections and post-correction regression verification are complete.

Implementation authorization grants no permission to acquire data or activate trading.
