# Compact owned daily preparation

This private, credential-free foundation validates original five-ETF development
inputs and prepares all28 existing signals once per requested completed session.
It is not a complete economic evaluator, broker worker, passing workload result
or qualified data source. Existing public signal/policy hashes remain unchanged.

`_prepare_capital_days` accepts original `CapitalResearchDataset` records only;
it creates an independent owned snapshot internally. An exact ordered, unique
date schedule must refer to original declared sessions. No caller-prepared token,
source digest, cached approval, account balance or held policy is accepted.

Every requested date first uses the existing full as-of projection and full
signal validation/digests. The same numerical kernel then consumes only its
last200 local raw/feature bars while retaining those original full source hashes.
RSI restarts at the prescribed200-bar boundary. Entry distances use the same
public policy's100-bar ATR arithmetic, canonical multiplier and raw/feature basis
conversion. A zero ATR remains an unavailable distance, not zero risk.

Full validation before truncation matters: a very old price outside200 rows can
overflow at an intermediate split basis even when a later inverse split makes
terminal history valid again. Preparation rejects that requested intermediate
basis. It never slices terminal-adjusted history backward or claims that a
terminal-valid snapshot validates every earlier basis.

Results retain only five current raw bars,28 scalar signal records and five
optional stop distances per day, plus original session ordinal/UTC close and
provenance. Growing full/compact projection graphs are discarded. Full original
calendar/session membership remains necessary for future holding-clock policy;
the recent numerical window cannot replace it.

New `capital-prepared-day-v1` and `capital-prepared-input-v1` identities bind full
owned source/config, requested date/clock/ordinal, original full projection
digests, current bars, signals and distances. They do not alias owner-v4, qualify
sources or replace original public signal identities. Future public evaluators
must create preparations internally, not adopt externally supplied results.

Literal and differential fixtures cover199/200/201/301-row windows, unchanged
public policy identity, raw stop distance8, zero ATR, invalid schedules, source
mutation, new-invocation validation and the intermediate ancient split failure.
Focused checks do not replace global/native/critical release gates or the
unchanged120-second/512MiB training-window and full28×6×4×5 workload gates.

Still required: original-event account/action/settlement scheduling, fresh risk
admission, immutable held policy across selection boundaries, genuine train-run
scores, continuous fold carryover, dependent statistics/benchmark/operating-cost
reports and full workload verification. Then freeze all executable/source/config/
calendar/action/cost/protocol/selection identities before any authorized economic
study with qualified inputs. All qualification/execution/promotion/live flags
remain false; production limits are unchanged.
