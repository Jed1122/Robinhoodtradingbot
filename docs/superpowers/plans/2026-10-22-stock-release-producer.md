# Trusted Stock Release Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement inline, with one fresh whole-branch review after integration.

**Goal:** Produce a source-bound stock research image and durable verified release without starting research or investing.

**Architecture:** Own a bounded source archive, fixed Engine build, fresh existing probe, reviewed Compose render and exclusive publication. Keep actual-operation provenance separate from the four unchanged release schemas. Public entry accepts only a source SHA; supplied observations never replace native operations.

**Tech Stack:** Python3.12, stdlib tar/JSON/socket/filesystem/subprocess, existing stock validators, Pytest.

**Spec:** `docs/stock-release-producer-design.md`

**Task3 clarification:** [Terminal facts and current acknowledgement](../../stock-release-producer-closure.md).
Historical distinct-source admission must validate the complete closed chain and obtain
fresh actual durability acknowledgements. It cannot reconstruct a prior caller result,
return an old successful manifest, replay a source or adopt old native authority. This
clarifies the original post-terminal lost-ack gap; all current-call final gates remain.

## Global Constraints

- Work only in the producer checkout; frozen controller8629cad/full55324 remains unchanged.
- No native build, Docker mutation, deployment, credential operation, broker call or live activation in this implementation wave.
- Existing Dockerfile, pinned base, canonical config, worker/probe profiles and four release schemas stay unchanged.
- Fixed Linux-root namespace `/var/lib/hybrid-stock-producer`; fixed release root and socket; no public path/UID/endpoint/cap override.
- Source16MiB/2,048 entries/1MiB file; build response1MiB; original producer1,200seconds/build900seconds; no cap renewal or request replay.
- Quiet legacy Docker29.1.3/API1.52 build; explicit public build dependencies, no implicit no-registry claim.
- Root owns protected implementation; independent aids remain read-only. One final review and one RED/GREEN fix pass; defer minors explicitly.

## Review Focus

- Valid intermediate-stage output or truncated quiet replies must not become a final image identity: Task1 negative wire-result cases.
- An internally consistent supplied archive/result/receipt must not bypass owned native operations: Tasks2/3 replay and replacement tests.
- Clock/shutdown changes during upload, fsync, subprocess cleanup or final publication deny success: Tasks2/3 boundary tests.
- Root namespace substitution, overlapping publishers and complete unacknowledged files must not yield publication/replay: Task2 filesystem cases.
- Ambient client credentials/dotenv/proxies or Compose normalization drift must not affect release identity: Task3 scrubbed renderer/real-loader composition.

## Task 1: Bounded source and quiet build-result data

**Files:** Create `infra/hybrid/stock_build_inputs.py`; test `tests/deployment/test_stock_build_inputs.py`.

**Interfaces:** Produce frozen `SourceArchive(digest, commit, raw, base_ref, dockerfile, compose_template)` with hidden repr; `inspect_source(raw: bytes, *, expected_sha256: str) -> SourceArchive`; `build_image_id(raw: bytes) -> str`. These functions consume supplied bytes only and grant no dispatch/publication authority.

- [ ] Write missing-module REDs for safe complete source and exact quiet success, with assertions for computed digest/Git/base/assets and full image ID.
- [ ] Add source bounds/UID/mode/type/path/PAX/duplicate/trailing/missing-content/hash failures and quiet aux/progress/error/multiple-object/truncation failures.
- [ ] Run `PYTHONPATH=src <locked-python> -m pytest tests/deployment/test_stock_build_inputs.py -q`; expected missing-module failures before source exists.
- [ ] Implement exact spec bounds with no extraction, no implicit decompression and existing strict JSON primitives where compatible.
- [ ] Run the same group with branch coverage at least95%; expected all pass. Validate an actual clean Git archive locally without Docker/provider use.
- [ ] Commit the owned module/tests, then task-done the whole group.

## Task 2: Exclusive producer state and fixed owned build

**Files:** Create `infra/hybrid/stock_release_producer.py` and `infra/hybrid/stock_build_engine.py`; tests `test_stock_release_producer.py`, `test_stock_build_engine.py`.

**Interfaces:** Consume Task1 data, existing root socket/peer and image validators. Public `initialize_producer() -> None`, later `produce_release(source_sha256: str) -> Path`; private locked producer context owns original clock/window, exclusive files, build dispatch and final publication. Fixed build transport accepts only that actual context, not route/body/image overrides.

- [ ] Write REDs for explicit initialization/opening, lock contention, fixed paths/ownership, unfinished/existing attempts, original source/intent/request durability before exactly one POST.
- [ ] Write real-socketpair cases for actual version/body upload/quiet result/exact image inspection, idle reads without cap renewal, partial send/EOF/error/timeout/shutdown and zero request replay.
- [ ] Implement private filesystem/context state and fixed HTTP build with retained originals and post-operation checks; no generic retry/repair/cancel/image deletion.
- [ ] Verify narrow state/transport groups at least95% combined coverage, existing probe/worker groups and strict static checks.
- [ ] Commit/task-done; this intermediate library must not claim a usable release or native proof.

## Task 3: Source preparation, fresh probe, rendering and durable release

**Files:** Complete producer module, add `infra/hybrid/stock_source_prepare.py`, integration tests and `docs/stock-release-producer-operations.md`.

Private supporting modules `stock_process.py`, `stock_compose_render.py` and
`stock_release_publication.py` share the existing producer lease and validators;
they do not create separate configuration, runtime authority or public CLI overrides.

**Interfaces:** `prepare_source(output: Path) -> str` owns bounded clean Git archive; public `produce_release(source_sha256: str) -> Path` owns all operations and returns only after final gate. CLI accepts only source SHA. Private fixture seams replace native filesystem/socket/process/clock boundaries, not the verifier/store/controller decisions.

- [ ] Write REDs for bounded clean source preparation/no replacement, owned actual controller success/failure/recovery, renderer version/env/bounds and exact four-file loader acceptance.
- [ ] Add composed failures at native and durable boundaries, substituted archive/namespace, failed/late contexts, poisoned env, duplicate calls, complete lost acknowledgements and final CLI formatting delays.
- [ ] Implement one producer-owned fixed probe, exact reviewed render, canonical derivation, exclusive fsync/readback/loader/terminal publication. Leave timers/control/credentials untouched.
- [ ] Run new groups and deployment/architecture/worker/release regression; expected pass with existing optional skips reported separately. Run Ruff, strict mypy including host modules, expanded Bandit, lock/diff checks.
- [ ] Commit/task-done; obtain one fresh whole-branch review against the spec and exhaustive root rulings.
- [ ] Fix Critical/Important once with observed RED/GREEN; defer minors. Queue this source's actual full only after earlier55324 terminates; never duplicate/restart it or infer this source's result from it.

## Remaining external gates

Actual native producer/probe/image/isolation/lifecycle proof, paused installation,
OAuth ownership/natural-expiry/revocation, backup/restore, scheduled24/7research,
qualified stock data/strategies and nonempty broker reconciliation are separate.
No mandatory60-day paper wait and no automatic live activation are introduced.
