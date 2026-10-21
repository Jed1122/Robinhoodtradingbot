# Current individual-stock discovery

`market_data.stock_universe` provides a public listing ingestion seam for the
individual-stock research project. It performs no investment selection, broker
access, credential operation, strategy promotion or order submission. All source,
strategy and live qualification flags remain false.

The fixed public sources are Nasdaq Trader's
[Nasdaq-listed directory](https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt)
and [other-listed directory](https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt).
The [official definitions](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)
describe listing, test, financial-status, ETF, NextShares and file-creation fields.
No subscription, paid provider, authenticated endpoint or added recurring service
is introduced. Public accessibility does not establish redistribution rights.

## Input and classification contract

`parse_stock_universe(nasdaq_body, other_body, captured_at=utc_receipt)` is pure.
It requires both exact eight-column formats, one final creation footer and final
newline, valid field values and bounded bodies/row counts. Duplicate symbols
within either source or across sources reject the entire snapshot, including
identical duplicates. Missing columns, malformed dates, control characters,
truncated footers and trailing records reject. This detects structural damage;
it cannot certify that Nasdaq supplied every listing.

Each immutable snapshot retains both original bodies, SHA-256 hashes, source URLs,
individual receipt clocks, original creation footers, parsed declared timestamps
and source record counts. The footer's timezone is unspecified and stays unknown;
it is never converted into a claimed historical UTC availability. Snapshot
availability is the final capture clock, no earlier than either source receipt.
Parser/classification version and receipt identities bind the snapshot hash.

Every row remains auditable. Test issues, ETFs and NextShares are excluded from
research eligibility, as are nonnormal Nasdaq financial-status codes. Listing-name
heuristics distinguish explicit common/ordinary stock, ADRs, preferred shares,
warrants, rights, units and explicitly named funds. Named funds remain excluded
even when their shares are described as common stock. Preferred/warrant/right/unit descriptions take
precedence over embedded references to common shares. Ambiguous descriptions
remain ineligible with an explicit reason and uncertainty flag. Unknown
other-listed exchange codes also remain ineligible. These labels are research
discovery hints rather than authenticated security-master classifications.
When an explicit ` - ` security description exists, issuer-name words such as
"Preferred" do not override it. ADR/ADS wrappers remain distinct from the
underlying ordinary shares. These heuristics cannot identify every closed-end
fund or other nonoperating vehicle without a separately verified security master.

`ETF=N` never labels every remaining security common stock. An eligible row is
not an investment recommendation or permission to trade. US listing does not
establish issuer domicile. `permanent_security_id` and `issuer_domicile` remain
`None`: symbols and names are not permanent identities. Corporate actions,
multiple share classes, issuer/CIK resolution and broker instrument identity
remain separate integration work. The other-listed format does not provide a
Nasdaq financial-status field; its absence is not evidence of a healthy issuer.

## Explicit fetch and private archive

`NasdaqStockUniverseFetcher` requires an injected `httpx.BaseTransport` and an
identifying application/version User-Agent. It has no default transport and no
credential input. It requests only the two fixed HTTPS URLs, disables environment
proxies and redirect following, accepts only uncompressed plain text and HTTP 200,
enforces body and declared-length bounds, and applies socket timeouts plus elapsed
response checks. It performs no retry. Response deadlines are checked when the
transport returns headers/chunks; the injected transport must honor its supplied
socket timeout. A malicious or broken injected transport cannot be preempted by
this synchronous wrapper.

One shared fetcher serializes captures and spaces request starts at least one
second apart. An integrating service must impose an aggregate limiter when using
multiple instances/processes. Defaults are at most 2 MB per source and 10 seconds
per response; callers may lower the byte bound or choose a timeout up to 30 seconds.
No source call occurred during implementation or tests: HTTP tests use synthetic
`httpx.MockTransport` responses.

`archive_stock_universe(snapshot, private_root)` requires an existing nonsymlink,
caller-owned directory with mode `0700`. It opens it with `O_NOFOLLOW`, creates
private temporary files with `O_EXCL`/`0600`, flushes original bytes, and publishes
them using atomic exclusive links. It then publishes the hash-addressed JSON
receipt as the commit marker. Both source files become durable before receipt
publication; an existing target is never overwritten. Readers must ignore bodies
without a receipt. Ordinary failures clean only files created by this invocation;
a process or host crash can leave orphan original bodies. No archive loader,
retention deletion, historical membership reconstruction or automatic capture
job is introduced here.

## Next steps toward continuous stock research

The goal is broad individual-stock research operating continuously, with numerical
screening before deeper investigation. The integrating owner next connects these
snapshots to stable issuer/security resolution; the existing canonical screening
criteria; timestamped price, market-cap and complete-session dollar-volume inputs;
then a bounded queue for SEC filings, financials, earnings and issuer research on
the strongest numerical candidates. Missing or stale facts must remain unavailable.
Refresh listing snapshots daily and retain additions/removals prospectively;
research jobs can run around the clock without claiming stock markets trade
continuously or repeatedly polling unchanged inputs.

Freeze complete stock-strategy and portfolio evaluation contracts separately,
including costs, distributions, corporate actions, lifecycle/reinvestment,
chronological validation and matched benchmarks. A current listing snapshot is
not a historical universe free of survivorship bias and cannot qualify an old
stock backtest. Existing ETF reports stay preserved as historical validation or
optional benchmark/diversification context. Source qualification, unattended
broker authentication, deployment readiness and explicit live authorization
remain independent requirements.
