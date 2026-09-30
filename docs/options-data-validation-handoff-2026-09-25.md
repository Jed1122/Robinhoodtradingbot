# Options validation data: authority and native-quality checkpoint

Recorded 2026-09-25 UTC against `8a3a55485a0da66a6645f5703fb4f5e2f596c277`.
Scope: fresh credit observation, read-only local data-quality profiling, and the
operator-approved integrated native-data design brief. No new data was purchased.

## Current acquisition authority

The operator explicitly authorized using **all existing Databento credits for data
necessary to complete economic validation**. This supersedes the earlier bars-only
$1 cap and per-request approval requirement for necessary historical-data purchases
within this expanded credit-only authority. It is permission, not an instruction to
exhaust credits or a claim that the balance funds a complete qualifying study.

The authenticated Billing page showed **$112.68 remaining credits and $0.00 due**
around 06:08 UTC. Usage-based access remains enabled with **No limit**. No account,
billing, credential or subscription setting changed. The earlier $0.89 bars request
is already reflected in this balance. [Billing](https://databento.com/portal/billing).

For each necessary acquisition, bind the exact dataset, schema, symbols, UTC range,
encoding and retained coverage manifest to a fresh customized-request quote. Recheck
applicable credits and outstanding accepted jobs, reserve pending costs in private
accounting, and submit once only if the full cost fits the unconsumed grant and fresh
applicable credits. Do not use uncertain acceptance as a reason to submit again.
Inspect existing jobs/local archives before requesting overlapping data.

No additional approval is needed for a necessary purchase meeting those conditions.
Stop for an unbounded or over-budget total, uncertain credit application, potential
cash charge, new agreement acceptance, subscription, upgrade, or unavailable access.
No cash top-ups, new subscriptions, live-data services, transfers, broker writes,
deployment or live activation are authorized. Later unrelated credit additions are
not assumed to enlarge this recorded grant. Retain unspent credits when the required
package is not ready or cannot meet the study's evidence requirements.

Databento distinguishes customized-request quotes from catalog estimates; credits
and an after-exceeded usage limit are not a hard transaction cap. The existing
private-use/local-retention attestation remains accepted, without a repeat OPRA
agreement request. [Credit behavior](https://databento.com/docs/faqs/usage-pricing-and-data-credits),
[usage-limit behavior](https://databento.com/docs/portal/billing).

## Fresh native SPY bars profile

The already-acquired package was read locally; no redownload, API key, data API,
broker connection, strategy calculation or holdout evaluation was used. The exact
diagnostic code and source identities remain in owner-private storage outside Git.
The diagnostic is not a production normalizer or a reusable trusted-source verifier.

| Check | Observed result |
| --- | --- |
| Scope | `XNAS.ITCH`, `SPY`, `ohlcv-1m`, `[2018-05-01, 2026-01-01)` UTC |
| Decoder | `databento-dbn==0.69.0`, DBN v1; `zstandard==0.25.0` |
| Complete decoded stream | 79,656,090 bytes; independent `zstd -t` passed |
| Provider-manifest checks | All three listed file sizes and SHA-256 values matched |
| Minute records / distinct native keys | 1,421,744 / 1,421,744 |
| UTC dates containing records | 1,929; not a verified regular-session count |
| Duplicate keys / timestamp regressions | 0 / 0 |
| Off-minute / out-of-request records | 0 / 0 |
| Metadata mapping mismatch / missing or ambiguous observed-date mapping | 0 / 0 |
| Undefined-price records | **2**; all four OHLC fields contain undefined sentinels |
| Provider condition declarations | 1,999 available dates; **3 degraded dates** |

The undefined rows fall on two of the provider-degraded dates. Raw row timestamps,
identifiers, prices, mappings and provider payloads are not copied into this document.
No rows were deleted or repaired. A finite-sentinel check is necessary: ordinary
OHLC ordering alone did not reject these equal undefined values. Final profile time
was 2026-09-25T06:13:42Z. Source payload hash was checked before and after the scan.

The scan verifies only the listed structural/native checks. It does not establish
gap-free sessions, original publication/revision times, corporate-action coverage,
complete point-in-time chains or market-wide close quality. Provider date statuses
are not a session calendar. The archive's minute timestamps mark interval starts;
missing no-trade bars and revisions require explicit treatment.
[OHLCV semantics](https://databento.com/docs/schemas-and-data-formats/ohlcv).

## Next approved design deliverable

The operator selected the **integrated native-data specification**: preserve raw
files; reject invalid observations; verify underlying sessions, corporate events and
availability; resolve native option definitions; feed the existing fixed shortlist
only through independently checked imported evidence; freeze complete quote coverage
before purchases. The alternative bars-only importer would not unlock the shortlist.

The [written specification](superpowers/specs/2026-09-25-native-options-data-integration-design.md)
records this design. Brief approval permits writing it, not skipping written-spec
and implementation-plan review. Native execution remains the operator's selected
workflow preference; no Cloud execution is claimed.

The exact option-quote package and its total cost are still unknown. No broad-chain
purchase substitutes for unresolved inputs or an independently defined study. The
existing 0.5% per-trade risk at the $100 capital assumption remains $0.50; additional
data credits do not fund the trading account or change that limit.

Disposition: **native quality profile and design preparation only; normalization,
genuine economic validation and live readiness remain incomplete**. Product tests
were not rerun because no product code, configuration or dependency changed.
Documentation verification checked all four task files, 12 local links, balanced
Markdown fences and whitespace. The private profile copy and rendered source receipt
were checked against the observed findings. The protected tracked SBOM hash is unchanged.
Ruff, Mypy, pytest, Bandit, dependency audit and deployment checks were not rerun for
this documentation-only change; their prior results are not claimed as fresh.
