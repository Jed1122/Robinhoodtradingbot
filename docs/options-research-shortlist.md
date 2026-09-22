# Offline SPY options research shortlist

This command implements a deterministic **acquisition universe**, not an entry
signal, order, backtest, economic finding or live-trading capability. It selects
one SPY call and one put at a common expiry, or records why no pair was selectable.

## Run

Use the installed locked Python environment from the repository root:

```sh
python -m trading_bot.cli.options_research options-shortlist /absolute/private/input.json --output-dir /absolute/private/output
```

Both parent directories must already exist, be owned by the current user, and
have mode `0700`. Input must be a regular `0600` file. Paths must be absolute,
outside this repository, without `..` or symlink components. The output root may
equal the input parent. No credential is needed or read.

The command explicitly loads `configs/options/shortlist/simulation.yaml` through
the existing canonical loader with an empty environment. The nested filename
preserves the loader's filename/mode check. Base and ordinary simulation keep
the feature disabled. PAPER/SHADOW/MICRO_LIVE/LIVE activation is rejected.
Every field is required in the resolved YAML graph and release envelope; Python
defaults do not silently fill omitted configuration. Existing programmatic config
builders must supply the new section explicitly.

Limits: one decision session, 25,000 records (options records + close observations
+ action observations + calendar-day declarations), 16,777,216 uncompressed UTF-8
JSON bytes and nesting depth 16. There is no compressed-input or batch mode.
Resource caps may tighten; policy values cannot change in this version.

## Policy and causality

Version `spy-prior-close-atm-30d-v1` uses the immediate prior completed underlying
regular session's unadjusted, non-interpolated SPY close. The calendar declares
closures and early closes; UTC instants retain America/New_York trading dates.
A source-specific last trade remains labeled as such, not a consolidated close.
An options session ending later than the underlying session cannot substitute for it.

Eligible standard USD American PM physically settled contracts have multiplier 100
and deliverable 100 SPY shares. Both directions must exist at one expiry within
inclusive 21–45 calendar days. Closest to 30 days wins, then earlier expiry. Each
side selects the nearest strike, then lower strike; output is call then put.

Definitions, source evidence, calendar and close must be available by the target
session open. Future revisions cannot alter the earlier decision hash. Full input
hashes still change when input bytes change. Duplicate economic identities and
conflicting simultaneous visible revisions are errors, not arbitrary tie breaks.

Visible splits, mergers and denomination/deliverable changes possibly intervening
between prior close and target open deny selection. Date-only actions are treated
conservatively across both endpoint trading dates. Cash dividends remain context
and do not adjust the reference price. Unknown actions deny coverage.

There are no bid/ask, liquidity, Greeks, return or balance ranking inputs. A chosen
contract is never replaced because later quote coverage is missing or unattractive.
This candidate pair does not authorize a straddle, two entries or a larger position.

## Provenance boundary

Only fabricated inputs can currently produce candidates. Internally consistent
imported envelopes are parsed but return `source_evidence_unverified`; there is
no JSON flag or digest that unlocks real-source authenticity/completeness checks.
Native definitions/underlying normalization and trusted source-availability review
remain separate work. No downloaded archive is consumed by this command.

All manifests permanently set these fields to false:

- `production_eligible`
- `evidence_promotable`
- `download_authorized`
- `live_authorized`

Code identity hashes a fixed installed-source inventory. It is not executing-image
attestation, a complete dependency inventory, provider authentication or a live permit.
The new configuration graph has a new identity even when the shortlist is disabled.
Historical hashes are not rewritten. Legacy replay golden tests retain their original
result hashes using a narrowly scoped test-only old-schema serialization projection,
pinned to the original full configuration digest. Production hashing has no projection.

## Output and exit codes

Stdout contains only status, decision/candidate/denied-session counts, reasons and
manifest hash. It does not print selected symbols, licensed rows or private paths.
The private manifest is saved at
`OUTPUT_ROOT/options-shortlists/<manifest_hash>.json` with mode 0600; its directory
has mode 0700. Schema is `options-shortlist-manifest-v1`, with the full research
result and counts. Hashes bind config, scoped code, raw input bytes and causal evidence.

| Condition | Exit | Status/reason |
| --- | --- | --- |
| Pair selected | 0 | `selected` |
| Valid but unselectable session | 0 | `no_candidate` with one reason below |
| Invalid JSON/schema/types/config/limits | 1 | `options_shortlist_input_invalid` |
| Unsafe path | 1 | `shortlist_path_invalid` |
| Different bytes already occupy artifact name | 1 | `shortlist_storage_conflict` |
| Publication/durability failure | 1 | `shortlist_storage_unavailable` |

No-candidate reasons, in evaluation order: `shortlist_disabled`,
`source_evidence_unverified`, `calendar_unverified`, `prior_close_unavailable`,
`action_coverage_unverified`, `reference_discontinuity`, `chain_unavailable`,
`no_common_eligible_expiry`.

Equal reruns are idempotent and never overwrite a different artifact. A directory
sync failure after publication can leave a complete artifact with uncertain
durability; no success is claimed, and retrying identical input re-establishes
durability without deleting that artifact.

## Complete fabricated input example

The following was generated from the committed `make_case()` test fixture. Save
the JSON in a private 0600 file outside the repository to exercise the command.
It is invented SPY-shaped data, **not historical market observations**. The schema
requires every field shown; missing optional evidence is explicit JSON null.
Nested records retain the existing `options-data-record-v1` schema and hashes.

```json
{"schema":"options-shortlist-input-v1","sessions":[{"action_evidence":{"available_at":"2023-12-28T14:30:00.000000Z","covers_from":"2023-12-29T14:30:00.000000Z","covers_through":"2024-01-02T21:00:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","semantics":"synthetic-shortlist-v1","source":"synthetic-shortlist","source_kind":"synthetic"},"actions":[],"calendar":{"days":[{"regular_session":{"closes_at":"2023-12-29T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2023-12-29T14:30:00.000000Z","session_id":"synthetic-regular-2023-12-29","trading_date":"2023-12-29"},"trading_date":"2023-12-29"},{"regular_session":null,"trading_date":"2023-12-30"},{"regular_session":null,"trading_date":"2023-12-31"},{"regular_session":null,"trading_date":"2024-01-01"},{"regular_session":{"closes_at":"2024-01-02T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2024-01-02T14:30:00.000000Z","session_id":"synthetic-regular-2024-01-02","trading_date":"2024-01-02"},"trading_date":"2024-01-02"}],"evidence":{"available_at":"2023-12-28T14:30:00.000000Z","covers_from":"2023-12-29T14:30:00.000000Z","covers_through":"2024-01-02T21:00:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","semantics":"synthetic-shortlist-v1","source":"synthetic-shortlist","source_kind":"synthetic"}},"chain_evidence":{"available_at":"2023-12-28T14:30:00.000000Z","covers_from":"2023-12-29T14:30:00.000000Z","covers_through":"2024-01-02T21:00:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","semantics":"synthetic-shortlist-v1","source":"synthetic-shortlist","source_kind":"synthetic"},"closes":[{"available_at":"2023-12-29T21:01:00.000000Z","bar":{"close":"100","data_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","ends_at":"2023-12-29T21:00:00.000000Z","high":"101","instrument_id":"SPY","interpolated":false,"interval":"one_day","low":"99","open":"100","source":"synthetic-shortlist","starts_at":"2023-12-29T14:30:00.000000Z","volume":"1000"},"coverage_label":"source_last_trade","evidence":{"available_at":"2023-12-28T14:30:00.000000Z","covers_from":"2023-12-29T14:30:00.000000Z","covers_through":"2024-01-02T21:00:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","semantics":"synthetic-shortlist-v1","source":"synthetic-shortlist","source_kind":"synthetic"},"price_basis":"unadjusted"}],"current_session":{"closes_at":"2024-01-02T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2024-01-02T14:30:00.000000Z","session_id":"synthetic-regular-2024-01-02","trading_date":"2024-01-02"},"option_source":"synthetic-shortlist","prior_session":{"closes_at":"2023-12-29T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2023-12-29T14:30:00.000000Z","session_id":"synthetic-regular-2023-12-29","trading_date":"2023-12-29"},"records":[{"kind":"contract","record":{"available_at":"2023-12-28T14:30:00.000000Z","event_at":"2023-12-28T14:30:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","source":"synthetic-shortlist","source_kind":"synthetic","value":{"adjusted":false,"available_at":"2023-12-28T14:30:00.000000Z","contract_id":"synthetic-2024-02-01-call-99","currency":"USD","data_hash":"c442837b71ee90bee53dee5b042a399e783ed148ec6ffd5e91f35cb89e7ebbf1","deliverable_symbol":"SPY","deliverable_units":"100","eligible_sessions":[{"closes_at":"2024-01-02T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2024-01-02T14:30:00.000000Z","session_id":"synthetic-regular-2024-01-02","trading_date":"2024-01-02"}],"exercise_style":"american","expiration":"2024-02-01","kind":"call","last_trading_at":"2024-02-01T21:00:00.000000Z","premium_multiplier":"100","settlement_at":"2024-02-02T21:00:00.000000Z","settlement_kind":"shares","settlement_timing":"pm","standardized_id":"SPY   240201C00099000","strike":"99","tick_size":"0.01","underlying":"SPY"}},"record_hash":"83aae9f8893431dc89e941a195e646de893f17396d7487b3954c600edb15c3c9","schema":"options-data-record-v1"},{"kind":"contract","record":{"available_at":"2023-12-28T14:30:00.000000Z","event_at":"2023-12-28T14:30:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","source":"synthetic-shortlist","source_kind":"synthetic","value":{"adjusted":false,"available_at":"2023-12-28T14:30:00.000000Z","contract_id":"synthetic-2024-02-01-call-101","currency":"USD","data_hash":"8603afb88abb826749411741ef326c990530737e524929445fcb2de1b5154c7e","deliverable_symbol":"SPY","deliverable_units":"100","eligible_sessions":[{"closes_at":"2024-01-02T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2024-01-02T14:30:00.000000Z","session_id":"synthetic-regular-2024-01-02","trading_date":"2024-01-02"}],"exercise_style":"american","expiration":"2024-02-01","kind":"call","last_trading_at":"2024-02-01T21:00:00.000000Z","premium_multiplier":"100","settlement_at":"2024-02-02T21:00:00.000000Z","settlement_kind":"shares","settlement_timing":"pm","standardized_id":"SPY   240201C00101000","strike":"101","tick_size":"0.01","underlying":"SPY"}},"record_hash":"ab675689366bcdc6bdf62fefd741ba77fc8cf5d8180cf918d08791fcd7361647","schema":"options-data-record-v1"},{"kind":"contract","record":{"available_at":"2023-12-28T14:30:00.000000Z","event_at":"2023-12-28T14:30:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","source":"synthetic-shortlist","source_kind":"synthetic","value":{"adjusted":false,"available_at":"2023-12-28T14:30:00.000000Z","contract_id":"synthetic-2024-02-01-put-99","currency":"USD","data_hash":"ca464d1468b2aaf694f5eb0a4a63e0a647a68b5fbf1df4ad204fc0f87b90dd34","deliverable_symbol":"SPY","deliverable_units":"100","eligible_sessions":[{"closes_at":"2024-01-02T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2024-01-02T14:30:00.000000Z","session_id":"synthetic-regular-2024-01-02","trading_date":"2024-01-02"}],"exercise_style":"american","expiration":"2024-02-01","kind":"put","last_trading_at":"2024-02-01T21:00:00.000000Z","premium_multiplier":"100","settlement_at":"2024-02-02T21:00:00.000000Z","settlement_kind":"shares","settlement_timing":"pm","standardized_id":"SPY   240201P00099000","strike":"99","tick_size":"0.01","underlying":"SPY"}},"record_hash":"1a565205fecbdd5da45c6f22eb213d78ba442a7f82e6fc7a044c46129641a2ab","schema":"options-data-record-v1"},{"kind":"contract","record":{"available_at":"2023-12-28T14:30:00.000000Z","event_at":"2023-12-28T14:30:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","source":"synthetic-shortlist","source_kind":"synthetic","value":{"adjusted":false,"available_at":"2023-12-28T14:30:00.000000Z","contract_id":"synthetic-2024-02-01-put-101","currency":"USD","data_hash":"efc601dec9a5e66b2b7fb1ba90d14a3f0683657b373646096a866479a171dc08","deliverable_symbol":"SPY","deliverable_units":"100","eligible_sessions":[{"closes_at":"2024-01-02T21:00:00.000000Z","exchange_timezone":"America/New_York","opens_at":"2024-01-02T14:30:00.000000Z","session_id":"synthetic-regular-2024-01-02","trading_date":"2024-01-02"}],"exercise_style":"american","expiration":"2024-02-01","kind":"put","last_trading_at":"2024-02-01T21:00:00.000000Z","premium_multiplier":"100","settlement_at":"2024-02-02T21:00:00.000000Z","settlement_kind":"shares","settlement_timing":"pm","standardized_id":"SPY   240201P00101000","strike":"101","tick_size":"0.01","underlying":"SPY"}},"record_hash":"5aa7c3fb77b79813fe59045ad568e8c481907925948edb0cb8f6365035f187e3","schema":"options-data-record-v1"},{"kind":"chain","record":{"available_at":"2023-12-28T14:30:00.000000Z","event_at":"2023-12-28T14:30:00.000000Z","raw_hash":"1768c09642b125c04d504e17607bafd9f3a8b2935e6ca53b085cf06debbd659f","source":"synthetic-shortlist","source_kind":"synthetic","value":{"contract_ids":["synthetic-2024-02-01-call-99","synthetic-2024-02-01-call-101","synthetic-2024-02-01-put-99","synthetic-2024-02-01-put-101"],"underlying":"SPY"}},"record_hash":"1288fad183fd4c89b7777d37e781d92b3ef3f260d7d7c7fc15be868acca76fe0","schema":"options-data-record-v1"}],"source_kind":"synthetic"}]}
```

## Verification and unresolved work

Implementation uses Native execution and test-first development. The pre-change
baseline was 5,579 passing tests, four local age-tool skips and one existing
Starlette/httpx deprecation warning. Focused selector/config/CLI regression passed 93
tests; codec/storage regressions passed 195. After correcting configuration regression
tests, the complete suite passed **5,781 tests**, with the same four age-tool skips
and existing warning. Overall line/branch coverage is **90.05%**, above the 80% gate.
The existing 90% per-critical-module branch gate passed. New-module branches are
selector **61/66 (92.42%)**, models **24/24**, wire **8/8** and IO **2/2**.

Ruff check and owned-file formatting passed; Mypy passed for 242 source files.
Bandit found no issues (12 existing explicit suppressions). Locked-dependency check
passed. SBOM/critical-coverage smoke tests passed 25/25. DigitalOcean shell syntax
and standalone `docker-compose config --quiet` validation passed; no service started.
The independent whole-range review remains the final gate before handoff.

The existing SBOM reproducibility check writes temporary files and preserves the
tracked artifact. Its generator currently reports an empty component inventory
plus a lock digest; reproducibility is not a complete dependency SBOM. This
pre-existing limitation is not hidden or expanded into unrelated changes.

No broker, data-provider or DigitalOcean operation, purchase, deployment or live
activation is part of this work. An operator-approved dependency advisory audit
sent package names/versions only to public vulnerability services and found no known
vulnerabilities. Its `--no-deps` hash-hardening warning remains advisory; the input
was exported from the locked dependency graph, with no dependency or lockfile edits.

### Native execution rulings

1. One final independent review replaces the plan's additional intermediate review,
   matching the operator's Native choice. Cost if wrong: defects surface later, before
   handoff rather than between tasks.
2. Model tests preceded implementation despite the plan's numbered ordering. Cost if
   wrong: execution ordering only; behavior is unchanged.
3. The profile is nested at `options/shortlist/simulation.yaml` to preserve the existing
   filename/mode invariant. Cost if wrong: callers must use this documented path.
4. Config identities use the canonical `ConfigHash` type, not `DataHash`. Cost if wrong:
   typed caller annotations require alignment; serialized values are unchanged.
5. All new config fields are required, preserving the repository's strict graph rule
   instead of the plan's implicit Python defaults. Cost if wrong: older programmatic
   builders need an explicit shortlist section.
6. The legacy replay test harness serializes the original config schema and asserts
   its original digest; production still hashes the complete new graph. Cost if wrong:
   the harness might hide a config regression, limited by that independent digest pin.

Remaining dependent work: verified native normalization/source evidence, a
separately authorized quote-cost/acquisition scope including exits/expiry and
settlement coverage, preregistered genuine historical economic testing and all
independent broker/runtime/operator gates. Synthetic success establishes none
of those outcomes.

Unchanged constraints include the $100 capital assumption, $150 live-account
equity ceiling, 0.5% per-trade budget, $50 outer per-trade cap and $50
non-replenishing cumulative trial-loss ceiling, subordinate to stricter controls.
The downstream 3,650-calendar-day request, 750-bar minimum, five folds, at least 50
test bars/fold and 30 independent opportunities remain where applicable. No exit
policy, study split, affordability increase or accepted economic result is chosen here.
