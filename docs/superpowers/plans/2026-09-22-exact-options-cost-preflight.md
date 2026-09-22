# Exact Options Cost Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Preserve the existing inline execution method; the coordinator owns the credential/HTTP boundary.

**Goal:** Estimate an explicitly supplied list of SPY option symbols without acquiring data or changing any trading authorization.

**Architecture:** Extend the existing immutable `CostRequest` and standalone diagnostic CLI with an explicit raw-symbol mode. Keep the fixed free metadata endpoint, private credential loader, Decimal response parser and fail-closed flags unchanged. This feature is a cost-query primitive, not a contract selector, acquisition client or research validation result.

**Tech Stack:** Existing Python 3.12+, dataclasses, Decimal, argparse, HTTPX and pytest; no dependency changes.

**Spec:** [Lower-cost options data scope](../../options-data-budget-scope.md), specifically “Exact-symbol estimator specification.” The master [options-only specification](../../options-only-build-spec.md) continues to govern trading and evidence policy.

## Global Constraints

- No dependencies, runtime configuration, risk limits or production capabilities change.
- Raw mode supports only `cbbo-1m`.
- Dataset and endpoint stay fixed.
- Default CLI behavior remains a credential-free, network-free preview.
- Validation errors stay sanitized and do not echo arbitrary command arguments.
- No raw licensed data, credentials or authenticated tests enter Git or CI.
- Preserve all existing staged/uncommitted changes, including `uv.lock` and the tracked SBOM.
- Baseline: `c623ab2e63845b955a0a9c51ffb6f80a8192dcbe`; use the existing implementation worktree.
- Operator review approved on 2026-09-22; no data purchase is included.

## Review Focus

- A caller mixes a root with a raw contract: deny instead of silently expanding to a chain (Task 1).
- A symbol contains Unicode digits, newline or comma: deny before credential loading/network (Tasks 1–2).
- A well-shaped symbol encodes an impossible date or zero strike: deny; syntactic success still does not certify tradability (Task 1).
- A raw list contains duplicates or exceeds 100 symbols: deny rather than truncate (Task 1).
- CLI opt-in is absent or a provider redirects: no credential/network in preview and no redirect/retry in either mode (Tasks 1–2).

---

## File ownership

Only these implementation files are owned by this plan:

- `src/trading_bot/diagnostics/databento_preflight.py`: request validation and query serialization.
- `src/trading_bot/cli/databento_preflight.py`: explicit mode argument and constructor wiring.
- `tests/unit/diagnostics/test_databento_preflight.py`: request and fixed-endpoint contract tests.
- `tests/integration/cli/test_databento_preflight.py`: credential-free previews and sanitized denials.
- `docs/databento-preflight.md`: the supported query modes and their limitations.

Do not change the general trading CLI, native staging, strategy, ledger, broker,
runtime, canonical risk configuration, dependency lock or SBOM. No network use is
needed to implement or verify this feature. Synthetic test strings are not market data.

### Task 1: Add bounded raw-symbol requests without changing parent mode

**Files:** Modify `src/trading_bot/diagnostics/databento_preflight.py`; test
`tests/unit/diagnostics/test_databento_preflight.py`.

**Interfaces:**

- Consumes existing `CostRequest(symbols, schema, start, end)` and
  `estimate_cost(request, credential, *, clock, allow_metadata_network=False)`.
- Produces `CostRequest(symbols, schema, start, end, stype_in="parent")`, with
  `stype_in: Literal["parent", "raw_symbol"]`. The existing `query()` return type
  stays `dict[str, str]`; the network function's signature does not change.

- [x] Add these failing tests using the existing `request_scope`, `replace`,
  `wire_transport`, `KEY`, and `Clock` fixtures/helpers:

```python
def test_raw_symbol_is_preserved_and_parent_default_is_unchanged(request_scope):
    symbol = "SPY   250117C00500000"
    raw = replace(request_scope, symbols=(symbol,), stype_in="raw_symbol")
    assert raw.query() == {**request_scope.query(), "symbols": symbol, "stype_in": "raw_symbol"}
    assert request_scope.query()["symbols"] == "SPY.OPT"
    assert request_scope.query()["stype_in"] == "parent"


@pytest.mark.parametrize("symbol", [
    "SPY", "SPY.OPT", "ALL_SYMBOLS", "SPY   250117C00500000,SPY",
    "SPY   250117C00500000\n", "SPY   250230C00500000",
    "SPY   250117C00000000", "SPY   ２５０１１７C00500000",
    "SPY\u00a0  250117C00500000", "QQQ   250117C00500000",
    "SPY1  250117C00500000", "SPY   250117c00500000", None,
])
def test_invalid_raw_symbols_are_denied(request_scope, symbol):
    with pytest.raises(DatabentoPreflightError, match="^scope_invalid$"):
        replace(request_scope, symbols=(symbol,), stype_in="raw_symbol")


def test_raw_list_boundaries_and_other_modes_are_denied(request_scope):
    symbols = tuple(f"SPY   250117C{strike:08d}" for strike in range(1, 102))
    assert len(replace(request_scope, symbols=symbols[:100], stype_in="raw_symbol").symbols) == 100
    for values in ((), symbols, (symbols[0], symbols[0]), (symbols[0], "SPY")):
        with pytest.raises(DatabentoPreflightError, match="^scope_invalid$"):
            replace(request_scope, symbols=values, stype_in="raw_symbol")
    raw = replace(request_scope, symbols=symbols[:1], stype_in="raw_symbol")
    for change in ({"schema": "definition"}, {"stype_in": "instrument_id"}, {"stype_in": None}):
        with pytest.raises(DatabentoPreflightError, match="^scope_invalid$"):
            replace(raw, **change)


def test_calendar_validation_accepts_leap_day_and_keeps_parent_limit(request_scope):
    raw = replace(request_scope, symbols=("SPY   240229C00500000",), stype_in="raw_symbol")
    assert raw.query()["symbols"] == "SPY   240229C00500000"
    with pytest.raises(DatabentoPreflightError, match="^scope_invalid$"):
        replace(request_scope, symbols=("SPY", "QQQ", "IWM", "DIA", "XLF"))


@pytest.mark.parametrize("status", [200, 302])
async def test_raw_mode_keeps_fixed_cost_endpoint_and_no_redirect(monkeypatch, request_scope, status):
    symbol = "SPY   250117P00500000"
    scope = replace(request_scope, symbols=(symbol,), stype_in="raw_symbol")
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        assert str(request.url.copy_with(query=None)) == "https://hist.databento.com/v0/metadata.get_cost"
        assert dict(request.url.params) == scope.query()
        return httpx.Response(status, content=b"0.125", headers={
            "content-type": "application/json", "location": "https://example.invalid/denied",
        })

    wire_transport(monkeypatch, respond)
    if status == 200:
        result = await estimate_cost(scope, DatabentoCredential(KEY), clock=Clock(), allow_metadata_network=True)
        assert result.cost_usd == Decimal("0.125")
        assert result.download_authorized is False
        assert result.economic_evidence is False
    else:
        with pytest.raises(DatabentoPreflightError, match="^http_failed$"):
            await estimate_cost(scope, DatabentoCredential(KEY), clock=Clock(), allow_metadata_network=True)
    assert len(calls) == 1
```

- [x] Run `PYTHONPATH=src python -m pytest -q tests/unit/diagnostics/test_databento_preflight.py`.
  Confirm new cases fail because `stype_in` is unsupported, not due to unrelated imports.
- [x] Add `stype_in: Literal["parent", "raw_symbol"] = "parent"` as the final
  `CostRequest` dataclass field and add a module-private raw validator:

```python
def _valid_raw_option_symbol(symbol: object) -> bool:
    if type(symbol) is not str:
        return False
    matched = re.fullmatch(r"SPY   ([0-9]{2})([0-9]{2})([0-9]{2})[CP]([0-9]{8})", symbol)
    if matched is None:
        return False
    year, month, day, strike = (int(value) for value in matched.groups())
    try:
        date(2000 + year, month, day)
    except ValueError:
        return False
    return strike > 0
```

Replace `CostRequest.__post_init__` with common validation first, mode-specific
validation second, and duplicate detection only after element types are validated:

```python
def __post_init__(self) -> None:
    if (
        type(self.symbols) is not tuple
        or type(self.stype_in) is not str
        or self.stype_in not in ("parent", "raw_symbol")
        or type(self.schema) is not str
        or self.schema not in ("definition", "cbbo-1m")
        or type(self.start) is not date
        or type(self.end) is not date
        or self.end <= self.start
    ):
        raise DatabentoPreflightError("scope_invalid")
    if self.stype_in == "parent":
        valid = 1 <= len(self.symbols) <= 4 and all(
            type(s) is str and re.fullmatch(r"[A-Z]{1,6}", s) is not None
            for s in self.symbols
        )
    else:
        valid = self.schema == "cbbo-1m" and 1 <= len(self.symbols) <= 100 and all(
            _valid_raw_option_symbol(s) for s in self.symbols
        )
    if not valid or len(set(self.symbols)) != len(self.symbols):
        raise DatabentoPreflightError("scope_invalid")
```

In `query()`, replace only the `symbols` and `stype_in` entries:

```python
"symbols": ",".join(
    symbol + ".OPT" if self.stype_in == "parent" else symbol
    for symbol in self.symbols
),
"stype_in": self.stype_in,
```

- [x] Run the full diagnostic unit module again; require all old and new tests pass.
- [x] Run `ruff check` and `mypy` on the changed diagnostic module. Format the new
  tests without altering assertions. Review the diff for endpoint or credential changes.
- [x] Commit only this task's two owned files, leaving unrelated staged work alone:
  `git commit --only -m "feat: add bounded raw option cost requests" -- src/trading_bot/diagnostics/databento_preflight.py tests/unit/diagnostics/test_databento_preflight.py`.

### Task 2: Expose explicit CLI mode and document its limits

**Files:** Modify `src/trading_bot/cli/databento_preflight.py`,
`tests/integration/cli/test_databento_preflight.py`, and `docs/databento-preflight.md`.

**Interfaces:** Consumes Task 1's extended `CostRequest`. Produces the existing JSON
result with `request.stype_in` reflecting explicit input. Schema and authorization
flags stay backward compatible; default parent invocations remain unchanged.

- [x] Add these failing integration tests:

```python
def test_raw_preview_never_loads_credentials(cli, private, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("preview must not load credentials or call the provider")

    monkeypatch.setattr(cli, "load_credential", forbidden)
    monkeypatch.setattr(cli, "estimate_cost", forbidden)
    symbol = "SPY   250117C00500000"
    code = cli.main([
        "estimate", "--credential-directory", str(private), "--symbol", symbol,
        "--stype-in", "raw_symbol", "--schema", "cbbo-1m",
        "--start", "2025-01-02", "--end", "2025-01-03",
    ])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "offline_preview"
    assert result["request"]["symbols"] == symbol
    assert result["request"]["stype_in"] == "raw_symbol"
    assert result["network_used"] is False
    assert result["download_authorized"] is False
    assert result["download_entitlement_verified"] is False
    assert result["economic_evidence"] is False
    assert result["credits_remaining"] is None
    assert list(private.iterdir()) == []


def test_invalid_raw_cli_denies_before_key_loading(cli, private, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid scope must not load credentials")

    monkeypatch.setattr(cli, "load_credential", forbidden)
    code = cli.main([
        "estimate", "--credential-directory", str(private), "--symbol", KEY,
        "--stype-in", "raw_symbol", "--schema", "cbbo-1m",
        "--start", "2025-01-02", "--end", "2025-01-03", "--allow-metadata-network",
    ])
    assert code == 2
    output = capsys.readouterr()
    assert KEY not in output.out + output.err
    result = json.loads(output.out)
    assert result["status"] == "denied"
    assert result["reason_code"] == "scope_invalid"
    assert result["network_used"] is False
```

- [x] Run `PYTHONPATH=src python -m pytest -q tests/integration/cli/test_databento_preflight.py`.
  Confirm the new valid preview fails because the new argument is not accepted.
- [x] Add the parser argument and constructor wiring, retaining all other behavior:

```python
cost.add_argument("--stype-in", choices=("parent", "raw_symbol"), default="parent")

request = CostRequest(
    tuple(args.symbol), args.schema, args.start, args.end, stype_in=args.stype_in
)
```

- [x] Replace the parent-only scope paragraph in `docs/databento-preflight.md` with:

> The fixed dataset is `OPRA.PILLAR`. Default parent mode accepts one to four
> alphabetic underlying roots and `definition` or `cbbo-1m`. Explicit
> `--stype-in raw_symbol` accepts one to 100 unique standard-format SPY option
> symbols, preserving their ASCII spaces, and supports only `cbbo-1m`. Syntax
> validation is not proof of deliverables, historical availability or tradability.
> No exact-contract selector or downloader is included. Underlying history,
> corporate actions, calendars and other costs are not estimated by this command.

Add this **offline-only synthetic syntax example**, not a selected contract:

```sh
PYTHONPATH=src python -m trading_bot.cli.databento_preflight estimate \
  --credential-directory /Users/jedweinstein/.robinhood-options-research \
  --stype-in raw_symbol --symbol 'SPY   250117C00500000' \
  --schema cbbo-1m --start 2025-01-02 --end 2025-01-03
```

- [x] Run all three existing credential/preflight modules, then the full offline
  test suite and existing coverage gates with coverage output in a temporary
  location. Preserve the 80% overall and 90% critical branch gates. Authenticated
  tests remain excluded. Use the verified Python environment, not an unverified venv.
- [x] Run Ruff, Mypy and Bandit using repository configuration; inspect
  `git diff --check` and the owned-file diff. Do not regenerate the tracked SBOM or
  change the lock; no dependencies were modified. Report unrelated baseline failures.
- [x] Commit only the three Task 2 paths with `git commit --only`. Have an independent
  reviewer inspect the combined credential-free diff before any real raw-symbol query.

## Acceptance and handoff

- [x] Old parent calls and outputs remain compatible; bounded raw previews work.
- [x] Invalid static symbol/mode/date-shape scope is rejected before credential loading
  and cannot reach a paid API. The unchanged clock-dependent future-date check is
  inside `estimate_cost`, after explicitly opted-in credential loading and before HTTP.
- [x] Tests use only invented keys, synthetic symbols and mocked HTTP; no downloads.
- [x] Record fresh verification commands/results; do not reuse the previous full-suite
  result as proof of this implementation.
- [x] Mark this feature technical-only. Exact research selection, underlying-data
  scope and acquisition approval remain separate work, not silently completed tasks.

After plan review and implementation, use a separately frozen private symbol/date
manifest for authorized free estimates. Never invent a historical contract merely to
obtain an attractive number. Before any purchase, present the entire required data
package, refreshed credit balance and explicit credit-only maximum to the operator.

## Execution record — completed 2026-09-22

Both approved tasks are implemented inline. Code commits: `b7f333a` (bounded raw
requests) and `a2f3450` (CLI and operator guide). A fresh independent read-only
review found no Critical, Important or Minor issues and independently passed the
88 focused tests. The scope/plan documents are included in the documentation commit.

Verification used the existing pinned Python 3.12.13 environment. Test-driven
evidence: 18 model cases failed before the new field existed; two CLI cases failed
before the argument was wired; the combined 88-test diagnostic suite then passed.

The first full run was interrupted after 2,315 passes when a legacy smoke test's
`uv run` subprocess selected the separate project `.venv` and stalled. No product
code was changed. Pinning nested uv to the verified environment made that entire
three-test smoke module pass in 0.85 seconds; the full suite was then rerun from
the beginning with fresh coverage output:

```sh
env PYTHONPATH=src \
  UV_PROJECT_ENVIRONMENT=/private/tmp/robinhood-anyio-verification.5rJfWx/.venv \
  UV_NO_SYNC=1 UV_OFFLINE=1 \
  COVERAGE_FILE=/private/tmp/options-exact-cost-verification.LDVBfr/.coverage-verified \
  /private/tmp/robinhood-anyio-verification.5rJfWx/.venv/bin/python -m pytest tests \
  --cov=trading_bot --cov-branch --cov-fail-under=80 --cov-report=term:skip-covered \
  --cov-report=json:/private/tmp/options-exact-cost-verification.LDVBfr/coverage-verified.json
```

Result: **5,579 passed, 4 skipped, 1 warning; 89.84% overall coverage**. The four
skips are the existing encrypted-backup integration cases requiring local `age`;
no cryptographic binary was installed and those cases are not claimed as executed.
The warning is the existing Starlette/httpx TestClient deprecation, not a changed
dependency. `scripts/check_critical_branch_coverage.py` passed the per-module 90%
gate using that new coverage JSON.

Additional checks passed: repository-wide Ruff, Mypy (238 source files), Bandit
(existing comment/nosec warnings only), `uv lock --check --offline`, root locked
requirements audit (no known vulnerabilities), changed-file format checks and
`git diff --check`. Deployment shell syntax and `docker-compose config --quiet`
passed; this host's `docker compose` plugin form was unavailable. No Docker service
was started. The full suite included the temporary-output SBOM reproducibility test.

The preexisting lock and tracked SBOM were preserved byte-for-byte:

- `uv.lock`: `bc4a00f5e4f9d251582f98694d410f59284a69798b8970311495e12e978c1044`
- `docs/sbom.cdx.json`: `085ecfb87803d0bd88b4d2efa53a7aab438356893b010799c4d7d70b88647750`

Execution decisions, their tradeoffs and the preserved future-date behavior are
recorded in [the preflight guide](../../databento-preflight.md#review-decisions-and-remaining-boundaries).
No deferred findings. Logs and coverage are retained under
`/private/tmp/options-exact-cost-verification.LDVBfr/`.

This completes the estimate-only software extension, not the research program.
No new authenticated Databento or broker call, raw-symbol provider estimate,
acquisition, subscription, risk change, deployment or live activation occurred.
Freeze the real contract/date manifest and matching underlying scope before using
this command for a complete acquisition proposal. No claim of economic readiness.
