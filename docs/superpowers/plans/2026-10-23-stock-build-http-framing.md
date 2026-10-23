# Stock build HTTP framing implementation plan

Spec: `docs/superpowers/specs/2026-10-23-stock-build-http-framing-design.md`.
Base: bac162fd6eb6178516a212d30846fb1a055c90fb/tree21953af2.
Workspace: `.superpowers/sdd/2026-10-23-stock-build-http-framing`.
Continue authorized Task3; live disabled. No native operation in implementation.

## Independent workstreams

1. Root freezes historical HTTP/1.0 helpers in `infra/hybrid/stock_build_legacy.py`,
   exporting pure `_source_request(source)` and `_body(raw)` with existing exact
   bytes/semantics. Add independent golden compatibility assertions. Root updates
   positive-history selection to exact legacy/current request generations and
   matching response validation, preserving every other gate.
2. HTTP implementer owns current `stock_build_engine.py`, a pure current framing
   module if useful, and its deployment tests. First reproduce open-peer/reset and
   truncated/malformed/trailing cases RED; implement fixed HTTP/1.1, strict bounded
   framing, nonblocking queued-byte policy and unchanged normal producer stages.
3. Cohort implementer owns `stock_failed_build_inputs.py`, `stock_build_profile.py`
   and their deployment tests. Import root's frozen historical helpers. Add exactly
   two immutable cohort records and derive profile selection internally. First
   reproduce bac denial and mixed-cohort cases RED; preserve old canonical facts.

Keep independently edited files disjoint. Communicate helper signatures before
edits and coordinate shared fixtures. Do not construct expected historical bytes
through the changed current encoder. No generic profile-registration framework.

## Integration and release

4. Root reviews/integrates both workstreams, resolves fixtures/history interfaces,
   verifies focused tests and unchanged failure ownership/diagnostics. Perform one
   fresh whole-change review, fix substantive findings with RED/GREEN regressions,
   then one exact-head current-stock full regression/static/coverage pass.
5. Commit/push/normal PR to `codex/robinhood-system-implementation` under standing
   authority. Inspect exact-head required CI/reviews, normal merge and merge CI.
   Preserve all originals; no reruns of unchanged terminal regressions.
6. Root separately plans/reviews native immutable source materialization, read-only
   two-cohort profile observation and one public8294 negative closure. No replay
   of479/a54 orbac/8294, manual facts, reset or private production-stage calls.
7. Only a genuinely different source may run a fresh normal public producer once,
   with actual complete source/build/probe/render/publication/terminal results.
   Existing installed97 worker/control/credential/units stay unchanged until that
   qualification; paused runtime upgrade and all remaining Task3 gates follow.

Completion here means the framing/compatibility change is independently tested
and genuinely qualified as scoped; Task3 also still requires scheduled operation,
monitor/backup/copy/application restore/restart/reboot and future authentication
evidence. No test, merge or negative closure alone completes Task3.
