# ETF execution-readiness reassessment — 2026-10-05

Status: **BLOCKED_INPUTS / ECONOMIC_NO_GO / NOT_READY**. This records fresh
verification, not completed research, trusted paper operation, deployment of the
forward owner, or permission to trade. Alpaca remains the market-data source;
Robinhood remains the execution broker. Risk limits and live blocks are unchanged.

The later October 5 operator amendment removes historical halt/LULD and gap
coverage as prerequisites for **exploratory** Alpaca-only research. It does not
establish those facts or remove forward operational controls. See the
[recorded authority](operator-authority.md#historical-control-coverage-research-waiver--2026-10-05)
and [amended study](superpowers/specs/2026-09-30-focused-etf-research-design.md).
Older role-specific reports remain unchanged; a separately versioned exploratory
admission is still needed rather than changing their permanent diagnostic flags.

## Verified software identity

[PR #17](https://github.com/Jed1122/Robinhoodtradingbot/pull/17) is merged at
`38c2d9a948bb963e348be68d1c1cacede48fedce` on
`codex/robinhood-system-implementation`. Its tree
`72fe8a93aacc989f8ff1c2992543ae5056810f1a` equals reviewed owner head
`7d7138b452d901037410d296f01ac13d32b89a3a`. PR #16 was already integrated;
neither merge needs repetition. The owner remains synthetic, paused and
non-promotable. This reassessment changes documentation only.

Fresh public-code audits distinguish existing implementations from missing
composition: the native replay kernel, six-run economic evaluator, descriptive
cost measurement, receipt linker, and versioned joint owner already exist.
They must not be rebuilt or described as qualified merely because tests pass.
Actual-source admission is still unshipped: `QualifiedEtfDataset` cannot be
constructed, `iter_etf_events` denies, and diagnostic economic reports remain
permanently `ECONOMIC_NO_GO`. Complete inputs alone cannot flip those contracts;
reviewed qualified-source/research composition is also required. No caller-supplied
verification flag is a substitute.
Existing daemon `run()` is a no-op, scheduler leadership is in-memory, the public
paper CLI lacks trusted promotion composition, and `serve --paused` is health-only.
The October 4 owner contract excludes a qualified factory, recurring worker and
production restore. Those are still separate engineering deliverables.

## Historical inputs

The retained native readers reverified one complete bar archive and one quote
archive: 2,514 daily bars and 1,074 quote observations. Another retained manifest
cannot be admitted as a complete archive. No attempt marker was removed or retried.

A newly requested Alpaca connector calendar covers 2016–2025. Its newly retained,
normalized connector envelope has SHA-256
`6b68276707b93e5d4402e991746721843f56d9d4806d61bb910df168ad66eeff`.
This is a **fresh acquisition and reference artifact**, not an original HTTP
receipt or restoration of original retrieval/publication evidence. The resulting
coverage report is byte-identical to the digest recorded in the October 2
assessment: this is not a new calendar content identity, changed historical
coverage, or new qualification. The reacquisition supplies a usable reference
file for the current assessment while preserving the documented legacy-v2 New
York projection and nonqualification flags. Prior reports are untouched.

The committed `execution-coverage-run --page-bounded-quotes --qualify-inputs`
command was run against these explicitly selected inputs. It returned exit 2 and
retained report SHA-256
`d836da7a9ae58c8a18a4a3a1633496ac7160bcf58a64e3d0a425ca68752f1a2b`.
Bar dates exactly match the 2,514 calendar sessions: zero missing or unexpected
bar dates. After the global 750-session warmup and pre-2024 holdout exclusion,
there are 1,262 development sessions, **zero** with full requested quote spans
and **zero** with in-session quote observations from this capture.
Request spans are not proof of market completeness or executable observations.
Holdout outcomes were not evaluated.

Unresolved nonwaived roles remain execution quote inputs, condition/round-lot
capacity semantics, corporate-action continuity,
account/channel fractional terms, dated customer costs, empirical order timing,
cash yield, and complete operating-cost provenance. Historical halt/LULD and gap
proof is waived only for exploratory research. Alpaca documents status/LULD messages
in its [real-time stream](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data);
that documentation and forward captures do not establish historical backfill.
The [historical quote endpoint](https://docs.alpaca.markets/us/reference/stockquotesingle-1)
must not be treated as proof of all these other roles.

The current CLI still admits at most 128 quote archive pairs and materializes
them; native event/economic intake also has independent record ceilings. A
versioned, bounded partitioned intake is needed for whole-study execution inputs.
Raising one ceiling alone is not an end-to-end completion or qualification fix.

### Subsequent native development capture

At clean committed source `454c6515cce6df883188313f3bffac94a9039b17`, the coordinator
froze a SPY/SIP/USD ascending, `asof=-` quote request for the first five minutes of
the first eligible development session: `[2018-12-26T14:30Z,14:35Z)`. Calendar bounds
were checked before acquisition; no strategy or holdout outcomes selected the scope.
Manifest SHA-256 is
`b9f764fc1f1ac1ef6ed65d5cd7c4934abab88a44ebe9f3741c92948dba04b609`.
The existing one-shot owner reached a terminal cursor: **62,346 observations across
63 pages**, retaining 7,057,317 original raw bytes. The committed page-bounded reader
independently reverified the manifest, receipt chain and raw hashes; all files are
current-user-owned mode 0600 inside a mode 0700 directory outside Git.
No credential value or raw price payload is recorded here.

The combined calendar/request-coverage audit now counts 63,420 observations and
**one** quoted development session, still **zero** full requested sessions out of
1,262. Report identity is
`9fca235ffa7094547da10d582b12b23fb40286367b7ef92b8078a430c5d4e421`.
This supersedes the initial zero-quoted-session inventory above. Transport
completion proves only this five-minute request, not all ticks, executable sizes,
full-session monitoring, whole-study history or qualified economic inputs.
Its flags remain source-unqualified, execution-disabled and non-promotable.
The existing diagnostic audit still applies its original role contract; the
operator amendment is not implemented by relabeling that result.

## Customer costs and economics

A fresh read-only check of the intended account succeeded. It did not supply
usable execution-calibration evidence. No unrelated account was inspected to
find substitute samples, and no order was submitted. Raw account results and
customer records are not included here or in delegated tasks.

The existing private cost input was rerun through the committed calibrator. It
returned exit 2, `BLOCKED_INPUTS`, calibration unverified and non-promotable;
retained artifact SHA-256 is
`4842c9a10e026132615db92db396f22e6a7e1a19977c14b9e5d2b62f72d4b0e6`.
Missing fees, slippage and original causal submission/quote/fill clocks remain
missing, not zero. Historical broker UTC timestamps cannot reconstruct an
unrecorded local monotonic clock session. Forward Alpaca quote receipts alone
cannot establish Robinhood order latency or customer execution costs.

Subsequent private document reconciliation matched the retained Alpaca invoice and
paid receipt by their invoice identity: they represent one payment, not two
operating charges. The original CSV hash and Decimal cash-flow total still match
its saved reconciliation; it contains funding but no trade or charged-fee samples.
A retained monthly statement explicitly reports zero interest for its period,
but that observation is not an attainable cash-yield rate or historical fee
calibration. Account identifiers, raw monetary records and original documents
remain private. Genuine fills, final order charges and causal quote/order clocks
are still absent; no empty broker-history query or calibration trade was repeated.

The full six-run evaluator is implemented but genuine after-cost acceptance
cannot be established from this package. No unqualified cost schedule was
installed, no synthetic sample was relabeled, and no final holdout was examined.
`ECONOMIC_NO_GO` remains the verdict; a future valid study can still fail its
economic thresholds. Accepted profitability cannot be promised or selected.

## Existing host inspection

Read-only access to the existing host now succeeds. Clock synchronization reports
`yes`; loopback health returns HTTP 200, readiness returns 503, and metrics show
`trading_bot_paused 1.0` and `trading_bot_live_enabled 0.0`.
The one matched Compose `trading-bot` container is running, with zero mounts and
restart count zero. Its executing image is
`sha256:1a259e1a559c2ecb2ae0277e8f7fa2733e7e9f0c2b90ff418f5baa1c527e9d25`.
Its image has no Git revision label. Read-only source inspection confirms that
both new forward-owner modules are absent from that container. A non-importing
`PathFinder` lookup in the container's interpreter also found the application
package but neither owner module, without importing application/broker code.

This proves paused process health, **not** deployment of PR #17, trusted strategy
cycles, unattended broker authorization, persistence, alerts, or restore/rollback.
No service was stopped/restarted, container deployed, mount added, credential
inspected/moved, or production state changed. The existing backup excludes the
forward owner; full owner/tape/independent-head backup and paused deployed recovery
require their own complete composition and verification. Diagnostic recovery is
not a filesystem read-only operation and was not run against production.

## Verification and next dependency chain

Three local, public-only audits freshly ran 1,110 fixture tests in the locked
Python 3.12 environment: historical contracts 226, cost/economics 691, and owner
recovery plus paper/shadow fail-closed composition 193. One existing
Starlette/httpx warning occurred in the composition subset. These are scoped
fixture results, not a new full regression, coverage/multi-interpreter release,
authenticated integration, economic acceptance, or eligible observation count.

The coordinator independently reran the combined 32-suite subset centrally:
1,054 passed, one existing warning, 52.27 seconds. The historical semantic/reference
suites included in the parallel audit were not all repeated in that subset.
Fresh Ruff and Mypy passed; Mypy checked 327 source files. Documentation diff
checks passed. No new full suite, coverage, dependency audit or hosted CI run was
performed for this documentation-only reassessment.

For the subsequent acquisition, the unchanged native capture/archive fixture
suites passed **96 tests**. New receipts were reverified with the committed reader,
and the combined coverage command correctly returned exit 2. These checks are
not a new full release validation or proof of execution-cost qualification.

Next work remains:

1. Implement separately versioned bounded partitioned exploratory execution intake
   under the recorded historical-control/gap waiver; retain its limitations and
   obtain the remaining price/action/size inputs without inventing market state.
2. Supply attributable genuine executions, reconciled final charges, original
   same-session order/quote receipts, and supported cash/operating-cost evidence.
   Do not poll empty history or place calibration trades to manufacture evidence.
3. Implement and review evidence-backed actual-source/research admission, then
   run the frozen after-cost study on supported inputs; accept NO-GO if its
   untouched tests, uncertainty or policy-feasibility requirements fail. Never
   unlock a diagnostic schema or relabel its results to obtain acceptance.
4. Complete reviewed strategy-to-joint-owner, worker and promotion composition;
   verify full encrypted backup, paused restoration and rollback on the exact
   separately authorized runtime candidate.
5. Only after eligibility gates pass, collect 100 genuine eligible paper cycles
   and seven distinct UTC shadow dates. No accelerated fixture or health probe
   counts. Live activation is a separate explicit authorization.

External evidence blocks its dependent qualification; it does not prohibit
credential-free engineering. New architectural slices still need exact contracts,
independent integrated review and revision-specific verification. Broader task and
merge authority does not waive any safety or evidence requirement.
