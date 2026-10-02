# ETF native interpretation, paired analytics and paper recovery

Base: `c035ec4efff12056f6a55d67e17b2b33bb8dd4a5` (merged PR #9).
Final executable revision: `fa1e0e0690dc32a0c11ec424252357dfcb17aadb`.
This increment does not complete the full native strategy/economic runner,
qualify market data or costs, verify deployed recovery, or enable paper/live.
Approved plan Tasks 2–6 remain open at their qualified/operational boundaries.

## Implemented boundaries

`alpaca_quote_semantics.interpret_alpaca_quote` retains the original native
record, nanoseconds, body/page/row identity and hash. The current endpoint-specific
[historical REST schema](https://docs.alpaca.markets/us/reference/stockquotesingle-1.md)
describes sizes as shares, with round lots before November 3, 2025, and describes
one condition for both sides or two ordered bid/ask conditions. The decoder
projects already-share-unit sizes only. Older sizes and the conservative
transition window remain unresolved; it never multiplies by 100. Side decoding
does not establish dated condition eligibility. Inactive, crossed and locked
observations remain explicit, with mandatory control/fractional/source denials.
Legacy record fields, reasons and hashes are unchanged. All trust flags are false.

`etf_paired_economics.analyze_etf_matched_returns` consumes 100–10,000 aligned,
strictly increasing dates and owner-supplied, already after-cost daily return
fractions. It subtracts matched constrained/cash benchmark returns once, using
exact arithmetic independent of the caller's Decimal context. Both comparisons
retain 20/100-session chronological moving blocks, 1,000 draws, shared seed and
the existing 95% endpoints; the less favorable lower endpoint is explicit.
Inputs are positive-NAV return fractions strictly above -100%; total-loss or
negative-NAV operating series require a separate reviewed transport. This helper
neither executes trades nor constructs benchmarks, allocates costs,
counts independent opportunities or accepts research. Its verdict is always
`ECONOMIC_NO_GO`; positive statistics cannot create promotion observations.

`PaperPromotionApplication` now reserves the deterministic cycle durably before
calling the existing paper owner. The private, descriptor-bound journal is
`paper-cycle-journal-v1` inside its existing private lock directory. A claim
binds cycle, exact trusted context and start time; an immutable prepared hash
binds the computed observation before its ledger append; completion binds that
same observation. No account identifiers or credentials are stored in this journal.
The source-neutral paper composition remains unavailable from the public CLI.

After interrupted execution, uncertain write, failed observation append, or a
missing observation following completion, the claimed cycle denies with
`paper_cycle_recovery_required`. Unresolved effects quarantine the whole owner
across changed requests, source times and identities. A descriptor-held nonwaiting
writer lock spans asynchronous execution, preparation, append and completion.
Recorded nonterminal or unreconciled outcomes remain pending; an ineligible
observation is not release of economic uncertainty. Cached observations cannot
bypass another pending cycle. All retained completions must be present in the
current observation snapshot before a new entry or cached-evidence return;
missing history and identity transitions deny pending reconciliation. Promotion
evaluation and attestation persistence hold the same owner lock over a freshly
validated, complete observation snapshot. A committed observation
matching its prepared hash, claim start, identity and context-fixed flags can
complete an interrupted journal publication without executing again. Conflicts,
changed context, corruption, partial bytes, symlinks, hard links, unsafe modes,
nonempty lock files and overlapping writers deny. There is no timeout reclaim,
delete/reset command, automatic reconciliation, lease takeover or live capability.
The lock remains single-host, not distributed fencing.

Any future operational composition must retain journal plus observation/economic
ledger together, restore paused, reconcile unknown effects, and test the joint
backup/rollback protocol before entries. Existing deployment backup helpers do
not include this new journal or ETF checkpoint namespaces. Deleting or restoring
only one store is not recovery. No production state was migrated or changed.

## Fresh verification and actual inputs

Three independent read-only audits used only the exact committed base. Two
isolated implementation workers owned only the descriptive quote parser and
pure paired statistics; the coordinator owned durable execution/recovery.
Private corpus and credentials were never delegated.

Recovery tests reproduced fresh-process reexecution after failed observation
append before implementation. They now cover exact restart refusal, simulated
effect-to-observation SIGKILL, durability failures, exclusive-claim races,
completion/observation conflicts, legacy committed observations, and unsafe paths.
The initial central focused selection passed178 cases. Integrated review then
reproduced changed-request quarantine and unbound pending-observation gaps;
both were repaired RED→GREEN with owner-wide locking/quarantine and durable
preparation before append. The same reviewer then reproduced missing completed
history on a new request and cached eligible evidence while another cycle was
pending. Five new RED cases established these gaps and the required locked
promotion snapshot; the repairs deny rather than reset or reconstruct unknown
economic state. Final focused verification is recorded below. The existing
critical 90% per-module gate now explicitly includes the journal, application and
promotion runtime. Final focused verification passed 243 tests; all three modules
achieved 100% statement and branch coverage. Full exact-revision regression and
independent integrated review are separate; focused green is not their substitute.

The coordinator reread the saved receipt-bound quote probe without credentials,
network acquisition, purchases or raw-value publication: 1,074 records,
archive hash `9d869935d763174a177633b4c129359a581aa05bcafa0c21d2bbb039cc06596f`.
All 1,074 are round-lot-era observations with unresolved conversion, controls,
dated condition eligibility and fractional terms. There are 128 crossed and 133
locked observations; none is granted execution eligibility. This is data-quality
inspection, not strategy evaluation, after-cost results or final-holdout trading.
Prior development coverage remains 0/1,262 quoted/fully requested sessions; this
increment did not download new data or rerun a genuine study.

The authorized SSH read-only check again returned public-key authentication
denial before any remote command. No deployed image, health, authentication,
service reconstruction or recovery drill is verified. Local process tests do
not establish those facts.

At approximately 14:02 UTC, the coordinator refreshed only the authorized
Robinhood session account, equity-position/order and SPY tradability reads.
They succeeded, with complete returned equity pages. Private identifiers,
balances, holdings and raw responses were not persisted or delegated. Session
read access and a fractional-eligibility flag do not establish fractional order
types, protective exits, empirical costs, order lifecycle or standalone runtime
authentication. No broker review, place or cancel operation was called.

## Integrated verification

The same independent reviewer examined the exact final committed range in an
isolated local clone and passed 428 focused, adjacent and coverage-gate tests.
All four independent recovery reproductions now deny with zero new effects.
The promotion-snapshot concurrency probe denies execution while the guard is
held and permits it after release. No Critical, Important or Minor findings
remain within that reviewed scope.

The review did not establish provider qualification, genuine economic acceptance,
cost calibration, deployed recovery, joint-store backup/rollback, broker order
behavior, distributed fencing, same-user host compromise resilience or live
readiness. Those items stay open; an offline review is not operational evidence.

Both locked public-package advisory audits found no known vulnerabilities at the
time checked. Separate local deployment/SBOM verification passed 61 tests, with
four encrypted-backup tests skipped because `age` is unavailable. Compose and
all four deployment shell-script syntax checks passed. No deployment ran; SBOM
reproducibility wrote temporary outputs without replacing the tracked artifact.

Final clean local Git-clone verification at the executable revision above:

- CPython 3.12.13 main suite: 7,445 passed, 33 skipped, one existing Starlette
  warning; 491.17 seconds. Separately locked native suite: 20 passed, zero
  skipped; 154.04 seconds.
- Combined statement/branch coverage: 90.4374%; statements: 92.3634%; aggregate
  branches: 82.5613%. The overall 80% gate and all 57 independently measured
  critical-module 90% branch gates passed.
- Ruff, Mypy over 307 source files, Bandit and both offline lock checks passed.
  Bandit found no issues; 15 existing explicit suppressions remain.
- The clean clone's tree is `f9cea773d037b6194e6e1889f722d69daf7fec55`.
  Its tracked-source digest was unchanged before and after validation:
  `ad6a7dca818b546cd1e70a0e843546c520e8eb044ab9c9324acf44235658ec73`.
  Raw logs and independent main/native/combined coverage databases remain in
  `/tmp/etf-frozen-final-verification.hNdejT`.

Skipped cases comprise unavailable optional native dependencies in the main
environment and four unavailable `age` cases, not successful encrypted-backup
tests. No hosted Python 3.12–3.14 matrix was waited on or represented as passed.
Earlier pre-repair broad results are not substituted for this final revision.
Subsequent report-only documentation changes do not alter executable code.

## Remaining dependencies and next steps

1. Extract the source-neutral feature/execution kernel while preserving sealed
   synthetic wrappers/hashes; implement the native history/result/checkpoint
   envelopes with independent source/account cursors and full run namespaces.
   Preserve source actions, complete controls, capacity, cancellation and
   settlement uncertainty rather than inventing them from calendar opens.
2. Establish complete development quotes/actions/continuity, dated condition and
   lot-size rules, fractional/protective-order terms and actual usable coverage.
   The publication-timeline waiver remains latest-vintage exploratory only.
3. Extend cost representation without rewriting v1 evidence. The current
   both-sides fixture rate cannot encode all sell-only, per-share, cap, waiver,
   rounding and execution-group rules in
   [Robinhood's fee documentation](https://robinhood.com/us/en/support/articles/trading-fees-on-robinhood/).
   Dated operating/cash rates and empirical latency/fill calibration are separate
   requirements, not fulfilled by seven present role names.
4. Finish the six-scenario, two-capital-tier evaluator and executable matched
   benchmarks; retain purged folds, effective opportunities, uncertainty,
   untouched final test and canonical acceptance. Paired statistics are not this
   complete evaluation, and terminal unfilled orders are not independent trades.
5. Build reviewed ETF paper/shadow composition and its complete durable economic
   lifecycle, joint backups and representative recovery. Verify the actual
   authorized runtime before collecting eligible observations.

Qualifying ETF progress remains 0/100 paper cycles and 0/7 distinct UTC shadow
dates. No fixture, diagnostic, duplicate or historical row counts toward either.
The current latest-vintage exploratory study cannot promote automatically.
No deployment, credential changes, broker review/place/cancel, risk increases,
paid data, real orders or live activation occurred in this increment.
