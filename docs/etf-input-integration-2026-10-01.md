# ETF input integration and data access — 2026-10-01

## Outcome

Continued the approved offline SPY/cash build without waiting for another provider
reply. Integrated the partial Cloud fixture handoff, corrected two independently
reproduced contract bugs, and implemented the independent effective-date cost
loader. This is not a completed ETF runner or genuine economic validation.

The operator reports purchasing Algo Trader Plus. The available market-data
connector returned four 2016 SPY SIP daily bars and five dated SIP bid/ask quotes.
That is fresh evidence of those connector reads, not proof of account binding,
complete historical coverage, original provider bytes or subscription identity.

## Implemented boundaries

- Frozen bar, quote, action, session and control observations preserve exact
  nanoseconds, canonical Decimal values and content hashes.
- Bounded synthetic pages preserve source ordering and late revisions, reject
  malformed/duplicate inputs, and never construct an actually qualified dataset.
- Private manifests and referenced bytes are read without writes, symlink
  traversal or fallback to another provider/feed.
- Valid open-session clocks close before their next opening; closed-session
  clocks open before their next closing. Corporate-action effective dates must
  be exact immutable dates.
- `load_etf_cost_evidence(manifest_path, allowed_root, study)` binds the study and
  cost plan. Seven explicit roles must cover the whole study window without gaps
  or overlaps; costs known after their effective start and zero latency are denied.
- Every cost/calibration reference must have retained SHA256-matching bytes.
  Recorded labels and calibration hashes do not certify calibration.
- No network transport, broker capability, risk-limit change, deployment,
  live-mode change or production migration was introduced.

### Cost manifest contract

The owner-private input directory must be outside the repository, with mode 0700.
The 0600 manifest is named `<sha256>.json`; its exact keys are `schema`
(`etf-cost-manifest-v1`), `study_hash`, `cost_plan_hash`, `source_kind`,
`starts_at`, `ends_at`, `intervals` and `calibration_hashes`.
Intervals contain the existing `EtfCostInterval` fields with canonical decimal
strings and UTC microsecond strings. Source/calibration references use
`<sha256>.raw` in the same directory. Limits are 1 MiB per file, 8 MiB total,
10,000 intervals, 256 unique references and JSON depth 16.

Supported roles remain commission per share, minimum commission, regulatory cost
per notional, extra slippage, latency, cash rate and operating cost. Spread stays
in fill prices; this loader neither calculates fees nor applies a second spread.
The existing cost-evidence hash schema is unchanged.

## Access evidence and remaining qualification

Samples were requested explicitly from SIP for SPY. Bars covered
2016-01-04T00:00:00Z through 2016-01-08T00:00:00Z with limit 5. Quotes covered
2016-01-04T14:30:00Z through 14:30:01Z with limit 5. No holdout outcome was tested.
Connector responses and the private access note remain outside Git and Cloud.

The quote response reached its limit; neither formatter response provides a
complete page-chain proof. Native imports must retain pagination tokens and
request/feed identity: Alpaca explicitly requires checking the next-page token
even when a response contains fewer records than the requested limit.
[Historical quotes reference](https://docs.alpaca.markets/us/reference/stockquotes-1).

Daily bar timestamps identify the beginning of the New York daily interval,
not the time its complete close was available. The native adapter must therefore
establish session completion and availability separately.
[Market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

The native request must explicitly pin raw adjustment semantics and retain its
request parameters. The connector's current bar surface does not expose an
adjustment argument. Do not infer validated raw treatment merely from the default
documented for a different interface.
[Historical bars reference](https://docs.alpaca.markets/us/reference/stockbarsingle-1).

Still unestablished: full role/era/session coverage, exact original wire precision,
publication/receipt and revision history, fractional execution terms, payable
dividend treatment and empirically calibrated fills. Do not relabel the synthetic
wire format as an Alpaca adapter. The earlier narrow four-ETF, two-request
diagnostic also remains a separate scope; do not silently repurpose its credential
authority for full SPY acquisition.

## Verification

Fresh local checks on the implementation tree:

- Main suite: 6,370 passed / 33 skipped on each of Python 3.12, 3.13 and 3.14.
- Focused ETF checks: 144 passed on each of Python 3.13 and 3.14.
- Native data/pricing/historical integration: 376 passed on Python 3.12.
- Combined Python 3.12 coverage: 91.31%; the existing 90% critical-branch gate
  passed. New source and cost modules have 97.73% and 91.67% branch coverage.
- Ruff, Mypy, Bandit, both lock checks and both locked dependency audits passed.
- Compose validation and all four DigitalOcean shell syntax checks passed;
  no deployment was performed.
- Independent review reproduced both source bugs, confirmed their fixes and
  found no remaining issues in the source/cost-input scope.

The 33 main-suite skips concern optional native dependencies and local age
backup tooling; the native run separately exercised installed research backends.
The full suite includes the reproducible SBOM test, which preserves the tracked
artifact. Pre-existing dirty work remains excluded from this change, so these
local results do not replace hosted checks of the exact committed PR revision.

## Next work and decisions

1. Native SPY acquisition/import and actual-source qualification, retaining exact
   pages and source semantics rather than promoting these connector samples.
2. Causal ETF account replay, then transactional restart and reconciliation.
3. After-cost benchmark/uncertainty evaluation, with the final holdout untouched
   until the protocol and all inputs are frozen.
4. Separate broker/runtime verification, qualified paper/shadow operation and
   explicit live authorization.

The cost loader was advanced ahead of the runner because its Task 1 interface was
already frozen and it has no account-owner dependency. The economic evaluator is
still pending. If later integration exposes a missing cost input, revise that
bounded interface with tests; do not invent zero costs or relax risk controls.

Tasks 2 and 5 remain partial; Tasks 3, 4 and 6 are not completed by this handoff.
Source and calibration verdicts remain blocked/unverified, economic evaluation
has not run, and execution/promotability flags remain false. Provider
correspondence is not a reason to pause independent offline implementation.
