# Options study registration and coverage

This is the offline real-data plan's registration library, not an economic result
or permission to trade. Actual provider rules remain unverified. All current tests
use fabricated data, including deliberately artificial calendars; they do not
establish historical SPY coverage. CLI composition remains Task 11.

## Canonical configuration

`options.research_study` extends the existing strict configuration and safety envelope.
Ordinary profiles leave it disabled. `configs/options/study/simulation.yaml` enables
only offline options/native-data/shortlist/study work, with paused startup and no
equity, crypto or prediction entries. Confidence uses whole-percent units: the
default and minimum is 95, never 0.95. A stricter release envelope can raise that
minimum or disable the feature. Execution and promotion fields are immutable false.
The exit policy is the approved signal-invalidation/prior-session-expiry hypothesis.
No risk limits, capital assumptions, subscriptions or deployment defaults change.

## Immutable preimages

`OptionsStudySpec` uses `options-study-v1`. Its hash binds exact decision sessions,
history/source/availability identities, current installed code and consumer identity,
fixed strategy/shortlist/exit policy, explicit scenario and cost hashes, all eight
hypothetical capital tiers, splits, final test, horizon/embargo, block lengths, seeds
and rejection criteria. Contract terms, source semantics and initialization calendars
are also bound when supplied for coverage composition. Missing values do not become
inferred source facts. Changing the study produces a different identity.

`VerifiedHistoryCoverage` retains actual canonical daily-bar/session preimages,
availability and native observation hashes. Despite its name, construction is not
verification. `validate_study_registration` rereads private evidence and invokes the
installed source verifier. Duplicate session dates, bar identities and overlapping
native observations cannot inflate the count. Interpolated or non-daily bars deny.
Calendar, publication and actions coverage are independently required.

The `options-observed-history-v2` preimage retains the exact SPY/unadjusted action
coverage window and its typed actions (including explicit empty coverage), plus
the source verifier's causal claim hashes. Registration recomputes those claims;
identical file bytes do not permit substituting different coverage/provenance.
Earlier study files remain readable, but their previous history/code identities
cannot qualify under the changed verifier and require a new registration.

Registration checks 750 observed daily bars, the declared and verified 3,650-day
history span, five chronological test folds of at least 50 sessions, and a separate
final test of at least 50. Training outcomes plus embargo must end before each test;
test outcomes plus embargo must end before subsequent tests. Resampling blocks may
not be shorter than the maximum outcome horizon. These are input/split checks, not
proof of sufficient independent outcomes; that evaluation remains a later stage.

`freeze_options_study` publishes privately and atomically without overwriting old
artifacts. Qualification declarations with failed prerequisites deny. An explicitly
labelled engineering pilot may retain insufficient-history/split diagnostics but
cannot ignore source-integrity or identity failures. Known late registration denies.
Synthetic history adds `study_sources_not_genuine` to qualification declarations
and their v2 acquisition diagnostics; such declarations cannot be frozen. Fixtures
can be frozen only as explicitly non-qualifying engineering pilots.
The declaration alone cannot prove an operator never inspected outcomes outside the
program: the later consumer must enforce its freeze-before-open access journal.

## Versioned coverage

`plan_options_study_coverage` emits `options-acquisition-manifest-v2` and reuses the
existing window union/batching and structural checks. Old v1 manifests remain
readable with unchanged serialization; v1 qualification remains denied. V2 separately
adds fresh observed-history/split findings and binds the study/history hashes.

Both fixed candidates retain initialization, entry, monitoring, prior-session exit,
expiry and settlement obligations, plus underlying quotes, warmup and references.
Insufficient contract calendars, unknown semantics, missing/denied sessions and
outcome tails beyond the declared horizon remain explicit. Shared windows are
deduplicated; outcomes never select which side to buy data for. This planner checks
structural requirements, not purchased data completeness or purchasing authority.

All emitted economic, production, promotion, download and live flags remain false.
Source approval, scenario calibration, untouched outcomes, economic evaluation,
runtime/broker capabilities and operator live authorization remain separate gates.

## Remaining path

Resolve actual source protocols without support outreach; freeze a source-qualified
calendar-selected pilot; reconcile existing and uncertain acquisitions; verify the
complete necessary package against current applicable credits. Only then may the
standing credit-only grant be used. The historical episode, continuous-account
journal, cost/baseline analysis, dependent uncertainty and command/report composition
remain subsequent implementation tasks. No live activation is part of this work.
