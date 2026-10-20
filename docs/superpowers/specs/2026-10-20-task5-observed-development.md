# Task 5: available-Alpaca development evaluation

## Authority and status

The operator explicitly waived the 2016–2025 history requirement and all
Alpaca-support inquiries, authorized necessary downloads through existing Alpaca
access, and instructed us to proceed with Task 5 and amend the backtest plan as
needed. Task 4 is complete as amended, not source-qualified. This version
supersedes the original Task 5 history/schedule and prerequisite qualification
gates **only for the conditional DEVELOPMENT evaluation described here**.

No support response, new subscription, new agreement, or assertion of complete
history is required to run this study. Personal private noncommercial use and
the previously selected paper-key permission are settled. These waivers do not
establish licensing rights, provider completeness, execution evidence,
profitability, or authority to trade.

Status: design selected before economic outcomes; implementation and evaluation
not complete. A plan, inventory, or synthetic test is not Task 5 completion.

## Evidence-based range choice

Use the existing original Alpaca daily bars for SPY, QQQ, IWM, SHY, and IEF,
through a provenance-preserving range view `[2023-01-01, 2026-01-01)`.
Do not rewrite original responses, relabel their request dates, or manufacture
new native capture receipts.

This range was selected from action-field and calendar metadata, without
examining strategy performance. The retained calendar supplies 752 sessions.
The 109 supplied cash-dividend observations in this range have record and
payment dates, valid ex/record/payment ordering, and unique ex-dates per symbol:
SPY 12, QQQ 13, IWM 12, SHY 36, IEF 36.

The earlier 2022–2025 candidate range was rejected before outcome evaluation:
QQQ has two nonspecial observations for 2022-09-19, with the same amount but
different payment dates. This is an additional unresolved ambiguity, not an
adopted correction or duplicate. The prior missing dates, issuer-only dates,
amount conflicts, and SHY ambiguity are also retained and not resolved.

Known field conflicts are absent from the selected range; this does not prove
that no unknown omissions or errors exist. No issuer observations are injected.
The 2026 supplementary actions remain preserved but outside this study, which
does not need another download. Do not select a better-looking range after
seeing outcomes.

## Closed short-history protocol

Introduce exactly one new protocol, `observed-252x84-v2`; retain the existing
`legacy-750x126-v1` entry points, schemas, checks, and hash formulas by default.
Do not expose arbitrary optimizer-controlled study lengths.

| Dimension | Legacy | This development study |
| --- | ---: | ---: |
| Rolling training sessions | 750 | 252 |
| Purged closes inside training | 20 | 20 |
| Embargo sessions after training | 20 | 20 |
| Test folds | 5 | 5 |
| Sessions per test fold | 126 | 84 |
| Total test sessions | 630 | 420 |
| Global exit-only tail | 23 | 23 |
| Total used sessions | 1,423 | 715 |

For fold `i`, let `s = 84*i`. Train on `[s:s+252]`, permit training
decisions only on `[s:s+232]`, embargo `[s+252:s+272]`, test
`[s+272:s+356]`, and report the local exit-only tail `[s+356:s+379]`.
Local tails overlap later test folds and must not suppress later-fold entries.
The sole global entry halt begins at index 692.

Use session indices `[0:715]`; baseline 271; tests `[272:692]`; global
tail `[692:715]`; supplied suffix `[715:]` is unused (37 sessions).
Keep the full declared calendar, original archive identities, and used/unused
date lists in the input identity. "Unused by this run" does not mean untouched
historically. All 2023–2025 data is adaptive/previous-use-uncertain DEVELOPMENT,
never the final prospective test.

Signals use only bound history available as of each close, including elapsed
pre-training history in later folds. Do not reset feature warm-up at each
training start or invent earlier history. With the unchanged 200-bar readiness
rule, the maximum history-ready eligible training closes are 33, 117, 201, 232,
232. These are not trade counts or independent opportunities. Shorter history
weakens support; do not relax decision thresholds or claim increased power.

## Unchanged research and execution model

Preserve all 28 candidates, six capital tiers (100/250/500/1000/5000/10000 USD),
four round-trip friction levels (.05/.10/.20/.40 whole percent), five-fold
train-only selection, 29 continuous paths, and four comparison roles. The
complete new panel has 24 scenarios, 3,360 training trajectories, 696 continuous
paths, 24 constrained-SPY reference paths, 2,784 paired columns by 420 test
sessions, and 174 decisions. No cached winners or reused computed outcomes.

Keep the existing original-event account, risk limits, sizing, stop/exit logic,
policy ownership, settlement, pending/rejected/partial-fill handling, cash floor,
weekly review gate, kill controls, and paper/live separation. No broker calls.
No forced terminal fills, invented cash, inferred action dates, averaging down,
pyramiding, or suppression of incomplete account tails.

The new source model explicitly means **observed actions only**. Zero supplied
split rows is not certified zero split activity. Bind these limitations in
dataset and report identities: unverified split coverage, conditional absence
of unobserved splits, unverified dividend coverage, latest-vintage chronology,
unknown corrections, unverified access/retention terms, and raw daily OHLC not
executable quotes. Reject missing action fields or duplicate selected ex-dates;
do not resolve them by aggregation, inferred dates, or issuer overrides.

Use declared offline instrument/status/fractional and full-fill assumptions,
not backdated claims of historical broker availability. Declare per-order fees
and the episode bound explicitly before the run; the friction grid is an
assumed-cost sensitivity analysis, not observed fills. Retain unfilled/partial/
rejected behavior in tests. Weekly review dates are simulated approvals under
the unchanged review gate, not an actual operator review or runtime bypass.

Unknown allocated recurring expense remains `None`, so the entire operating
profit family and operating-risk results remain `None`. Known subscriptions
are not total operating cost. Sunk research cost and taxes retain their actual
known/unknown status. No claim of profitability, qualified costs, independent
support, or successful promotion follows a positive trading-only result.

Preserve block lengths 20 and 100, 1,000 resampling draws and the existing seed,
simultaneous family construction, stress/decision criteria, and unknown-support
criteria. The 100-session block has limited support in 420 dates; disclose that
limitation rather than treating resampled paths as independent observations.
Allowed verdicts remain REJECT or INSUFFICIENT_EVIDENCE, never automatic GO.

## Architecture and preservation

Implement in the separate `codex/etf-observed-development` checkout based on
`b0ff8add9ab809ba174c45fb7196c1ec2860bce9`. Preserve MAIN and SECOND, all old
pinned paths, source versions, raw originals, captures, logs, workload results,
stable lock and branches. Do not rerun the completed old synthetic workload,
193-pin audit, source review, release or CI unchanged.

Add explicit observed-range/dataset admission and a closed protocol descriptor.
Extend the existing private composition through finite exact-type dispatch;
reuse the same preparation, signal, account, risk, selection, comparison, and
statistics kernels. Do not copy a second evaluator, monkeypatch runtime
constants, subclass past validation, forge owned-source tokens, or weaken v1.
New variant records use explicit distinct hash namespaces. Adding fields to
existing canonical dataclasses must not silently change old preimages.

Before observing any economic outcome, freeze all original and derived source
identities, selected rows, dates, action-model limitations, canonical config,
exact clean code commit, declared fees/fills/instruments/review dates, costs,
protocol, selection, statistical settings and criteria in a new private
immutable manifest. No private inputs or credentials are delegated or committed.

Run one bounded offline evaluation after changed-source tests and independent
public-code review. A new execution specification must explicitly bind a
96-hour outer wall limit and 2 GiB peak limit, including setup, serialization,
validation and publication, using the reviewed suspend-inclusive custody
mechanism. This is a new development grant, not reuse of the spent synthetic
grant. No automatic retry, resume, stitching or post-outcome redesign.

## Definition of done

Task 5 is complete only when the new version is implemented and verified,
the inputs and assumptions were frozen before outcomes, the real complete
panel has an observed successful process/controller result and bounded report,
all required dimensions/identities are reconciled, and a readable results
report states limitations, unknown operating profit, decisions and next steps.
An evidence-supported rejection or insufficiency result completes this research
task; it does not complete the overall bot or authorize later activation.

Tasks 6–8 remain separate: conditional regime work, forward paper/shadow
qualification, and a genuinely prospective untouched final evaluation.
