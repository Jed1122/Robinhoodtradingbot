# Individual-stock research verification — 2026-10-21

This is a development checkpoint, not deployment readiness, strategy qualification or
live authorization. No real-money orders, reviews, cancellations or transfers occurred.
The existing deployed paused services were unchanged during this work.

## Official source observations

A separately authorized dedicated research browser grant captured 83 selected-server
tool declarations. A new process then reused the encrypted saved credential without a
browser. The credential remains trading-capable despite local research restrictions.
Natural expiry, refresh rotation/persistence and owner-revoked denial remain unverified.

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
periods while explicitly preserving the five unavailable companies. One non-interpolated
historical row violated its OHLC range, so the strict history normalization correctly
denied that batch. The bad row remains in the original capture; no price was repaired,
zero-filled or silently accepted. No qualifying strategy result follows.

A separate public Nasdaq directory capture retained 13,293 rows and 5,176 tentatively
eligible common-stock listings. Name-based security classification remains conservative
and heuristic. Current membership is not historical survivorship-free membership.

## Engineering evidence

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

A broader central regression and final static checks are recorded in the ongoing
implementation ledger. Earlier full-suite evidence applies to an older executable;
it is not silently reused as final verification of this checkpoint.

## Outstanding work

The research acquisition/cache scheduler is not yet a verified persistent background
service. Authentication lifecycle recovery, company dossiers, complete raw-session
liquidity, stock point-in-time datasets, out-of-sample strategy/cost/tax validation,
nonempty broker reconciliation and encrypted operational backup/watchdog installation
remain outstanding. No stock strategy has qualified for capital allocation. There is
no mandatory paper waiting period; live activation still requires separate authorization.
