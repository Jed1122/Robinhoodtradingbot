# Supported-Python and readiness checkpoint — 2026-09-30

Status: local compatibility repairs verified; hosted CI remains externally blocked.
These tests are software/fixture evidence, not an economic result or live approval.

## Changes

- Use the actual stdlib logging registry RLock on Python 3.12–3.14; removed helper
  names are no longer called. Reentrancy, cross-thread exclusion and release have
  a regression test. Secret-redaction behavior is unchanged.
- Bind uv to each workflow's declared Python. No required check is removed.
- Make hostile-dictionary and traceback fixtures portable; keep their leak/error
  assertions. Accept both supported exception types for prohibited dataclass
  replacement and additionally assert that non-promotability remains false.
- Integrate the separately approved $1,000 inclusive account-equity ceiling with
  canonical config/hash/stage checks. All other risk amounts, paused defaults,
  authorization, promotion and lease gates remain unchanged. Historical golden
  evidence uses its original $150 fixture policy, not a rewritten expected hash.

## Executed verification

Local macOS runs, frozen main/research dependencies, no authenticated CI tests:

| Environment | Main suite | Main plus native coverage | Critical branch gate |
| --- | --- | ---: | --- |
| Python 3.12.13 | 6,226 passed; 33 skipped | 89.10% | Passed |
| Python 3.13.2 | 6,226 passed; 33 skipped | 89.10% | Passed |
| Python 3.14.6 | 6,226 passed; 33 skipped | 88.60% | Passed |

The exact mandatory Python 3.12 research workflow selection passed 909 tests.
Each interpreter also passed the 21-test native append selection (20 historical
episode cases plus the final replacement-regression case). Counts overlap and
must not be added as independent test totals. Main-suite skips include optional
native backends; the dedicated research environment exercises its mandatory ones.

The first 3.13/3.14 full runs each exposed one remaining exception-type assumption;
after its test-only fix, both complete suites passed. Coverage was retained from
the full runs and appended with the corrected case and native episode selection.
All final main suites report one existing Starlette deprecation warning.

Ruff, Mypy (282 source files), Bandit, both offline lock checks, both locked public
dependency audits, shell syntax, Compose configuration and diff checks passed.
Both vulnerability audits reported no known vulnerabilities; this is not a
security guarantee. No dependencies were upgraded during these repairs. The SBOM
reproducibility test used a temporary destination and preserved the dirty artifact.

Detailed local logs and coverage JSON remain in ignored
`reports/ci-remediation-2026-09-30/`. Verification was against the current dirty
working copy; unrelated pending work is preserved and is not part of this change.
This is not a clean Linux hosted-run result.

## External gates and next steps

The latest inspected GitHub annotation says the job was not started because of
failed account payments or a spending-limit restriction. The inspected run is
[36761860859](https://github.com/Jed1122/Robinhoodtradingbot/actions/runs/36761860859).
Local green tests do not override that restriction or replace required checks.
Push reviewed scoped changes, obtain current hosted results after billing/reset,
and merge only when required checks actually pass on the current PR revision.

Read-only broker/paused-host findings and their limits are recorded separately in
[the source/runtime checkpoint](etf-data-source-checkpoint-2026-09-30.md).
The ETF specification and implementation plan are approved, not implemented by
these CI changes. Source qualification, economic evidence, qualifying paper/shadow
observations and unattended broker/runtime capability remain separate work.
