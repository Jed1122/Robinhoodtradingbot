# Bounded repeatable stock research lifecycle

The local implementation now composes repeated research invocations through the
actual release-file verifier, operations store, Engine transports, prestart verifier
and supervisor. It is not an installed scheduler or verified continuous service.
It does not submit brokerage orders or enable live trading.

`infra.hybrid.stock_launcher.run_research_cycle(store, release_path)` requires the
held, fixed root operations context and a `manifest.json` file, not its directory.
Its result is `completed` for a durably observed worker termination, or
`recovery_only` for an invocation consumed by recovery or shutdown. Neither means
that research succeeded, that a strategy is approved, or that buying is authorized.
Worker exit diagnostics remain in the supervision result and stopped receipt.

## Implemented protocol

Explicit new initialization writes protocol 2. Protocol 1 remains readable for
bounded cleanup and incident inspection; it cannot admit, create or start a worker.
There is no automatic migration, reset, receipt rewrite or history pruning.

Every v2 attempt binds its logical predecessor and terminal hash. A stopped
predecessor also supplies the full physical container ID and stopped-record hash.
A successor resolves that physical retirement before preparing CREATE. An abandoned
predecessor supplies no invented container identity. Validation walks the complete
retained lineage, rejects unreferenced attempts and rejects historical CID reuse.

The CREATE transport itself persists and acknowledges a dispatch fence binding the
actual canonical worker-body hash and original five-second deadline, before opening
the connection. It checks the same issued fence again before sending. Copied objects,
reopened records, failed acknowledgements, changed bytes and renewed deadlines grant
no dispatch authority. CID recording and START retain the acknowledged bindings.

Retirement first persists its intent, then inspects only the stored predecessor's
full CID. DELETE requires a fresh owned stopped observation matching the retained
lifetime. Its sole route sets `force=false&v=false&link=false`. A closed 204 with
empty body and final EOF acknowledges removal. Each exchange has one absolute
five-second budget inside one issued fifteen-second retirement cap; there is no
retry loop. A later invocation can resolve a lost acknowledgement separately.

Scoped inspect 404 requires the exact singleton JSON message
`No such container: ` followed by the owned full CID, after the durable stopped and
removal-intent chain. Generic route errors, names, wrong IDs, malformed framing and
uncertain CREATE are not absence evidence. This comparison follows the pinned
[Moby API schema](https://raw.githubusercontent.com/moby/moby/d105562beff448ae44d6e3a2f7738b235fd197b5/api/swagger.yaml),
[lookup implementation](https://raw.githubusercontent.com/moby/moby/d105562beff448ae44d6e3a2f7738b235fd197b5/daemon/container/view.go)
and [HTTP handling](https://raw.githubusercontent.com/moby/moby/d105562beff448ae44d6e3a2f7738b235fd197b5/daemon/server/server.go).
The [lookup consistency caveat](https://raw.githubusercontent.com/moby/moby/d105562beff448ae44d6e3a2f7738b235fd197b5/daemon/container.go)
remains relevant. These sources do not establish native process absence, daemon
quiescence, full-ID nonreuse or compatibility on the intended host.

The opener classifies entry state once under its lock, before exposing the store.
An unfinished entry consumes all admission/dispatch authority. Recovery burns those
capabilities before fallible validation and ends the invocation. Only a later fresh
invocation can reconfirm terminal state and admit a successor. Complete STOP bytes
left after a lost fsync acknowledgement still require fresh matching observation
and durability reconfirmation. CREATE-fenced uncertainty is never reinterpreted as
abandonment merely because a generated name cannot be found.

Shutdown handlers are installed before admission. The same requested state reaches
CREATE, START and supervision; transports check it before acquiring authority and
again before sending. Existing requests can complete after a signal, so immutable
receipts and recovery remain necessary. Shutdown never authorizes another launch.

## Local checks and limits

Store TDD passed 150 tests. Store, mutation, retirement, supervisor, termination and
legacy first-attempt tests passed 394 checks at the Task 2 checkpoint. The combined
new cycle and shutdown increment passed 417 checks, including 21 composition tests
using real temporary manifest files, actual persistence/verifiers/transports and a
fictional Engine wire. They cover three successive runs, admission/CID/START/STOP
write failures, lost CREATE/DELETE/START acknowledgements, typed absence, shutdown,
legacy denial and manifest-directory rejection. No native Docker or broker action
occurs in these tests. Integrated review and revision-specific full regression are
separate acceptance gates, still pending at this checkpoint.
The broader stock deployment, architecture, worker configuration/CLI and persistent
worker selection passed 1028 checks. Ruff, mypy over application source and the five
affected host modules, expanded Bandit and the dependency-lock check also passed.

The fixed-root command is:

```sh
python -m infra.hybrid.stock_launcher /opt/hybrid-stock-research/releases/RELEASE_ID/manifest.json
```

It constructs the real operations context and transports internally. It has no
socket, account, credential, UID, clock, CID or live-mode override. An uninitialized
or unsafe namespace fails closed. Its small JSON status describes lifecycle only.
This command is not a deployment or initialization instruction.

Native inert lifecycle verification, release production and executing-image proof,
exclusive credential refresh, disabled-timer installation, backups/restore,
monitoring and actual scheduled collection remain required. Retained history is
bounded at 8192 attempts; capacity monitoring and controlled maintenance are not yet
implemented. No promise of indefinite unattended operation follows from this store.
Source semantics, strategy validation, brokerage reconciliation and explicit live
activation remain independent gates before automated stock buying.
