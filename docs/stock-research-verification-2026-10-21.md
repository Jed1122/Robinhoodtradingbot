# Individual-stock research verification — 2026-10-21

This is a development checkpoint, not deployment readiness, strategy qualification or
live authorization. No real-money orders, reviews, cancellations or transfers occurred.
The existing deployed paused services were unchanged during this work.

## Official source observations

A separately authorized dedicated research browser grant captured 83 selected-server
tool declarations. A new process then reused the encrypted saved credential without a
browser. The credential remains trading-capable despite local research restrictions.
One later official refresh succeeded and persisted absolute lifetime metadata. A fresh
process reused that new generation without a callback and retrieved all 83 declarations;
schema artifact SHA-256 `d7e31092ac39b56350cac907769916f17bdd95d5cb89e3d4c1f1126e1ee8f1dc`.
Natural expiry, owner-revoked denial and deployed background authentication remain unverified.

The reviewed 13-tool stock-only profile has SHA-256
`f95f313e2187326c610032029be438839536c6da69de30f17b1d1fe642d235f1`.
It excludes customer-account and order operations independently at facade and transport.
The actual research client completed 53 permitted data calls across five bounded captures:

| Capture | Calls | Manifest SHA-256 |
| --- | ---: | --- |
| Catalogs | 4 | `61c43cacaf97214e546204eaf6431974313e58bbd375f6c126103b4b4a2e62ef` |
| Broad discovery / initial partitions | 5 | `ac53c1e3f9445bfb4ea2b11a20a229ecfb80cd6268631b5d511d91ed5156801d` |
| Fine partitions | 16 | `2bfa59446c85f14bd4bc7c3ed7f7d6f2e07e9de32f7635e8b30914c605552c5e` |
| Refined truncated interval | 3 | `25aad07c4f5d1158b622971e8bfeafa354dd7ed23723f5a847b201a952fb3661` |
| Shortlist enrichment | 25 | `0b6f7bdd7a2add233e649ba83c4e9daa774bc3d743ad65f29a1a61b8f28f6a1b` |

All native structured payloads and request/receipt provenance remain in owner-private
storage outside source checkouts. None are fixture data or retained HTTP wire frames.
Rehashing authenticates retained bytes, not vendor signatures or historical completeness.

The initial broad query hit the row cap. Fifteen finer groups still included one 209-row
match returning only 200. The ranking correctly remained empty. Splitting only that
interval and reusing the other retained groups yielded 16 complete observed query groups,
1,470 distinct stocks and 1,057 with usable values for all six experimental factors.
Ten companies were prioritized for additional research. Sequential queries remain
non-atomic; these counts do not establish a simultaneous exchange-wide universe.

The resulting private descriptive report SHA-256 is
`abb260fef6c048aa12a9b96d6646ea6518bf8421c675626ead5a1ecdee1288d0`.
Its canonical research configuration hash is
`f1c4063c3fad36a3c6e381cffddc08006bf61efd66fd22ebcd31e4d7ab4d9484`.
The score orders research effort and has no established relationship to future returns.
Every candidate remains investment-ineligible.

The 25 enrichment calls returned fundamentals, annual/quarterly financials, quotes,
daily raw-request history, earnings results and SEC filing indexes. Five positional
financial results were null; this means no returned financial data for those slots,
not zero revenue. Of 2,650 returned daily bars, 193 were labeled interpolated. Synthetic
bars cannot supply genuine trading activity or establish liquidity. The corrected
normalizer retained 10 fundamental records, 38 annual financial periods and 60 quarterly
periods while explicitly preserving the five unavailable companies. One historical row
not marked interpolated violated its OHLC range, so the strict history normalization correctly
denied that batch. The bad row remains in the original capture; no price was repaired,
zero-filled or silently accepted. Subsequent whole-company projection quarantined the
affected company's entire history while retaining nine valid histories with 2,385 bars.
All 193 rows marked interpolated belonged to the quarantined company; none of the
nine accepted histories contained a bar marked interpolated. Ordinary retained bars
omit the optional interpolation flag, so their interpolation state remains unknown.
Projection context retains original batch/index/hash and
separate local projected hashes. Twenty earnings and filing-index collections also
normalized successfully. No qualifying strategy result follows.

The integrated archive-to-dossier report rehashed the actual 25-call enrichment capture,
normalized source facts, retained the whole-company history quarantine, and published
10 company dossiers with zero collection normalization denials. Every dossier explicitly
retains data gaps and disabled investment eligibility. The private report SHA-256 is
`53df6a2c1f21ec96a2724a85fc643c40c86f8569345b3e4589e456f6aa8ab8a8`.
The company dossiers are evidence inventories; filing contents and investment theses
have not yet been substantively evaluated.

Schema-v2 technical binding retained nine `ineligible` histories and one quarantined
history, producing zero technical metric values. All 2,385 retained ordinary bars had
an omitted interpolation flag. The reviewed output schema permits omission but supplies
no default, and the response guide does not establish one. No unknown flag was coerced
to false. The dossier exposes `history_interpolation_unknown`; resolving source semantics
or obtaining a permitted dataset with explicit evidence is an outstanding qualification
step. Synthetic fixtures verify the technical formulas; they do not supply missing actual
market evidence. The earlier v1 and initial v2 reports remain retained separately.

A separate public Nasdaq directory capture retained 13,293 rows and 5,176 tentatively
eligible common-stock listings. Name-based security classification remains conservative
and heuristic. Current membership is not historical survivorship-free membership.

## Engineering evidence

The stock deployment request/prestart gate is implemented locally and independently
reviewed. It passed 129 fictional tests with 100% branch coverage after a source-backed
RED-to-GREEN correction for Docker's permitted null-versus-empty no-volume map.
The GET-only Engine reader passed 53 fictional/socketpair tests with 97.40% branch
coverage after review's shared-transport route finding was reproduced RED and fixed.
Independent combined deployment regression passed 427 tests with four optional local
age skips; those skips do not prove encrypted backup or recovery. Ruff, strict mypy
(444 source files), expanded Bandit and dependency-lock checks passed locally.

A separately authorized read-only check ran the exact reviewed reader/version-parser
source at `6d6b8c0a6a77f6522a92fe6ac213a0c9f8df63f9` in memory on the existing host.
One `/version` GET succeeded through the fixed root-owned Unix socket and UID-0 peer,
yielding an accepted API 1.52/Linux amd64 profile. There was no host installation,
Docker mutation, image/container inspection, broker request or credential operation.
This proves only that bounded metadata transport path. Native immutable-image and
created-CID verification, applied hardening, deadline/recovery supervision, scheduled
stock acquisition and operational backups remain incomplete. The primary full suite
at frozen a63a475 is still pending; this later source increment remains separate.

The schema/profile/bootstrap correction passed 607 relevant checks plus repository
Ruff, strict mypy, Bandit and dependency-lock verification at its reviewed checkpoint.
The new capture/reader/screen/config correction passed 51 focused checks, including
RED-to-GREEN regressions for publication, cancellation, input bounds, factor identity,
extreme decimals and contradictory rehashed manifests. Independent review cleared
those corrected paths. The integrated new stock surfaces subsequently passed 114 tests
with 88.18% combined statement/branch coverage against an 80% gate. Coverage is for the
new capture, archive, screen, stock configuration and fact normalizers, not the entire
application; the capture module individually measured 79%. Independent review also
cleared positional financial nulls and interpolated-bar omission provenance.

The earlier broad selected suite terminated with 4,386 passed, 18 skipped and one
architecture failure: this work had placed broker-bound archive I/O under research.
Moving it into runtime corrected that boundary; targeted architecture checks passed.
The current integrated broker/runtime/architecture and stock evidence regression then
passed 723 tests after technical integration and the interpolation-gap regression.
The renewal/lifecycle/provider/SDK subset passed 89 tests, including
17 filesystem, cancellation, single-POST and no-replay renewal cases. Two independent
reviews cleared those protected paths. Repository Ruff and strict mypy (430 source files)
passed. Bandit, offline lock and diff
checks also passed. These source/fixture checks remain distinct from actual official refresh and
schema-reuse evidence. No complete all-repository test pass is claimed for this revision.

## Later local worker and dashboard checkpoint

The one-shot worker at 32f4de3 completed one additional authorized discovery with
exactly 17 planned, attempted and successful stock-data calls. It reused the dedicated
saved grant without a browser callback and invoked no account or order tools. Manifest
SHA-256 `a300b94bbe13a67524e6ee38034487b3199e5373c1e7c59d8f7595157e72d6af`
and report SHA-256
`49b84c53040a9546f782602444dd884cf8f103d65a65eff55ecf78abb09a63b1`
were rehashed and recomputed at the original cutoff. Sixteen complete observed query
groups yielded 1,472 candidates, 1,058 scorable companies and ten research priorities.
The canonical configuration hash was
`deff9b8bdaadb5765dfe79dd4b2f0f091f1a857cb81cd57594be3b3922920d10`.
An immediate process restart returned `not_due`, with no new claim or capture.
This adds 17 calls to the earlier 53; it does not replace those source checkpoints.
No company or strategy became investment-eligible.

The frozen 7cd644d baseline completed with 11,407 passed, 33 optional skips, one warning
and 88.55% combined branch coverage. The optional native-data, QuantLib and local-age
skips are not native or encrypted-backup evidence. Subsequent worker/CLI/persistence
integration at 32f4de3 passed 455 central tests; that older full run does not certify
the later source changes.

The bounded stock-dashboard backend then passed 417 central tests with 93.63% combined
branch coverage, independent review, Ruff, strict mypy, Bandit and lock checks. The
integrated stock UI passed 57 tests and a production frontend build. A fictional local
projection traversed the real private publisher, file reader, authenticated API and
built UI on desktop and mobile without browser errors, warnings or page overflow.
No provider or credential operation was part of this dashboard check. The
[export contract](stock-dashboard-export.md) describes the implemented boundary.

## Outstanding work

The later local collector-control feature passed 290 focused/architecture tests with
96.09% combined branch coverage over controls, CLI, worker and job store. Independent
review cleared the implementation after lost-anchor and operation-error regressions.
It requires explicit active authority for acquisition, preserves budget on suspension,
and fences old cycles across pause/resume. Its state and operator procedure are in the
[control contract](stock-research-controls.md). It has not been exercised as a deployed
supervised collector. The full dashboard baseline at 3cd8e8c terminated with 11,597
passed, 33 optional skips, two failures and 88.74% combined branch coverage in 4,780.71
seconds. It does not validate this subsequent feature.

Both failures were test-context interactions, reproduced with small cases. A printable
fictional authentication seed matched the dashboard's repeated-character placeholder
digest; the production secret guard correctly denied it. The fixture now uses real
deterministic SHA-256 values and exercises both registered-seed and ordinary contexts.
A logging test assumed the logger manager had never been configured; it now explicitly
arranges its existing third-party logger under a scoped patch and exercises configured
and unconfigured contexts. Exact type/caller assertions remain intact. A review-found
test teardown leak was reproduced and corrected; ambient manager state is preserved.
No production logging/model/secret guard changed. Independent reviews and the final
provider-to-dashboard-to-logging ordered regression passed 131 tests. The corrected
integrated full run remains required; the failed run is not a full-suite pass.

The configuration-only command, isolated Compose source and immutable retained-release
verifier are also implemented locally. The verifier/policy passed 102 fictional checks
with 99% verifier branch coverage. Separate data-only Engine/image metadata parsers
passed 67 checks with 100% branch coverage, and the deployment-test directory passed
245 checks with four optional local-age skips. Independent reviews cleared the corrected
cleanup and numeric-overflow boundaries. Actual pinned-image observation, CID inspection,
trusted attestation production, supervision, termination and native deployment remain
unverified. See [operations status](stock-research-operations.md).

The research acquisition/cache scheduler is not yet a verified persistent background
service. Natural-expiry/revocation recovery, substantive company research, complete
raw-session liquidity, stock point-in-time datasets, out-of-sample strategy/cost/tax validation,
nonempty broker reconciliation and encrypted operational backup/watchdog installation
remain outstanding. No stock strategy has qualified for capital allocation. There is
no mandatory paper waiting period; live activation still requires separate authorization.

A broker-neutral reconciliation audit used only fictional records. Twenty-seven
regressions reproduced false-clean results before account/row scoping, position
economics, order terms, fill-time comparisons and duplicate-view handling were fixed.
The corrected service passes 50 focused tests at 100% combined statement/branch
coverage. The integrated reconciliation, execution, persistence, risk, adapter and
architecture check passed 1,891 tests in 295.27 seconds, with 99.03% combined coverage
over reconciliation. Ruff, strict mypy (445 files), expanded Bandit and lock checks
passed. Independent review cleared ca31b24 after 70 targeted tests, a 7,225-case
order-view oracle and ten foreign-data retention probes. This does not
verify native Robinhood positions/orders/fills: unverified nonempty and paginated
provider response shapes still deny.

## Later local integration and recovery-library checkpoint

The corrected full baseline at a63a475 terminated successfully: 11,810 passed,
33 optional skips, one dependency deprecation warning, 88.77% combined branch
coverage in 4,258.53 seconds. The primary was then fast-forwarded locally to
f04a63f after review and 641 focused tests with four optional age skips. Its new
actual full-suite process is still pending; it must finish before another primary
integration. Neither full run covers the later dispatch/manifest/termination source.

Root integrated the independently reviewed pure stock manifest ae991be at 63a988e
and reran 956 deployment/architecture/stock-data checks, with four optional age skips.
The first command used a nonexistent screen-test path and collected no tests; only
the corrected terminal run supplies that evidence. Ruff, strict mypy (447 files),
expanded Bandit, lock and diff checks passed. The adapter independently passed
200 focused tests and 58 additional negative probes, with false qualification flags.

The root-only cleanup increment exposes copied validated receipt snapshots and
fresh owned-container TERM/KILL dispatch. Seventeen snapshot and 74 missing-library
RED cases were followed by 235 focused passes at 98% combined store/termination
coverage. Central deployment/architecture/stock-data regression passed 1,047 tests
with four optional age skips. Ruff, strict mypy (448 files), expanded Bandit, lock
and diff checks passed. Independent review remains pending. No native Docker
mutation, new provider/authentication operation, deployment or live activation occurred.
The actual supervisor, deadline/grace enforcement, observed termination, incomplete
attempt recovery, inactive-container removal and scheduled operation remain pending.

Transport review cleared 34ce7ba after 74 tests and five independent in-memory
framing/partial-send probes. Store review found an existing unsupported terminal
admission: a start-fenced `created` observation could acknowledge termination.
The initial candidate is NOT_READY. Four RED regressions demonstrated new/retained
receipt, reopened and historical-admission cases. Root added both new-write and
retained-receipt guards; never-started `created` observations remain valid. The
corrected focused suite passed 239 tests at 98% combined store/termination coverage;
central regression passed 1,051 with four optional age skips. Ruff, strict mypy
(448 files), expanded Bandit, lock and diff checks passed. Follow-up review is pending.
