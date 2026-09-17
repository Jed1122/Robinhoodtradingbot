# Alpaca First-Response Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository ownership overrides generic delegation: the primary owns all credential, capture, and source-evidence code and decisions.

**Goal:** Build and test a separate, one-shot diagnostic that can collect at most two authorized market-data response samples into private quarantine, without integrating a provider or accepting research data.

**Architecture:** First prepare an offline, hash-bound request manifest from the existing canonical configuration. Separately implement private I/O and a tightly bounded transport; enable its one-shot execution only after the operator approves the exact reviewed acquisition scope and unresolved rights are resolved. The diagnostic never calls the synthetic bundle assembler, trading runtime, or production ledger.

**Tech Stack:** Python `>=3.12,<3.15`; existing `httpx==0.28.1`, standard-library dataclasses/JSON/Decimal/SHA-256/POSIX APIs, and the existing Pytest/Ruff/mypy/Bandit tools. No new dependencies.

**Spec:** [Approved Alpaca free-data validation specification](../specs/2026-09-17-alpaca-free-data-validation-design.md).

## Global Constraints

- The budget is $0 for data subscriptions.
- Robinhood remains the intended broker. Its credentials, allowlists, runtime, production ledger, deployment, strategy selection, risk settings, and promotion gates stay unchanged.
- Do not treat HTTP 200 as legal clearance.
- No automatic retry, feed switch, upgrade, or scheduler is part of the first capture.
- Raw responses remain off Git, Cloud, and reports.
- Do not pass captured Alpaca data to the synthetic bundle assembler/store, relabel real data as synthetic, or broaden its allowlist.
- All times use the existing canonical UTC validation; collection time is not historical publication time.
- Account setup is complete by operator report, not by authenticated inspection. No account identifier or key belongs in this document.
- Implementation approval and acquisition approval are separate. Completing Tasks 1-3 offline does not authorize Task 4.

---

## State, scope, and dependency chain

Planning base: `62cc33b2520124ead55aa8effe8aa24ea24cdedc`, integration branch
`codex/continue-implementation-from-commit-7c4dcd1`.

Worktree: `/Users/jedweinstein/Documents/robinhood-multi-asset-trading-system/worktrees/robinhood-system-implementation`.
Preserve the unrelated untracked `.coverage 2`, `.coverage 3`, `.coverage 4`, and `error.log`.
Check actual branch/base/status before execution; the desktop Polymarket cwd is not this project.

Classification: diagnostic **not implemented**; account **operator-confirmed**; feed entitlement,
retention rights, authenticated response shapes, and usable history **unverified**.
Written-spec approval and paper-only Basic/free confirmation were received on 2026-09-17.

Critical path: offline implementation and tests (Tasks 1-3) -> resolve feed/use prerequisites
and approve an exact manifest -> primary-only capture (Task 4) -> inspect actual shapes ->
separately design complete acquisition and an offline importer. Source acceptance and the
existing paper/shadow/live gates follow that later work, not this diagnostic.

This plan intentionally implements only the first-response prerequisite of the larger spec.
It requests the full configured symbol/window scope but only the first page, capped at one
record, from each endpoint. It does not silently reduce the 3,650-day research requirement
or 750-bars-per-symbol threshold. Every captured result remains insufficient for research.
No pagination or provider-specific value mapper is implemented before authenticated shape
review. There is no claim that two successful responses complete source validation.

## Files and ownership

All paths are relative to the worktree. Unlisted source/config/deployment paths are read-only.

| Path | Responsibility and owner |
| --- | --- |
| `src/trading_bot/diagnostics/__init__.py` | Primary: package marker only, no imports or startup effects. |
| `src/trading_bot/diagnostics/alpaca_probe.py` | Primary: immutable manifest/receipt, offline preparation, fixed one-shot transport. No provider bar/action mapping. |
| `src/trading_bot/diagnostics/alpaca_probe_io.py` | Primary: private credential read and quarantine publication, no networking. |
| `scripts/probe_alpaca_data.py` | Primary: prepare/capture entry point; prepare is the default and never reads credentials. |
| `tests/unit/diagnostics/test_alpaca_probe.py` | Primary: manifest identity, request bounds, synthetic mocked transport tests. |
| `tests/integration/diagnostics/test_alpaca_probe_io.py` | Primary: synthetic credentials/responses in private temporary directories. |
| `tests/smoke/test_alpaca_probe_command.py` | Primary: help, offline preparation, fail-closed flags, sanitized output. |
| `docs/alpaca-data-diagnostic.md` | Primary: implemented command help, scope approval procedure, limits, remaining source checks. |
| `PARALLEL_ORCHESTRATION_TRANSITION_REPORT.md` | Primary: truthful checkpoint and verification record. |

Read-only dependencies: `config/loader.py`, `clock.py`, `market_data/bundle_store.py`,
`market_data/bundle_models.py`, `configs/{base,backtest,safety-envelope}.yaml`, the approved
specification, and repository authority documents. Do not change existing storage contracts.
Reuse compatible descriptor-relative private-file primitives from `bundle_store.py` internally;
translate their `BundleError` into diagnostic reason codes without exposing exception values.
Do not use `write_bundle`, `read_bundle`, `verify_bundle`, or synthetic descriptors for real data.

## Frozen diagnostic interfaces

The following are planned interfaces, not existing code. Import `Clock`, `require_utc`, and
`LoadedConfig` from their existing modules. Do not add a second application config model.

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from trading_bot.clock import Clock
from trading_bot.config.loader import LoadedConfig

@dataclass(frozen=True, slots=True)
class ProbeRequest:
    path: Literal["/v2/stocks/bars", "/v1/corporate-actions"]
    query: tuple[tuple[str, str], ...]

@dataclass(frozen=True, slots=True)
class ProbeManifest:
    code_revision: str
    config_hash: str
    prepared_at: datetime
    expires_at: datetime
    requests: tuple[ProbeRequest, ...]
    credential_file: Path
    quarantine_root: Path
    repository_root: Path
    max_response_bytes: int
    total_timeout_seconds: int

@dataclass(frozen=True, slots=True)
class ProbeReceipt:
    manifest_sha256: str
    request_index: int
    started_at: datetime
    completed_at: datetime
    status_code: int | None
    body_sha256: str | None
    body_bytes: int
    reason_code: str

@dataclass(frozen=True, slots=True)
class ProbeCredential:
    key_id: str = field(repr=False)
    secret_key: str = field(repr=False)

class ProbeError(ValueError):
    # Only an enumerated safe code is permitted; no provider/error/body input.
    code: str

def prepare_probe(
    loaded: LoadedConfig, *, clock: Clock, code_revision: str,
    requested_end: datetime, credential_file: Path, quarantine_root: Path,
    repository_root: Path,
) -> ProbeManifest: ...

def encode_manifest(manifest: ProbeManifest) -> bytes: ...
def decode_manifest(body: bytes) -> ProbeManifest: ...
def manifest_sha256(manifest: ProbeManifest) -> str: ...

async def capture_probe(
    manifest: ProbeManifest, *, approved_manifest_sha256: str,
    loaded: LoadedConfig, active_code_revision: str, clock: Clock,
) -> tuple[ProbeReceipt, ...]: ...

# Defined in alpaca_probe_io.py; credentials never appear in return receipts.
def read_probe_credential(path: Path, *, repository_root: Path) -> ProbeCredential: ...
def publish_probe_blob(root: Path, body: bytes, *, repository_root: Path) -> str: ...
def publish_probe_receipt(root: Path, receipt: ProbeReceipt, *, repository_root: Path) -> str: ...
```

`ProbeError` accepts only these literal safe codes: `probe_manifest_invalid`,
`probe_scope_mismatch`, `probe_expired`, `probe_path_invalid`, `probe_credential_invalid`,
`probe_storage_failed`, `probe_access_denied`, `probe_rate_limited`, `probe_http_failed`,
`probe_timeout`, `probe_response_invalid`, `probe_response_too_large`, `probe_secret_echo`.
Never attach a raw exception as the public cause or serialize `__dict__` from an exception.
Successful receipt reason is the literal `probe_sample_retained`; failure receipts use only
the enumerated error codes. Missing HTTP status is `None`, never a fabricated status. Load
`alpaca_probe_io` inside `capture_probe`, not at module import time, to avoid a type/import cycle.

Encode one versioned JSON object (`schema_version="alpaca-first-response-v1"`) with exact
dataclass fields. Use sorted keys, compact separators, UTF-8, `allow_nan=False`, canonical
UTC strings, path strings, and ordered request arrays. Hash exactly those bytes with SHA-256.
Decode strict exact fields/types, reject duplicate keys/nonfinite values, bound input to
16,384 bytes and reject any manifest that differs from the fixed scope below. No supplied
extra field can enable a host, request method, retry, feed fallback, or order operation.
Private manifest paths are not included in the shareable report.

### Exact first-response request and resource bounds

| Item | Fixed rule |
| --- | --- |
| Host/method | HTTPS `data.alpaca.markets`, port 443, GET only; no user-supplied base URL. |
| Requests | Exactly two planned paths above, bars first; at most one send per path. Stop the entire run on any failure. |
| Symbols/window | Read `loaded.config.equity_strategies.research_universe_symbols` and `loaded.config.research.history_calendar_days`; start is requested end minus that many calendar days. Preserve all symbols and their order. |
| Interval/history | Require `BarInterval.ONE_DAY`; retain the configured `minimum_history_bars` in the assessment, not a new acceptance rule. |
| End/cutoff | Explicit UTC requested end, at least 24 hours before preparation; expires 30 minutes after preparation. Reject non-UTC, future, reversed, or expired scope. This buffer is a diagnostic request bound, not a session-finality assertion. |
| Bars query | `symbols`, `timeframe=1Day`, UTC `start`/`end`, `adjustment=raw`, `asof=-`, `feed=sip`, `currency=USD`, `sort=asc`, `limit=1`. |
| Actions query | Same `symbols`, UTC-date `start`/`end`, `region=us`, `data_quality=all`, `sort=asc`, `limit=1`; omit `types` to request all documented types. Dates use the provider's process-date filtering, not an asserted ex-date coverage interval. |
| Feed prerequisite | SIP is proposed, not authorized by the account confirmation. If contractual access cannot be established, block. IEX needs a separately reviewed manifest, not automatic substitution. |
| Paging | Do not send a `page_token`, inspect or follow a returned token, or repeat a request. Mark history and action coverage `not_checked`. |
| Bytes | 1,048,576 raw body bytes per successful response; at most two bodies, hence at most 2,097,152 bytes total. Count streaming bytes, not just Content-Length. |
| Time | 60 seconds total via `asyncio.timeout(60)`, including both requests/body reads; 10 seconds per HTTP I/O operation. Recheck clock expiry before each send and before publishing. |
| HTTP | TLS verification on; redirects off; `trust_env=False`; transport retries zero; `Accept-Encoding: identity`; reject non-identity encoding. Disable HTTP client debug logging. |
| Errors | No error-body/response-header retention. Record only bounded status integer and enumerated reason code. No retries for 401/403/429/5xx. |
| Retention | Successful JSON-object bytes only, private quarantine outside every repository/Cloud/production-evidence location explicitly reviewed in Task 4. No overwrites/symlinks. |

The parameter choices were checked against official [historical bars](https://docs.alpaca.markets/us/reference/stockbars)
and [corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1) references
on 2026-09-17. They are request definitions, not verified response semantics or permission.

## Task 1: Offline manifest and fixed scope

**Files:** Create package marker, `alpaca_probe.py`, and `tests/unit/diagnostics/test_alpaca_probe.py`.

**Interfaces:** Consume existing `load_config(base_path, mode_path, safety_path, environ) -> LoadedConfig`
and `Clock.now() -> datetime`. Produce the immutable manifest types and four preparation/codec
functions above. No credential file is opened; no network client is constructed.

- [ ] **Step 1: Write the failing deterministic preparation test.** Use this complete setup:

```python
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json

from trading_bot.config import load_config
from trading_bot.diagnostics.alpaca_probe import encode_manifest, prepare_probe

ROOT = Path(__file__).parents[3]

@dataclass(frozen=True)
class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 17, 12, tzinfo=UTC)

def test_prepare_is_offline_and_preserves_research_scope(tmp_path: Path) -> None:
    loaded = load_config(ROOT / "configs/base.yaml", ROOT / "configs/backtest.yaml",
                         ROOT / "configs/safety-envelope.yaml", environ={})
    end = datetime(2026, 9, 15, tzinfo=UTC)
    manifest = prepare_probe(loaded, clock=FixedClock(), code_revision="a" * 40,
        requested_end=end, credential_file=tmp_path / "absent" / "credentials.json",
        quarantine_root=tmp_path / "absent" / "quarantine", repository_root=ROOT)
    query = dict(manifest.requests[0].query)
    assert query["symbols"] == ",".join(loaded.config.equity_strategies.research_universe_symbols)
    assert datetime.fromisoformat(query["start"]) == end - timedelta(
        days=loaded.config.research.history_calendar_days)
    assert query["limit"] == "1"
    assert query["feed"] == "sip"
    assert len(manifest.requests) == 2
    assert not (tmp_path / "absent").exists()
    assert json.loads(encode_manifest(manifest))["schema_version"] == "alpaca-first-response-v1"
```

- [ ] **Step 2: Run the test and confirm the new-module import fails.**
  Run `uv run pytest tests/unit/diagnostics/test_alpaca_probe.py -q`.
- [ ] **Step 3: Implement immutable values, exact scope validation, canonical encoding and decoding.**
  Calculate `requested_start = requested_end - timedelta(days=loaded.config.research.history_calendar_days)`;
  construct only the two query tuples in the bounds table. Serialize via
  `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()`.
  Validate the full lowercase 40-character commit and 64-character config digest, strict integers
  (not booleans), UTC times and lexical absolute paths without `..`; do not stat secret paths here.
  Reconstruct and compare the canonical requests against loaded config at capture time as well.
- [ ] **Step 4: Add and run parameterized negative tests.** Mutate each encoded field independently:
  unknown schema/key, duplicate JSON key, method/base-URL injection, extra/duplicate path,
  `limit=2`, `feed=iex`, `adjustment=all`, page token, non-UTC time, expiry beyond 30 minutes,
  limit boolean, negative/oversized bounds, invalid digest, relative path and `..` component.
  Each raises `ProbeError("probe_manifest_invalid")`; a scope mismatch against loaded config
  raises `probe_scope_mismatch`. Repeat encode/decode and assert identical bytes and digest.
- [ ] **Step 5: Run narrow tests, Ruff and mypy; commit only these paths.**
  Commit message: `feat: prepare bounded offline Alpaca diagnostic manifest`.

## Task 2: Private credential and quarantine I/O

**Files:** Create `alpaca_probe_io.py` and `tests/integration/diagnostics/test_alpaca_probe_io.py`.

**Interfaces:** Consume `ProbeCredential`/`ProbeError`, and existing `_open_root`, `_read`,
`_publish` private storage helpers. Produce `read_probe_credential`, `publish_probe_blob`,
and `publish_probe_receipt`.
The root is explicitly operator-selected, pre-existing, owner-only, and never auto-discovered.

- [ ] **Step 1: Write the failing synthetic byte-storage test.**

```python
import hashlib
from pathlib import Path
from trading_bot.diagnostics.alpaca_probe_io import publish_probe_blob

def test_blob_is_exact_private_and_content_addressed(tmp_path: Path) -> None:
    repo, root = tmp_path / "repo", tmp_path / "quarantine"
    repo.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    body = b'{"synthetic":true}\n'
    digest = publish_probe_blob(root, body, repository_root=repo)
    assert digest == hashlib.sha256(body).hexdigest()
    target = root / (digest + ".raw")
    assert target.read_bytes() == body
    assert target.stat().st_mode & 0o777 == 0o600
    assert publish_probe_blob(root, body, repository_root=repo) == digest
```

- [ ] **Step 2: Run `uv run pytest tests/integration/diagnostics/test_alpaca_probe_io.py -q`; confirm import failure.**
- [ ] **Step 3: Implement the thin I/O wrappers, without a second storage framework.**
  For blobs, reject more than 1,048,576 bytes, compute `hashlib.sha256(body).hexdigest()`,
  open the existing private root with `_open_root`, publish `digest + ".raw"` using `_publish`,
  close descriptors in `finally`, and translate `BundleError`/`OSError` into safe codes.
  Read credentials only from the explicit no-symlink parent using `_open_root` and `_read`
  with a 4,096-byte bound. Require a 0600 owner-owned regular file and exactly two nonempty
  printable ASCII JSON strings, `key_id` and `secret_key`, each 16-256 characters. Reject
  duplicates, CR/LF, whitespace, NUL, unknown keys and non-string values. This is a local
  credential-file contract, not a statement about provider-issued key formats.
  For receipts, validate all fields, encode exact fields with the same canonical JSON rules
  as Task 1, hash the encoded bytes, and publish `digest + ".receipt.json"` through `_publish`.
  Hashes/reason codes/times/statuses/counts are the only receipt contents; no response fields,
  request headers, credential file paths or arbitrary strings are admitted. A blob followed
  by a failed receipt write is incomplete evidence, not a successful capture.
- [ ] **Step 4: Parameterize private-filesystem failures and safe-error assertions.** Cover root/file
  symlink, intermediate symlink, repository-contained root/file, traversal, 0644 credential,
  0755 root, FIFO, oversized body/credential, conflicting digest filename, partial writes and
  failed publication. Confirm all public errors/reprs omit synthetic key/secret/body strings.
  Preserve existing complete artifacts on uncertainty; never recursively delete a root.
- [ ] **Step 5: Run both new modules' tests plus `tests/integration/market_data/test_bundle_store.py`,
  Ruff and mypy.** Commit message: `feat: isolate Alpaca diagnostic private capture files`.

## Task 3: One-shot mocked transport, entry point, and honest report

**Files:** Modify `alpaca_probe.py` and its unit tests. Create `scripts/probe_alpaca_data.py`,
`tests/smoke/test_alpaca_probe_command.py`, and `docs/alpaca-data-diagnostic.md`; update the handoff.

**Interfaces:** Consume Tasks 1-2. Implement `capture_probe` exactly as frozen, plus
`main(argv: Sequence[str] | None = None) -> int` in the script. No production CLI registration.

- [ ] **Step 1: Write the fail-before-credentials test.** Construct the Task-1 manifest using the
  same fixed-clock fixture and absent credential path; run
  `asyncio.run(capture_probe(manifest, approved_manifest_sha256="0" * 64, loaded=loaded,
  active_code_revision="a" * 40, clock=FixedClock()))` inside
  `pytest.raises(ProbeError, match="probe_scope_mismatch")`. Mock the credential-read and
  `httpx.AsyncClient` constructors to raise `AssertionError` if reached.
- [ ] **Step 2: Run the targeted test and confirm capture is absent.**
- [ ] **Step 3: Implement capture with fail-closed ordering.** Validate manifest/config/revision/hash,
  expiry, and private destinations before any credential read. The approval digest is an
  operator confirmation mechanism, not an unforgeable security capability. Use an explicit
  `httpx.AsyncHTTPTransport(retries=0)` and `httpx.AsyncClient(verify=True, trust_env=False,
  follow_redirects=False, timeout=10.0, transport=transport)` inside `asyncio.timeout(60)`.
  Send only the fixed host/path/query via `client.stream("GET", url, params=query, headers=headers)`;
  the two authentication headers exist only in that local request. Never print request objects.
  Consume `response.aiter_raw()` with an incremental 1 MiB limit. Reject non-200/non-JSON/
  encoded responses before retaining a body. Require strict JSON-object syntax with duplicate
  key/nonfinite rejection and Decimal parsing; do not interpret provider fields. Reject any
  raw or decoded string containing either credential or authentication header name before
  publishing. Only then write the exact original bytes and a safe receipt. Reject clock
  regression (`completed_at < started_at`) before publishing. Stop on the first
  error; do not send the second request after a first-request failure. A partially completed
  run may retain its first successful private body, but never claims full success or coverage.
  Persist a safe failure receipt if the validated destination is still usable; then raise
  the safe `ProbeError`. If even that write fails, report only `probe_storage_failed`. Never
  let cleanup or receipt failure expose raw network exceptions.
- [ ] **Step 4: Exercise the transport with synthetic mocked responses only.** With `respx`, bind the
  exact host/path and assert GET, expected query, no redirect follow, and call counts. Test
  two 200 JSON objects; then parameterize 301, 400, 401, 403, 429 and 500 for the first call
  and assert exactly one send. Test first success/second failure, timeout, expired clock,
  malformed/non-object/duplicate-key/nonfinite JSON, compressed body, overflowing streamed
  bytes, credential echo (including JSON escapes), and arbitrary `next_page_token` text.
  Assert there is never a third send, retry, token follow, fallback or provider error-body log.
- [ ] **Step 5: Implement and test the offline-default command surface.** Freeze these flags:
  `--prepare` (default), `--capture` (mutually exclusive), `--manifest-file`,
  `--approved-manifest-sha256`, `--credential-file`, `--quarantine-root`, `--requested-end`.
  Both modes determine the full current Git revision locally and load the three canonical
  backtest files with `environ={}`. Refuse capture from a dirty tracked checkout, mismatched
  manifest/revision/config or missing exact approval digest. Preparation never opens keys or
  contacts HTTP; capture-only flags cannot turn preparation into capture. Prepared manifests
  are private 0600 no-overwrite files, not stdout. Command stdout contains only a safe JSON
  summary (manifest hash, disposition, safe reason codes, UTC time); never paths/keys/raw data.
  Use subprocess argument lists with `shell=False` and a five-second timeout for local Git
  identity checks; no remote command or environment expansion. Publish the private manifest
  with existing `_open_root`/`_publish` primitives; it is not an application bundle. After
  Task-1 lexical preparation, resolve and validate its explicit private destination before
  writing. Recheck the concrete credential/quarantine parents immediately before capture.
  Exit 0 means the diagnostic command completed, not source acceptance; invalid invocation or
  failed capture exits 2. In either mode no result is `READY_FOR_IMPORTER_DESIGN_REVIEW`.
- [ ] **Step 6: Implement the assessment as a diagnostic document, not a promotion type.** It must
  include every row from spec section 5. Successful sample HTTP access is `observed_pass` only
  for technical access and retained-byte integrity. Account/free plan remains operator-reported;
  contractual entitlement and rights cite the separately reviewed basis. Identity, numeric
  semantics, full history, slots, interpolation, session timing, vintages, actions and historical
  universe remain `not_checked` or `unresolved`; successful samples overall mean
  `INSUFFICIENT_SOURCE_EVIDENCE`. Do not print an arbitrary provider string as a status/code.
- [ ] **Step 7: Document exactly the implemented flags and the operator gate below.** Assert script
  `--help` exposes no host, arbitrary URL, order, retry, paid-upgrade or live switch. Run all new
  tests, existing data-bundle tests and documentation smoke checks, then the full baseline:

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests --cov=trading_bot --cov-branch --cov-fail-under=80
uv run bandit -c pyproject.toml -r src
uv lock --check
git diff --check
```

  On this workstation use `PYTHONPATH=src` with the verified executable directory
  `/private/tmp/robinhood-oauth-runtime.tahOFY/.venv/bin/` if the repository `.venv` remains stale;
  check interpreter/dependency availability first. Do not claim CI passed from local results.
  Commit message: `feat: add separately authorized Alpaca first-response diagnostic`.

## Task 4: Separately authorized operator capture and source-shape review

This is an external execution gate, not permission contained in this plan and not an automatic
continuation of Tasks 1-3. Do not install keys, read private account pages, or send requests now.

- [ ] **Step 1: Resolve the actual paper-only feed entitlement and private retention/use.** Use
  public/account-specific terms supplied by the operator or a separately authorized provider
  communication. Record the source/date and conclusion without identifiers or secrets. An
  unresolved conflict blocks capture; the account confirmation is not the missing proof.
- [ ] **Step 2: Review exact implementation commit and local results.** No dirty tracked code,
  unreviewed helper, Cloud execution, or runtime deployment may substitute for this check.
- [ ] **Step 3: Agree the private credential/manifest/quarantine locations and retention scope.**
  The operator installs the paper credential through a separately reviewed private process;
  do not request its values in chat. It remains a credential with its actual account authority,
  not a guaranteed read-only key. Inspect only the explicitly approved paths. No search for keys.
- [ ] **Step 4: Prepare and show the non-secret acquisition scope.** Bind actual code revision,
  config hash, requested UTC end/start, expiry, all fixed query fields, 2-request/1-MiB/60-second
  bounds, and the private manifest digest. Obtain explicit authority for that single digest,
  credential read, two GET requests, and authorized private retention. Expiry requires a fresh
  manifest and fresh approval, not silent regeneration or an automatically repeated request.
- [ ] **Step 5: Run once and record only safe results.** No retries, follow-up pages, provider
  contact, paid plan, account write, deployment, paper/live execution or ledger operation.
- [ ] **Step 6: Primary-only private response review.** Inspect value-free structural summaries
  locally; keep genuine values private. A 401/403/429 or unknown shape yields a truthful blocked
  or insufficient assessment. Do not replace the paper credential with a live credential.
  Plan complete-history pagination, exact numeric mappings, sessions/DST/coverage, vintages,
  corporate actions and historical universe only after this evidence is understood. Those
  follow-on contracts require their own bounded design; this probe cannot satisfy them.

## Parallel work and handoff

All production code and tests involving credential/capture decisions remain primary-owned.
No actual Cloud task is dispatched by this plan or its approval. After callable interfaces
exist, a separate exact-commit contract may delegate only synthetic codec/CLI tests or docs;
never real response values, secrets, source acceptance, transport policy or runtime changes.
Local read-only documentation-test inventory is supporting work, not Cloud execution.

## Primary self-review and completion boundary

- Spec sections 1-3: account/spec facts recorded; cost, authority and endpoint boundaries mapped
  to global constraints, Tasks 1-3 and the explicit Task-4 gate.
- Spec section 4: original-byte quarantine and UTC/config/request identity covered here; full
  history, provider mappings, session/availability, adjustments and universe explicitly remain
  outside this first-response milestone. No complete acquisition or importer is implied.
- Spec section 5: relevant bounded transport/storage tests mapped to Tasks 1-3. Pagination
  cycles, per-symbol gaps/duplicates, DST and action coverage tests belong to the follow-on
  full-capture/validation plan, not fabricated acceptance of these samples.
- Spec section 6: exact primary ownership and separate external approval retained.
- Plan execution is complete only for the checked tasks. Offline code completion must not
  be reported as completed external acquisition, full spec completion, or live readiness.
