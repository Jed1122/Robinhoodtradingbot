# Spent build reconciliation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> for root-owned filesystem/native work; independent pure codecs and diagnostics
> may use superpowers:subagent-driven-development. Steps use checkboxes.

**Goal:** Reconcile only demonstrably terminal failed legacy builds as permanently
spent, so a different source can undergo its own full release qualification.

**Architecture:** A pure negative-chain validator, fixed read-only host observer
and separate root reconciliation owner extend the existing two-stage
facts/current-success model. History admission recognizes successful and qualified
spent-failed families; all other partial histories stay blocked. Diagnostics do
not confer authority.

**Tech Stack:** Python3.12+, standard library, existing fixed Engine transport and
producer filesystem/clock helpers; existing Pytest/static/coverage tooling.

**Spec:** `docs/superpowers/specs/2026-10-23-spent-build-reconciliation-design.md`

## Global constraints

- No live trading, broker/account/order calls, credentials, paid services or
  unrelated runtime changes. No native action follows plan/test success alone.
- Preserve original source479/a54 exit1, every original byte, namespace and source
  spending. No same-source replay, deletion, rename, reset or private-stage call.
- New record: `failed-build-terminal.json`, schema1,
  `stock_failed_build_terminal_facts`, mode0600, maximum16384bytes.
- Fixed Ubuntu29.1.3 profile/hash and seven original causal hashes are copied from
  the spec; no runtime profile/root/endpoint/policy override.
- Reconciliation120seconds; GET budgets at most5seconds each; failure-closed
  filesystem/clock/lock/durability gates. Capacity5GiB/4096inodes as specified.
- Current regression/static/coverage gates remain unchanged; critical tests never
  access real Docker, credentials, brokers or live services.

## Review focus

1. A complete quiet marker with lost EOF/close must never become producer success.
2. A caller-created observation/profile object must never authorize a facts write.
3. Successful and failed histories sharing one release parent must remain coherent.
4. A late cleanup error must preserve the first failure and deny current success.
5. Different-source admission must perform every fresh native stage, not reuse facts.

---

### Task 1: Pure failed-build evidence and facts

**Files:** create `infra/hybrid/stock_failed_build_inputs.py`; test
`tests/deployment/test_stock_failed_build_inputs.py`.

**Interfaces:** consumes original source/input/namespace/six bounded file bytes.
Produces a frozen `FailedBuildEvidence` data object with derived source commit,
image ID, original origin/dispatch/preparation clocks and original hashes.

- `inspect_failed_build(source_sha256: str, namespace_raw: bytes, input_raw: bytes,
  original: dict[str, bytes]) -> FailedBuildEvidence` validates exact six names,
  source/clock/canonical/hash links, fixed request, qualified original Engine
  identity and strict quiet reply using existing parsers. It performs no I/O.
- `encode_failed_facts(evidence: FailedBuildEvidence, *, observation: dict[str, Any],
  directories: dict[str, list[int]], files: dict[str, dict[str, Any]]) -> bytes` and
  `validate_failed_facts(raw: bytes, evidence: FailedBuildEvidence, *,
  directories: dict[str, list[int]], files: dict[str, dict[str, Any]]) -> dict[str, Any]`
  implement the exact negative schema and recorded observation/clock invariants.
  Data objects/encoded bytes never confer authority or write files.

- [ ] Write RED tests for the actual six-file shape and derived marker, zero I/O,
  strict bool/integer types, missing/extra fields, mismatched hashes/commit/
  namespace/request/profile/clocks, prefixes/error/extra frames and forbidden
  positive claims. Test canonical round-trip and mutated negative/profile/clock/
  file/directory fields; assert supplied data cannot cause a native operation.
- [ ] Run the focused file and retain the expected failures.
- [ ] Implement the pure codec with closed field sets, finite bounds and existing
  canonical JSON/source/HTTP/clock helpers; no permissive fallback.
- [ ] Run focused tests, Ruff and strict mypy for this module. Independently review
  evidence semantics against both actual source reports before integration.

### Task 2: Fixed read-only qualified observer

**Files:** create `infra/hybrid/stock_build_profile.py`; test
`tests/deployment/test_stock_build_profile.py`.

**Interfaces:**
`observe_build_profile(source_commit: str, original_engine: bytes,
original_origin: dict[str, Any], *, not_after_ns: int) -> dict[str, Any]`.
Roots, socket, qualified hashes, version, data-root policy and Git argv are fixed;
the source checkout path is derived only from its verified Git commit. The owner
calls this fresh; it never accepts a supplied observation as an alternative.
`check_failed_capacity(capacity: dict[str, Any]) -> None` checks fresh current
DockerRootDir via fixed bounded GET/info and canonical root path/identity/headroom,
including after reboot without original-boot/process requirements. First closure uses
the stricter conservative pre-origin BOOT-time bound from the spec. Only exact
source479/tree982/archivea54 qualifies this initial causal profile.

- [ ] Write RED tests with harmless process/socket/filesystem fixtures for Linux/
  root/loopback guards; systemd socket activation (root listener peer PID1 versus
  daemon MainPID, exact official units/no overrides, shared kernel listener FDs);
  same-peer version/info reads; binary identity/hash/mode/
  size/stability; process start/boot binding; original-source clean/module hashes;
  canonical DockerRootDir and capacity. Test conservative tick upper bounds,
  same-tick/post-origin starts, suspend and unknown clock domains; independent
  later-boot capacity checks and changed-current-data-root denial. Exercise short I/O, peer change, symlinks,
  timeout/shutdown and resource uncertainty. Default native Docker is denied.
- [ ] Implement bounded fixed GETs using existing transport primitives, validate
  actual root peer/executable and source, then canonical data-root/headroom facts.
  Never execute downloaded/source code or write any native state.
- [ ] Run focused tests/static checks; independently review fixture seams to prove
  caller data cannot select a production root/endpoint or mint write authority.
- [ ] Before any eventual native closure, independently verify this observer in a
  read-only isolated invocation against preserved actual files; retain actual exit.

### Task 3: Root owner, CLI and historical admission

**Files:** create `infra/hybrid/stock_failed_build.py` and
`infra/hybrid/stock_producer_reconcile.py`; modify
`infra/hybrid/stock_producer_history.py`, `stock_release_producer.py`; test
`test_stock_failed_build.py`, `test_stock_producer_reconcile.py` and extend existing
producer-history/final-gate tests.

**Interface:** `reconcile_failed_build(source_sha256: str) -> Path`; public CLI
has this source argument only. Success emits one compact canonical object with
`status=spent_failed_build_reconciled` and its `facts` path, only after actual
context/descriptor/lock cleanup. No producer manifest or old result is returned.

- [ ] Write RED lifecycle tests: permanent lock contention, unknown other history,
  exact originals/no target release, fresh observer required, substituted namespace/
  original file, exclusive publication, partial write/fsync/readback/close, timeout/
  shutdown, existing fact denial and zero mutating Engine/worker calls.
- [ ] Implement the root-only finite context with current owned authority and fresh
  reads, exact identities/inventories, exclusive facts write, durability/readback
  and final cleanup/window checks. Private disposable fixture seams cannot target
  production. No initializer or repair path exists.
- [ ] Extend history classification without authority: successful, spent-failed,
  or invalid/partial. Release-parent inventory contains successful families only.
  Every history still validates and flushes before a new mutable stage. Preserve
  existing positive chain code; validate failed chains using Task1 and fresh pins.
- [ ] Run RED/GREEN integration tests: mixed history, both terminal families,
  partial/malformed facts, changed profile/file/namespace/clock, complete facts
  after caller-only lost acknowledgement, same-source permanent denial, and a
  different source's complete fresh build/probe/render/publication/cleanup.
  Assert every fresh stage actually runs and no old image/probe acknowledgement
  is adopted. Re-run existing source/build/probe/history/publication/final gates.
- [ ] Document CLI/negative-only distinction and update closure/operations docs;
  no document may declare current native reconciliation or release success.

### Task 4: Future failure diagnostics

**Files:** create `infra/hybrid/stock_producer_diagnostics.py`; modify
`stock_build_engine.py`, `stock_producer.py`; test
`test_stock_producer_diagnostics.py` and focused build-engine/CLI faults.

**Interfaces:** a private `capture()` context; `phase(name: str)` context; and
`failure_diagnostic() -> str | None`. The CLI controls capture and failure-only
stderr output. Fixed phases cover connect/send/receive/EOF/close/response-retain,
lease checks, parse, imageGET/retain/verify and build-complete. Helpers never emit
data themselves or alter dispatch/exception/cleanup behavior.

- [ ] Write RED tests: receive ECONNRESET followed by close EIO and retain ENOSPC;
  first failure survives, later cleanup separately bounded. Include policy/parse/
  imageGET and failed diagnostic sink, secret-bearing exception text, no active
  capture, success silence and unchanged exact stdout/exit contracts.
- [ ] Implement first-failure in-memory allowlisted phase/family/errno collection,
  at most1024bytes canonical failure stderr; never messages/args/paths/payloads.
  Preserve original denial even if collection/emission fails. Never retry.
- [ ] Run diagnostics/build-engine/CLI tests and static checks; root integrates
  only after independent review. Do not claim an original cause was discovered.

### Final verification and native handoff

- [ ] Independently review the complete diff, pure/native separation and all five
  review-focus cases. Fix substantive findings; inspect current source identity.
- [ ] Freeze a clean revision. Run one full current-stock regression with coverage
  and the existing critical gate; whole Ruff, strict mypy, Bandit and lock/audit.
  Keep original handle, logs and actual terminal result. Inspect exact current CI.
- [ ] Normal commit/push/PR/merge follows standing authority, no bypass. Inspect
  postmerge CI. Source identity for native artifacts remains its actual commit.
- [ ] Prepare a root-owned exact source/observer harness. First run only the
  read-only qualified observer. Review actual original namespace/file/capacity/
  daemon/source facts. If any obligation fails, stop dependent native steps.
- [ ] Root may then invoke one public reconciliation CLI under the actual lease,
  retain its handle/PID/actual result and independently inspect unchanged original
  evidence plus the single negative facts file. No original producer success.
- [ ] Stage a genuinely different clean source and call the normal public producer
  once. Require actual complete success before maintenance/runtime/paused-upgrade
  work. Never rerun source479/a54 or duplicate an ambiguous invocation.
- [ ] Resume the original Task3 runbook: real scheduling/jobs, backups/restore,
  monitoring/recovery/reboot and separate future auth gates; live stays disabled.
