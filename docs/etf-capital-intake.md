# Capital-research daily intake

Task4 is in progress. Credential-free components now include a separately
versioned request/page parser for SPY, QQQ, IWM, SHY and IEF, and private supplied-
byte archive publication/verification. Neither is an authenticated capture
transport, complete historical dataset or economic-qualification factory.

`CapitalDailyRequest` uses a symbol-bound single-stock daily-bars path. Query
construction reuses the existing raw-SIP/USD/asof-minus/ascending request syntax.
The old SPY request, page, record and archive hashes are unchanged. Original body
bytes are hashed directly; no symbol rewriting is used to reuse SPY parsing.
The underlying native bar retains its origin hash, page/row identity and exact
Decimal and nanosecond observations. A distinct wrapper binds the actual symbol.

Pages are limited to1MiB,10,000rows and128pages per supplied chain, preserving
existing native bounds. Strict keys, hashes, symbol/currency, ranges and monotonic
timestamps are checked. Cursor loops, extra pages after terminal pagination,
duplicate session timestamps and changed requests deny. Parsing exceptions use
the sanitized native-invalid reason. Financial records have private representations.

The assessment establishes **pagination completeness only**. It cannot establish
that every expected trading session exists, that corporate actions/distributions
are complete, or that the observed daily aggregation timestamp is an original
publication time. All source/promotion flags remain false. Zero observations
and incomplete pagination stay explicit. This component uses fabricated fixtures
only and adds no credentials, network access or acquisitions.

## Private raw archives

`write_capital_daily_archive` validates all supplied bodies and declared receipt
times before publishing anything. It reuses the existing descriptor-relative,
no-follow, current-owner0700directory/0600file primitives outside the repository.
Original bodies are content-addressed and never replaced; the canonical new
manifest is published only after the raw bodies. Exact retries verify existing
bytes and directory durability. Failure can leave complete original blobs but
never reports successful publication or deletes originals to hide uncertainty.

`read_capital_daily_archive` checks private modes, manifest/body hashes, exact
schema and request identity, then reparses the originals and reconstructs the
canonical manifest. Symlinks, changed bytes, impossible receipt clocks and
qualification flags deny. Receipt timestamps are **supplied declarations**, not
authenticated collection clocks, original publication times or order timings.
There is no credential field or production-ledger access. Incomplete captures
are retained as incomplete, without becoming qualified datasets.

## API references and outstanding checks

[Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars)
and [the official stock request model](https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html)
document historical request parameters. [The official historical-data guide](https://alpaca.markets/learn/fetch-historical-data)
describes access to data older than15minutes; this is documentation, not verified
access for this account or a fresh execution quote. Do not change subscriptions,
silently substitute IEX, or use delayed history as current SIP/NBBO evidence.

## Session inventory

`capital_daily_inventory` binds supplied archives to the fixed five-symbol
universe, exact request window and declared calendar. It rejects duplicate
symbols, unexpected sessions and non-midnight New York daily stamps. Output
distinguishes an absent archive (unknown counts) from a supplied empty response
(zero observed rows). Pagination and missing-session counts remain separate.
The hash is independent of archive input ordering.

Split and distribution counts remain unknown because this API receives neither
kind of evidence. Calendar counts never establish source acceptance; strategy
projection, qualification and promotion remain false. This is an inventory,
not an accepted dataset or feature normalizer.

Next are split/distribution/availability dataset controls
and a separately authorized bounded capture composition. These must be verified
and frozen before the walk-forward
strategy study. No genuine economic result, qualifying paper/shadow behavior or
broker/runtime readiness follows from this parser.

## Supplied action facts and feature basis

The new `CapitalActionArchive` preserves per-symbol supplied split and cash
distribution observations, exact windows, source hashes and declared receipt
times. `None` is unknown; an empty tuple is zero observed rows, not complete
coverage. Ex-date entitlement, record date and payment date are separate. Unknown
announcement/correction timestamps remain unknown. These contracts are not an
authenticated Alpaca corporate-action parser or a verified reconciliation.

`capital_split_feature_bars` creates a separately hashed research projection of
completed declared sessions. It requires explicit action inputs, consistent
windows, completed pagination and every prior session. Split effectivity and
distribution ex-dates must have declared calendar sessions. Split factors apply
only through the as-of session; raw assumed execution OHLC remain separate and
captured bytes unchanged. Dividend cash is not subtracted from feature prices
or automatically reinvested. Account entitlement/settlement and total-return
rotation remain future composition work.

Session-close availability and latest-vintage action completeness are research
assumptions, not original publication evidence. All qualification, promotion and
execution flags remain false. No actual source capture or economic evaluation
has been performed by these fixtures.

## Policy-bound supplied development dataset

`build_capital_dataset` restores the exact canonical research configuration via
the existing loader and requires the five policy symbols, consistent windows,
complete pagination, all declared sessions and explicit action inputs. Inputs
are sorted by canonical universe order before hashing. Dataset identifiers bind
configuration, calendar, archive and action identities; missing or duplicated
symbols and altered flags deny. The aggregate input is bounded to20,000bars.

This version accepts only adaptive development dates before2024. It cannot
relabel2024–2025 as untouched or stand in for a prospective final-test contract.
Declared calendar completeness and supplied action completeness still are not
authenticated provider evidence. Its source, promotion and execution flags are
permanently false.

`capital_dataset_features` returns a fresh as-of slice; it does not reuse a
terminal split-normalized series for earlier decisions. Unavailable requested
sessions deny rather than being clipped. Raw OHLC quality is checked during
construction. No forward fill, execution quote, original publication time or
automatic cash settlement is invented. Strategy/account/total-return composition
and actual-source acquisition remain unfinished.
