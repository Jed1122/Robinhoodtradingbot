# Alpaca Basic: free-only research-data validation

Date: 2026-09-17 (UTC)

Status: the operator approved this written specification on 2026-09-17 and confirmed that
they created a paper-only account on Basic/free, with no paid subscription or funded live
account. This is operator-reported account status, not an authenticated entitlement check.
No acquisition, credential access, provider implementation, research acceptance, or live
operation is approved by this specification.

Subsequent approval: the operator selected inline implementation of the separately written
diagnostic plan. Its local Tasks 1-3 are implemented and tested; see the
[diagnostic guide](../../alpaca-data-diagnostic.md). No authenticated capture has occurred,
and that separate implementation approval does not resolve usage rights or authorize acquisition.

Inspected base: `d53d596e5e11b21938adbc2ac6adaa95e6a4284c`, branch
`codex/continue-implementation-from-commit-7c4dcd1`.

## 1. Outcome, scope, and authority

Determine whether Alpaca Basic can provide a usable, privately retained research dataset
for the existing equity candidate scope without any data-subscription payment. This is
a source-feasibility milestone, not a broker migration or a live-trading milestone.

The selected subsystem is **unverified**. The synthetic bundle subsystem is complete for
its existing synthetic-only scope; it does not yet accept Alpaca or any imported source.
Robinhood remains the intended broker. Its credentials, allowlists, runtime, production
ledger, deployment, strategy selection, risk settings, and promotion gates stay unchanged.

The budget is $0 for data subscriptions. Do not start a paid plan, an automatically
converting trial, an exchange add-on, a funded-account workaround, or a subscription
upgrade. Existing hosting charges are separate. A denial must not trigger a paid fallback,
a new brokerage account, or a change of provider/feed behind the operator's back.

This specification's approval covers public-documentation review and local design/planning/handoff.
The separately approved diagnostic plan covers its local implementation and synthetic tests only.
The operator has completed account creation; agreement acceptance remains their action.
Credential installation, authenticated requests, raw-data retention, and any provider communication require an
explicit, separately reviewed acquisition scope before execution. Do not search for existing
keys, read account pages, or inspect production state to discover those prerequisites.

Dependency chain: source choice and written specification (approved) -> account creation
(operator-confirmed) -> usage prerequisites -> separately authorized bounded capture -> primary
review of authenticated response structure and coverage -> separately approved offline importer design.
The critical path is access and source evidence, not additional synthetic tests or funding.

## 2. Public evidence and unresolved facts

The following are provider-documentation claims checked on 2026-09-17, not tested entitlements.

| Item | Public evidence | Required disposition |
| --- | --- | --- |
| Basic pricing and history | Basic is listed as free, with US stocks/ETFs, history since 2016, and 200 historical calls/minute. [Plan documentation](https://docs.alpaca.markets/us/docs/about-market-data-api). | Candidate only; per-symbol completeness and the operator's actual plan remain unverified. |
| Historical feed access | The FAQ permits unpaid historical SIP queries when the request end is at least 15 minutes old; free live data is IEX. [Market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq). | Explicitly pin the feed. Never substitute IEX for SIP on an access failure. |
| Paper-only conflict | The paper-account page restricts paper-only users to IEX, while the plan/FAQ language is broader. [Paper trading](https://docs.alpaca.markets/us/docs/paper-trading). | Unresolved. Technical access alone does not resolve contractual entitlement. |
| Corporate actions | The endpoint documents late availability, but does not establish Basic access or a complete historical horizon. [Corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1). | Free access, historical coverage, and availability provenance remain separate unknowns. |
| Bar controls | The endpoint exposes raw/adjusted choices, explicit feed selection, symbol mapping, and pagination. [Historical bars](https://docs.alpaca.markets/us/reference/stockbars). | Bind all request choices; documented parameters are not verified response semantics. |
| Usage rights | Terms limit ordinary use to personal/non-commercial purposes and restrict distribution; no general archival permission is inferred here. [Terms and conditions](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf). | Resolve rights for the actual private retention/use before acquisition; no redistribution to Git or Cloud. |

If the account-specific terms or documentation conflict cannot be resolved, record the
candidate as blocked. Do not treat HTTP 200 as legal clearance. A request to provider support,
if necessary, is a separate operator-approved communication and must not include secrets.

## 3. Approach and boundaries

Use a staged evidence review before building a provider adapter. A broad Alpaca integration
now would assume unverified shapes and rights. Combining several free feeds now would add
unresolved identity, adjustment, and timestamp differences. Both alternatives are deferred.

The operator initially reported having no Alpaca account, then confirmed on 2026-09-17 that
they created a paper-only Basic/free account without a paid subscription or funded live
account. The remaining prerequisite checklist is not a network command:

- Account creation and account-type/free-plan confirmation are complete by operator report.
  Review the applicable usage terms separately; do not infer entitlement or retention rights
  from account creation. Record only account type and free-plan status in the sanitized
  handoff. Do not accept agreements on the operator's behalf.
- Do not fund or move assets. Do not select a paid plan, paid add-on, or live brokerage signup.
  If a required dataset needs one of those changes, stop and report the free-only limitation.
- Resolve the permitted feed and intended private research/retention use. Unresolved rights
  stop acquisition; an account-access test cannot substitute for this review.
- Keep any subsequently authorized credential in an operator-controlled private file outside
  the repository, Cloud workspace, logs, screenshots, shell arguments, and container images.
  Do not paste keys into chat. Review credential handling before installing or reading it.
- Treat an API credential according to its real authority, not the planned client's use.
  A data-only client is not proof that its key is data-only. Do not use live-trading credentials
  merely because a paper credential cannot access a requested dataset.

After prerequisite review, prepare one explicit acquisition manifest for operator approval.
It binds the code revision of any capture helper, permitted host/method/paths, feed, symbols,
date range, adjustment and mapping settings, UTC run cutoff, request/page/byte/time limits,
credential-file location, private artifact location, and permitted retention scope.
These are diagnostic authorization bounds, not new strategy thresholds or an alternative
application configuration schema. The companion diagnostic has an offline-default command;
its existence does not authorize an authenticated acquisition in this milestone.

Only the official HTTPS market-data host `data.alpaca.markets` and these proposed GET paths
are within the future capture's maximum scope:

- `/v2/stocks/bars` for historical bars;
- `/v1/corporate-actions` for separately assessed corporate-action availability.

The final manifest may narrow that scope. It cannot expand it without a new review. No
account, portfolio, position, order, review, placement, cancellation, funding, subscription,
latest-quote, streaming, or broker endpoint is needed. Disable redirects; never forward
authentication to another host. Stop on access errors, rate limits, ambiguous responses,
changed schemas, or exceeded bounds. No automatic retry, feed switch, upgrade, or scheduler
is part of the first capture. Pagination consumes the same fixed request budget; exhaustion
means incomplete evidence, not success. Do not retain credential-bearing provider errors.

## 4. Validation contract

### History and identity

Read the existing candidate symbols, daily interval, history window, and minimum history from
the canonical loaded configuration. At the inspected base these are SPY/QQQ/IWM/DIA, one-day
bars, a 3,650-calendar-day request window, and at least 750 daily observations per symbol.
The requested range and minimum count are different checks; neither may be silently reduced.
This candidate tuple remains research scope, not an execution allowlist or proof that the
universe was selected without present-day knowledge.

Pin SIP only if entitlement and intended use are resolved. An IEX-only result is a distinct
source result, not an acceptable substitution. Preserve instrument identity and symbol-mapping
choices. Alpaca's `asof` symbol-mapping parameter must not be labeled a data-vintage guarantee.
Do not relabel late ticker mappings or later corrections as information known earlier.

Use explicit raw/unadjusted bars for the initial investigation; retain the price-basis claim
as provider evidence to validate, not an instruction to apply local adjustments. Verify exact
numeric parsing, symbol identity, ordering, duplicates, pagination completion, requested-window
containment, and missing intervals. Reject non-finite or malformed values. No forward filling,
interpolation, zero-volume fabrication, or silent row deletion may manufacture coverage.

### Event time, collection time, and coverage

Record request-start and response-completion instants in canonical UTC using a trusted local
clock. Keep provider event dates/times and any claimed publication times separate. A bar label
does not establish its close time or when the final value became available. Review actual
session aggregation, holidays, early closes, and daylight-saving transitions before declaring
expected slots; do not map every equity day to a fixed 24-hour UTC duration.

Initial capture assessment must keep availability no earlier than local collection. Backtests
at earlier dates therefore remain unqualified until historical availability/revision semantics
are separately supported and approved. Having enough rows, a plausible chart, a documentation
claim, or an internally consistent hash does not prove complete source history.

### Corporate actions and universe evidence

Assess corporate-action access independently from bar access. Capture only the authorized
record scope; account for pagination, provider filter semantics, and action types returned.
Alpaca's `data_quality=complete` label is not proof of complete history, and an empty response
does not establish an action-free interval. Preserve delayed, corrected, incomplete, or
unsupported events as explicit limitations. Do not assume cash distributions, splits, or
capital-gains events can be ignored because prices were requested unadjusted.

No current listing, instrument start date, or present-day ETF list establishes a historical
selection baseline. This milestone does not fabricate membership events, change the candidate
universe, add an adjustment policy, or clear survivorship/point-in-time limitations.

### Artifact and assessment separation

If retention is authorized, keep exact successful market-response bytes in a private,
content-addressed quarantine outside the repository and production evidence directory.
Retain a separate request manifest without headers or credentials and distinguish exact-byte
digests from canonical decoded-value hashes. Files must be owner-only regular files in an
owner-only directory, with no symlink traversal or overwrite of existing artifacts. Reuse
reviewed storage mechanisms where compatible; do not introduce a second general storage layer.

The current bundle assembler/store accepts only synthetic descriptors. Do not pass captured
Alpaca data to it, relabel real data as synthetic, or broaden its allowlist in this milestone.
Any acquisition helper and private capture format require their own reviewed bounded plan;
neither is implemented by this document. Raw responses remain off Git, Cloud, and reports.

The shareable assessment contains only safe reason codes, counts, hashes, UTC assessment time,
non-secret request scope, and per-check statuses. Unknown facts remain unknown. Each check has
one of `not_checked`, `observed_pass`, `observed_fail`, or `unresolved`, plus a safe evidence
reference. These are proposed diagnostic statuses, not new promotion-domain types. No field
may claim source acceptance, research eligibility, or live authorization.

## 5. Success, failure, and tests

The milestone can complete with a truthful negative result. A positive feasibility disposition
means only that the scoped source is sufficiently understood to propose an offline importer.
It is not a `VerifiedBundle`, a `ValidatedMarketSnapshot`, accepted research, or a qualifying
paper/shadow observation. Data quality and successful authentication alone cannot enable trading.

Required assessment rows cover: zero-cost plan, contractual entitlement, technical access,
retention rights, original bytes, identity, numeric shape, requested history, expected-slot
coverage, interpolation semantics, event/session timing, historical availability/revisions,
corporate-action coverage, and historical universe evidence. All start `not_checked`, except
the already identified documentation/rights ambiguities, which start `unresolved`.

Use three overall dispositions without a trading implication:

- `BLOCKED_PREREQUISITES`: account, rights, reviewed capture mechanism, or authority is absent;
- `INSUFFICIENT_SOURCE_EVIDENCE`: a run was authorized but one or more required source facts
  failed or remain unresolved;
- `READY_FOR_IMPORTER_DESIGN_REVIEW`: primary review found all required source facts adequately
  supported for the explicitly scoped follow-on design. No automatic promotion follows.

When acquisition tooling is separately approved, deterministic tests must cover exact host,
method/path restrictions; no redirects or write paths; no credential logging; response bounds;
clock/manifest binding; malformed numbers and unknown shapes; page-token repetition and budget
exhaustion; 401/403/429 denial without retry or fallback; per-symbol gaps and duplicate bars;
session/DST boundaries; unavailable records; action-coverage ambiguity; and quarantine-only
output. Default tests and Cloud tasks must use synthetic data and perform no network access.
Authentic response values are never copied into fixtures; reviewed value-free shapes may guide
later synthetic fixtures without upgrading them to provider evidence.

For this documentation checkpoint, run existing documentation smoke checks, validate changed
Markdown links locally, review the exact diff, and run `git diff --check`. Do not represent
these checks as network, data, runtime, or full-suite verification.

## 6. Operator handoff and next approval

The operator has confirmed account creation, paper-only account type, and Basic/free plan.
Do not ask them to repeat that setup or confirmation. Feed entitlement and intended private
retention/use remain separate unresolved prerequisites, not facts established by this report.
No key, account identifier, screenshot of a key page, payment detail, or brokerage balance is
needed in the conversation. Do not request live-account creation or funding to unblock this work.

Written-spec approval is complete. The next bounded plan is the
[first-response diagnostic implementation plan](../plans/2026-09-17-alpaca-first-response-diagnostic.md),
with exact local ownership, frozen interfaces, tests, and separately enumerated external
operations. Its two first-page samples cannot establish full-history coverage. Completing
that diagnostic does not complete this broader source-feasibility specification.
Follow the repository rule prohibiting a production provider implementation from public prose
alone: authenticated shape evidence must be reviewed before implementing such an adapter.
If legal entitlement remains ambiguous, resolve that prerequisite before acquiring data.

Cloud workers may later review public documentation or write synthetic fixtures/parser tests
against an exact frozen contract. They receive no credentials or actual capture bodies. The
primary owns acquisition, source acceptance, and integration; all trading-sensitive work stays
under the existing ownership rules. No new Cloud task or external capture is dispatched by
approval of this document alone.

The existing paused deployment and every live-trading blocker remain unchanged. This document
does not start the paper-cycle or elapsed shadow evidence clocks.
