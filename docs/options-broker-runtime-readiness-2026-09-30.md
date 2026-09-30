# Options broker/runtime readiness audit — 2026-09-30

Read-only audit against `f2ff32219ffc017b8da63c3b8a8177bcb8c6ee65`.
Sources were repository code/docs, current public Robinhood documentation and available
tool-declaration metadata. No broker operation, authenticated capture, account read,
credential access, production-ledger access, SSH, deployment, purchase or external write
was performed. This document is not evidence of profitability or live authorization.

**Broker/runtime verdict: `NOT_READY`.** These findings are ready for integration as an
audit only. `OPTIONS_LIVE_SUPPORTED=false`, paused defaults, risk controls and the initial
single-leg long-call/put boundary remain unchanged.

## Four independent evidence dimensions

| Dimension | Finding | What remains unproved |
| --- | --- | --- |
| Public | Current official options/approval catalog inspected | Account entitlement and actual behavior |
| Session | Two namespaces declare conflicting contracts; neither invoked | Exact standalone schema and response behavior |
| Account | Unverified by this audit; historical empty reads remain historical | Nonempty rows, fees, settlement, permissions and restrictions |
| Standalone runtime | Unverified; prior paused-host observations are historical | Unattended auth, renewal/revocation, restart and production lifecycle |

Public documentation does not establish session availability. Session declarations do
not establish account entitlement. Codex/plugin authentication is not runtime
authentication. Neither successful local tests nor complete declaration evidence grants
production eligibility. Use `capabilities/verification.py` for scoped diagnostic evidence;
its `production_eligible` result remains permanently false.

## Dated declarations: preserve old negatives

The [September 18 audit](options-official-capabilities.md) remains a dated observation,
not a statement to silently rewrite. The [September 30 checkpoint](options-real-data-validation.md)
already records a separate public/session update. This audit confirms these distinctions:

| Contract | Legacy `mcp__codex_apps__robinhood_*` | Current `mcp__robinhood_2__*` |
| --- | --- | --- |
| Review/place options | Exactly one leg | Declares 1–4 legs with account restrictions |
| Orders/positions/instruments pagination | Extract cursor from `next` URL | `next` is an opaque cursor passed verbatim |
| Upgrade/exercise/cancel exercise | Absent from inspected legacy namespace | Declared; not invoked or behavior-verified |

`replace_option_order` is absent from both inspected namespaces despite prose references.
Do not invent it, combine namespace contracts or submit independent legs as a package.
The newer multi-leg declaration does not expand the repository's approved strategy scope.

The [current official catalog and trade-approval documentation](https://robinhood.com/us/en/support/articles/trading-with-your-agent/)
lists exercise/cancel-exercise and account trade-approval tools. Neither inspected
namespace exposes `get_trade_approval_setting` or `get_trade_approvals`. Account approval
settings and resulting order/proposal behavior therefore remain unknown.

`capabilities/snapshot.py` classifies nine options tools; newly declared exercise tools
remain locked, unclassified discovery records. Its unconditional single-leg limitation
should eventually distinguish repository policy from dated connector facts. Classification
updates must not unlock a tool or destructively rewrite historical evidence.

## Concrete engineering and evidence gaps

- **No options broker mapping:** `domain/options_account.py` defines normalized
  observations, not Robinhood response parsers. Complete sections require independently
  established account scope, pagination and a common history window.
- **No complete fee/cash/lifecycle mapping:** declared order executions include settlement
  dates but no actual execution fees. A settlement date is not settlement completion;
  pending exercise/assignment/expiration quantities are not complete lifecycle history.
  Portfolio cash and informational unsettled funds do not establish all settled cash,
  reservations and collateral. Missing values must not become zero or complete sections.
- **Identity and states:** legacy orders may omit `option_id`; do not guess contract
  identity. Unknown states, missing timestamps and incomplete rows must fail closed.
- **Ambiguous submission:** placement declares `ref_id`, but inspected order reads neither
  accept lookup by it nor echo it in order rows. Broker deduplication lifetime, exact
  request binding and lookup after a lost response require external evidence. A fake test
  cannot establish broker idempotency; ambiguity must retain reservations and block retry.
- **Review binding:** no declared durable review token/expiry establishes provider-side
  review-to-place binding. Local exact equality and freshness checks remain necessary but
  do not prove provider behavior. Missing order output is not proof of rejection.
- **Execution integration:** `execution/service.py` and `execution/review.py` require the
  legacy exact `OrderIntent`. Do not coerce options structures into that domain.
  `simulation/options_historical_execution.py` is simulation, not a broker submission seam.
- **Offline monitoring only:** `runtime/options_monitor.py` accepts injected normalized
  observations in offline modes and always stays paused/entry-disabled/live-unsupported.
  Its overlap guard is per instance, not distributed fencing. `runtime/daemon.py` does
  not implement the production options loop.
- **Readiness is scoped:** `scripts/live_readiness.py` checks live configuration and
  Crypto/operator file prerequisites; it does not establish options readiness.
  `cli/options_deploy_plan.py` remains a static, credential-free `NOT_READY` report.

## Local work that can proceed without credentials

Implement only declaration-bound parsers and injected fake contracts, not an authenticated
provider adapter constructed from public prose or declarations alone:

1. Pin connector/schema provenance in synthetic fixtures. Test drift, missing/new tools,
   conflicting namespaces, latest denial/expiry, preserved historical negatives and strict
   public/session/account/runtime separation. Synthetic evidence never promotes readiness.
2. Build parse-only DTOs and conservative mappings into existing options observations.
   Test exact types, bounded Decimal strings, integral quantities, UTC times, null rows,
   unknown enums, duplicates, missing identities and sanitized errors. Independently test
   each pagination contract, bounded pages/rows and repeated cursors; never fetch a returned
   URL directly. Missing fee/settlement/lifecycle information remains incomplete.
3. Test fake-only requests within current policy: exact account/contract/side/effect/ratio/
   quantity/tick-price/TIF/session equality, review freshness and required fee/collateral
   evidence. Reject second legs and unsupported order types. Persist logical identity
   before fake submission. Unknown acceptance forbids blind retry/replacement.
4. Test partial-fill/cancel races: cancel acceptance is not terminal cancellation and
   cannot release reservations before reconciled final state. Test paused monitoring with
   incomplete/stale observations, timeout, store/alert failure, backward clocks and restart
   without trusted prior clean status. Assert no network, credentials or write capability.

Reuse canonical configuration, reconciliation and storage. Production scheduler, lease,
recovery and execution integration remain under the authoritative integration owner.

## Separately authorized external proof required

- Approved account binding and caller-relative Agentic eligibility; options permissions,
  account/restriction state, settlement/spendable funds, current intraday regime and trade
  approvals. Do not infer a regime from dates or options approval level.
- Sanitized authenticated nonempty response shapes, complete history/pagination, actual
  fee mapping, settlement completion and lifecycle visibility; quote entitlement,
  timestamps, product coverage, tick rules, latency and rate-limit behavior.
- Supported standalone authentication, renewal, expiry/revocation and restart procedures.
  [Official onboarding](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)
  documents interactive setup, not the deployment-specific unattended lifecycle contract.
  Do not copy or inspect plugin credentials to fill this gap.
- Exact runtime image/config identity, durable reconstruction, cross-process fencing,
  heartbeat/alerts, encrypted restore, readiness denial and unchanged live-disabled state.
- Separately authorized broker review/place/cancel evidence: request equality, idempotency,
  ambiguous-outcome reconciliation and cancel/fill races. Exercise requires its own
  specific confirmation and remains outside this implementation boundary.

## Verification and next steps

**200 local, non-authenticated tests passed:** 172 tests from capability verification,
options monitor/reconciliation/expiry, monitor persistence and no-live-write suites;
28 tests from options snapshot/config/deployment-report and equity-lock suites.
Runs used `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest
-p no:cacheprovider` with the repository's default non-authenticated selection. An initial
invocation omitted `PYTHONPATH` and failed import collection; the corrected runs passed.
No full regression, remote CI, authenticated behavior, current host or encrypted restore
verification was performed for this audit. No source changes were required by the tests.

Next: finish declaration-bound parsing and fake contracts, integrate paused observation
tests, then obtain separately authorized account and standalone-runtime evidence.
Economic validation, paper/shadow promotion and explicit live authorization remain
independent later gates. The project is not complete or live-ready.
