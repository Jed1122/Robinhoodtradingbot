# Original-input walk-forward development composition

`replay_capital_walk_forward` accepts original `CapitalResearchDataset`, one
of the six research cash tiers, five explicit instrument assumptions, fees and
fee bound, one approved friction level, explicit weekly-review dates and bounded
execution outcomes. It accepts no prepared data, training scores, winners,
balances, latches, callbacks or independence counts. Research declarations are
not authenticated source, cost, account, reconciliation or broker evidence.

The invocation privately owns originals and prepares the first1,423 used dates
once. Unchanged five calendar-anchored folds each own750 training sessions,
730 decision-eligible closes,20 purged closes and20 embargo sessions. A final
eligible decision may execute at the next opening during the purge; no training
run extends into embargo. Training cutoff is its last close plus three synthetic
seconds. Selection occurs at the close immediately before the test starts.
Earlier folds' elapsed dates may enter subsequent rolling training; these are
adaptive development folds, not an untouched final test.

All28 training trajectories per fold use0.40% round-trip friction regardless
of selected/test cost. Their original events, final account, hash and nullable
complete dollar profit are retained. Only flat, fully settled, final-fee-complete
outcomes can rank. Incomplete paths remain visible exclusions, not zero-profit
paths. The existing pure selector chooses the greatest strictly positive complete
USD profit, ties by frozen grid order, otherwise cash. It does not infer a
statistically supported edge or economic admission.

One selected account and28 fixed comparison accounts each run continuously from
original index769 through1422. They retain cash, reservations, obligations,
loss latches, streaks and the policy bound to the original opening BUY. At
session895, its opening still belongs to fold0's previous instruction; its close
prepares fold1's instruction for opening896. A new close winner cannot cancel
an eligible instruction retroactively at that day's opening. Cash selection
does not remove existing positions or finalize partial/submitted orders.

Intermediate local tails overlap subsequent normal test sessions. They are not
unioned into an entry halt. Only the final global tail1400–1422 forbids new
submissions; close1399 cannot schedule a new entry. No forced terminal sale,
payment, settlement or fee finality is introduced. All used and unused source
dates are reported. Default-empty weekly-review assumptions retain the shared
denial gate, not automatic research approval.

The private trajectory seam reuses the same original-event execution loop,
account reducer, risk/loss controls, sizing and configuration. Public trajectory-v1
preimages and owner-v5 identities are unchanged. Separately scheduled opening
winners bind a new private namespace; they are never public approval tokens.

Synthetic path-orchestration tests use clearly identified doubles to inspect the
140 training attempts and continuous schedules. Real shared-kernel fixtures
independently check adverse prices, literal cash, old-opening/new-close timing,
original holding exits and settlement/finality. These controls are not a full
workload benchmark or historical economic evaluation.

## Existing denial and statistical primitives

The daily owner's exact-bool `entry_decision_allowed` and
`entry_submission_allowed` frame controls remain denial-only. They cannot bypass
original-state risk/sizing, settled cash, reservations, ownership, loss latches
or kill controls. A suppressed instruction is not delayed into a later opening;
held-position exits and existing obligations continue independently.

`select_capital_training` remains a pure, non-authoritative helper when called
directly. Its declarations and original-run hashes bind ranking integrity, not
proof of genuine fills or authenticated cost/source completeness. The new owning
composer derives those declarations from its own original-event paths instead
of treating supplied scores as evidence.

`dependent_simultaneous_mean_intervals` retains the shared seeded draw engine
and unchanged legacy individual results. Equal-length columns share noncircular
block starts. Each draw takes the maximum absolute centered mean error over the
supplied columns; the outward95th-percentile radius gives conditional two-sided
bands. Defaults are1,000 draws and20/100-session blocks. These are model-dependent
bootstrap bands, not guaranteed coverage or an independent-opportunity estimate.

The report adapter still must bind the complete29-path/six-capital/four-cost/
three-reference family (2,088 columns), exact dates, identities and all attempted
paths. Numeric length validation alone authenticates neither labels nor family
completeness. Draw counts and completed episodes never become independent support.

Statistics, compatible benchmarks, complete workload/resource verification and
economic executable preregistration remain separate unfinished composition.
Qualified authorized five-symbol source/calendar/actions and defensible costs
are not established by this module. Every source/cost/execution/economic/
promotion/live eligibility flag remains false. Existing production limits and
live blocks remain unchanged. Merge is not deployment or profitability proof.
