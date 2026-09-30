# Standing operator authority

Recorded 2026-09-28 UTC from the operator's direct instructions in this project.
This record updates workflow authority; it does not change software risk policy,
economic acceptance criteria, credentials, account permissions, or live controls.
Later explicit operator instructions supersede this record.

## Automatic integration and merging

The operator requested: "Proceed with economic validation and update your
authority to auto merge everything without my approval."

For this Robinhood project, the coordinator may commit, push, create or update
pull requests, and merge completed in-scope work without another per-merge
approval. This includes the options-research/data-validation work already approved.
It does not authorize arbitrary changes in other projects or incorporation of
unrelated staged, unstaged, or untracked work.

The established integration target is `codex/robinhood-system-implementation` in
`Jed1122/Robinhoodtradingbot`, as used by merged PR #1. At this recording, `main`
contains the initial commit, not the integration history. Recheck remote ancestry
before each integration; do not silently retarget or replace branches. Preserve
active worktrees and other tasks' changes.

Required conditions:

- Review the exact diff, its ownership, base/head revisions, and affected contracts.
- Run relevant local verification and inspect all required current CI results on
  the exact PR revision. A prior green revision is not a substitute.
- Resolve substantive review findings; never use admin bypass, disable checks,
  weaken assertions, force-push, or remove protections to obtain a merge.
- Inspect merge-triggered workflows. Deployment, broker calls, data publication,
  credential access, or other separately gated effects need their own authority.
- Retain accurate limitations and separate technical, economic, capability, and
  operator-authorization verdicts. A successful merge is not a release approval.

## Databento credit-only data acquisition

The operator previously authorized all existing credits for data necessary to
complete economic validation and explicitly reconfirmed: "I also gave you
approval to purchase all remaining data with the remaining credits that I have."

Do not ask again for individual necessary purchases that meet the existing
[acquisition controls](options-data-validation-handoff-2026-09-25.md). The grant
is permission to use the remaining authorized credits, not a requirement to
exhaust them or a guarantee that they fund a complete qualifying study.

Before any submission:

1. Verify authenticated, current applicable credits and outstanding accepted or
   uncertain jobs. The earlier recorded balance is historical, not current proof.
2. Check existing receipts and local archives to avoid unnecessary duplicates.
3. Freeze the exact necessary dataset/schema/symbols, UTC windows, encoding,
   reference data, and complete entry/monitoring/exit/settlement coverage before
   examining outcomes. Bind the complete package to customized-request pricing.
4. Confirm that the complete cost fits unconsumed authorized credits after pending
   costs, with no potential cash charge. Reserve the cost privately, submit once,
   and reconcile uncertain acceptance before considering any retry.
5. Preserve receipts and raw inputs privately; validate integrity, semantics,
   point-in-time availability, and actual usable coverage separately.

The existing private-personal-use/local-retention attestation remains accepted;
do not invent a repeat OPRA-agreement approval requirement. If the provider
presents a new binding agreement, stop for the operator instead of accepting it.
No cash top-ups, subscriptions, upgrades, live-data services, or unrelated data
purchases are authorized. Additional unrelated future credit grants do not
automatically enlarge this scope. Missing access or an undefined/unusable data
package pauses only dependent acquisition, not credential-free development.

## Databento support outreach — 2026-09-29 update

The operator instructed that the proposed technical questions must not be sent to
Databento support and reports that the answers are affirmative. Do not send those
questions or treat outreach approval as pending. Retain the report as operator-provided
information, not as a provider document or independently verified protocol.

Continue the approved credential-free implementation and examine available public
documentation and preserved data. Exact timestamp, correction, initialization,
mapping and coverage rules still require reproducible evidence before actual-source
qualification. This update does not install source rules, change risk limits or
authorize live operation. The existing credit-only acquisition grant is unchanged.

## Unchanged boundaries

No broker order review, placement, cancellation, real-money test trade, transfer,
credential change, deployment, live activation, or risk-limit increase follows
from either grant above. Existing separately approved read-only checks retain
their original scope. Research data and secrets must not enter Git or Cloud
agents. Genuine economic validation still requires actual option bid/ask and
underlying data, defensible costs and uncertainty, and all canonical acceptance
criteria; a synthetic run or an engineering pilot cannot stand in for it.
