# Current stock investing implementation plan

Base: eabd6253bbd28973ea86504fdd5f1f3331edbf71 in the isolated
codex/task5-current-stock-decisions checkout. The current design governs scope;
historical strategy qualification remains separate and deferred.

1. Freeze current decision/evidence contracts and monthly holding inputs/results.
   Use existing source models where useful; do not add execution capability to
   collector types or fake historical eligibility.
2. Implement pure current fundamental/tactical decisions and scenario math with
   short genuine RED/GREEN tests; preserve missing/contradictory inputs.
3. Implement a pure month-review/mandate evaluator independently, with no network,
   account lookup, fake calendar or automatic order.
4. Integrate verified archive/report consumption, durable decision/proposal
   records and sleeve/risk-aware target mapping. Reuse the existing persistence,
   accounting and idempotency owners; no duplicate cash ledger.
5. Implement/verify the explicit current-research approval basis and official
   adapter/reconciliation seams. Keep default live flags false; all development
   execution tests use deterministic simulated brokers.
6. Independently review/integrate, run appropriate regression/static checks, and
   document observed scheduled research and remaining external broker/auth
   dependencies. Separate actual deployment and user-controlled activation.

Root owns this plan/specification, config and runtime integration. Exact delegated
source/test ownership is recorded before parallel implementation. No commit/push
or provider/account/order/deployment action is performed by a worker unless root
assigns that concrete step. Root may integrate/merge routine verified code under
the existing human authorization.

Implementation status: steps 1–5 and the local independent review/integration
checks in step 6 are complete. Release CI and merge verification remain pending.
The current scope ends at source-bound proposals and software verification;
actual official-account execution/reconciliation and deployment follow Task 5.
See `docs/current-stock-selection.md` and its validation companion for runnable
commands, verified checks and explicit remaining dependencies.
