"""Public listing snapshots establish prospective observations, never investments."""

import hashlib
import importlib
import json
import stat
from datetime import UTC, datetime, timedelta

import httpx
import pytest

NOW = datetime(2026, 10, 21, 14, 20, tzinfo=UTC)
NASDAQ_HEADER = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares"
)
OTHER_HEADER = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol"
)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.stock_universe")
    except ModuleNotFoundError:
        pytest.fail("stock universe importer is missing")


def bodies(nasdaq_rows=None, other_rows=None):
    nasdaq_rows = nasdaq_rows or ["ALFA|Fictional Alpha - Common Stock|Q|N|N|100|N|N"]
    other_rows = other_rows or ["BETA|Fictional Beta Common Shares|N|BETA|N|100|N|BETA"]
    return (
        (
            NASDAQ_HEADER
            + "\n"
            + "\n".join(nasdaq_rows)
            + "\nFile Creation Time: 1021202610:01|||||||\n"
        ).encode(),
        (
            OTHER_HEADER
            + "\n"
            + "\n".join(other_rows)
            + "\nFile Creation Time: 1021202610:01||||||\n"
        ).encode(),
    )


def parse(pair=None, **kwargs):
    return api().parse_stock_universe(*(pair or bodies()), captured_at=NOW, **kwargs)


def test_complete_two_source_snapshot_has_receipts_and_no_permanent_identity():
    result = parse()
    assert result.captured_at == result.available_at == NOW
    assert result.record_count == 2
    assert [row.symbol for row in result.records] == ["ALFA", "BETA"]
    assert all(row.research_eligible for row in result.records)
    assert all(
        row.permanent_security_id is None and row.issuer_domicile is None for row in result.records
    )
    assert all(row.us_listed for row in result.records)
    assert all(source.received_at == NOW for source in result.sources)
    assert all(source.declared_timestamp.tzinfo is None for source in result.sources)
    assert all(source.declared_timezone is None for source in result.sources)
    assert result.sources[0].body_sha256 == hashlib.sha256(bodies()[0]).hexdigest()
    assert (
        not result.source_qualified and not result.strategy_qualified and not result.live_authorized
    )
    assert parse().snapshot_hash == result.snapshot_hash
    assert (
        api().parse_stock_universe(*bodies(), captured_at=NOW + timedelta(seconds=1)).snapshot_hash
        != result.snapshot_hash
    )


@pytest.mark.parametrize(
    "name,kind",
    [
        ("Fictional Common Stock", "common_stock"),
        ("Fictional American Depositary Shares", "adr"),
        ("Fictional Depository Shares each representing Preferred Stock", "preferred"),
        ("Fictional Warrants", "warrant"),
        ("Fictional Rights", "right"),
        ("Fictional Units", "unit"),
        ("Fictional Income Trust", "ambiguous"),
    ],
)
def test_security_classification_never_equates_non_etf_with_common_stock(name, kind):
    row = parse(bodies([f"ALFA|{name}|Q|N|N|100|N|N"])).records[0]
    assert row.security_kind == kind
    assert row.research_eligible == (kind in ("common_stock", "adr"))
    assert row.classification_method == "listing_name_heuristic_v1"
    assert row.classification_uncertain == (kind == "ambiguous")


@pytest.mark.parametrize(
    "name",
    [
        "Fictional Income Strategies Fund Common Shares",
        "Fictional Diversified Income Fund Common Shares of Beneficial Interest",
        "Fictional Emerging Markets Fund, Inc. Common Stock",
    ],
)
def test_explicit_fund_common_shares_are_not_operating_stock_candidates(name):
    fund = parse(bodies([f"ALFA|{name}|Q|N|N|100|N|N"])).records[0]
    assert fund.security_kind == "fund"
    assert not fund.research_eligible
    reit = parse(bodies(["ALFA|Fictional Property Trust - Common Stock|Q|N|N|100|N|N"])).records[0]
    assert reit.security_kind == "common_stock" and reit.research_eligible


def test_issuer_name_does_not_override_explicit_security_description():
    common = parse(bodies(["ALFA|Preferred Fictional Bank - Common Stock|Q|N|N|100|N|N"])).records[
        0
    ]
    preferred = parse(bodies(["ALFA|Fictional Bank - Preferred Stock|Q|N|N|100|N|N"])).records[0]
    assert common.security_kind == "common_stock" and common.research_eligible
    assert preferred.security_kind == "preferred" and not preferred.research_eligible


@pytest.mark.parametrize("description", ["ADS", "ADS, each representing 10 ordinary shares"])
def test_ads_wrapper_is_not_relabelled_as_its_underlying_ordinary_shares(description):
    row = parse(bodies([f"ALFA|Fictional Group - {description}|Q|N|N|100|N|N"])).records[0]
    assert row.security_kind == "adr" and row.research_eligible


@pytest.mark.parametrize(
    "row,reason",
    [
        ("ALFA|Fictional Common Stock|Q|Y|N|100|N|N", "test_issue"),
        ("ALFA|Fictional Common Stock|Q|N|N|100|Y|N", "etf"),
        ("ALFA|Fictional Common Stock|Q|N|N|100|N|Y", "nextshares"),
        ("ALFA|Fictional Common Stock|Q|N|D|100|N|N", "financial_status_not_normal"),
    ],
)
def test_excluded_rows_remain_auditable_but_cannot_enter_research(row, reason):
    result = parse(bodies([row])).records[0]
    assert not result.research_eligible
    assert reason in result.ineligible_reasons


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.rsplit(b"File Creation", 1)[0],
        lambda b: b.rstrip(b"\n"),
        lambda b: b.replace(b"1021202610:01", b"1332202610:01"),
        lambda b: b.replace(b"|NextShares", b"|Unknown"),
        lambda b: b.replace(b"|Q|N|N|100|N|N", b"|Q|N|N|100|N"),
        lambda b: b.replace(b"|Q|N|N|100|N|N", b"|Q|Z|N|100|N|N"),
        lambda b: b + b"TRAILING\n",
        lambda b: b.replace(b"Fictional", b"Fictional\x00"),
    ],
)
def test_incomplete_or_malformed_source_denies_entire_snapshot(mutate):
    first, second = bodies()
    with pytest.raises(ValueError, match="stock_universe_invalid"):
        parse((mutate(first), second))


def test_duplicate_symbols_within_and_across_sources_are_not_silently_resolved():
    first = "ALFA|Fictional Alpha - Common Stock|Q|N|N|100|N|N"
    for pair in [
        bodies([first, first]),
        bodies(other_rows=["ALFA|Other Common Stock|N|ALFA|N|100|N|ALFA"]),
    ]:
        with pytest.raises(ValueError, match="stock_universe_invalid"):
            parse(pair)
    with pytest.raises(ValueError):
        api().parse_stock_universe(*bodies(), captured_at=NOW.replace(tzinfo=None))


def test_fetcher_bounds_urls_headers_timestamps_and_request_rate():
    ticks = [0.0]
    seen = []
    pair = bodies()

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200, content=pair[len(seen) - 1], headers={"content-type": "text/plain"}
        )

    def wait(seconds):
        ticks[0] += seconds

    with api().NasdaqStockUniverseFetcher(
        transport=httpx.MockTransport(handler),
        user_agent="StockResearch/1.0 (research@example.test)",
        clock=lambda: NOW + timedelta(seconds=ticks[0]),
        monotonic=lambda: ticks[0],
        sleep=wait,
    ) as client:
        result = client.capture()
    assert [str(request.url) for request in seen] == list(api().SOURCE_URLS)
    assert all(request.headers["accept-encoding"] == "identity" for request in seen)
    assert all(request.headers["user-agent"].startswith("StockResearch/") for request in seen)
    assert result.sources[0].received_at == NOW
    assert result.available_at == NOW + timedelta(seconds=1)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://attacker.invalid/"}),
        httpx.Response(200, content=b"x" * 101, headers={"content-type": "text/plain"}),
        httpx.Response(200, content=b"bad", headers={"content-type": "text/html"}),
        httpx.Response(200, content=b"", headers={"content-encoding": "gzip"}),
        httpx.Response(429),
    ],
)
def test_fetcher_rejects_redirects_oversize_bad_media_compression_and_errors(response):
    with (
        api().NasdaqStockUniverseFetcher(
            transport=httpx.MockTransport(lambda request: response),
            user_agent="StockResearch/1.0",
            max_bytes=100,
        ) as client,
        pytest.raises(ValueError, match="stock_universe_invalid"),
    ):
        client.capture()


def test_archive_private_original_bytes_and_atomic_hash_bound_receipt(tmp_path):
    tmp_path.chmod(0o700)
    result = parse()
    receipt = api().archive_stock_universe(result, tmp_path)
    raw = receipt.receipt_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == receipt.receipt_sha256
    saved = json.loads(raw)
    assert saved["snapshot_hash"] == result.snapshot_hash
    assert len(saved["sources"]) == 2
    assert [path.read_bytes() for path in receipt.body_paths] == list(bodies())
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in (*receipt.body_paths, receipt.receipt_path)
    )
    assert not list(tmp_path.glob(".pending-*"))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        api().archive_stock_universe(result, tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_archive_rejects_nonprivate_or_symlink_root_and_mutated_records(tmp_path):
    result = parse()
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError):
        api().archive_stock_universe(result, tmp_path)
    tmp_path.chmod(0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        api().archive_stock_universe(result, linked)
    object.__setattr__(result.records[0], "research_eligible", True)
    object.__setattr__(result.records[0], "security_kind", "warrant")
    with pytest.raises(ValueError):
        api().archive_stock_universe(result, tmp_path)


def test_equality_equivalent_boolean_tampering_is_rejected(tmp_path):
    result = parse()
    object.__setattr__(result.records[0], "research_eligible", 1)
    tmp_path.chmod(0o700)
    with pytest.raises(ValueError, match="stock_universe_invalid"):
        api().archive_stock_universe(result, tmp_path)


def test_source_count_must_remain_an_exact_integer():
    result = parse()
    object.__setattr__(result.sources[0], "record_count", True)
    with pytest.raises(ValueError, match="stock_universe_invalid"):
        _ = result.snapshot_hash


def test_fetcher_enforces_total_response_deadline_even_with_injected_transport():
    ticks = [0.0]
    seen = []

    def handler(request):
        seen.append(request)
        ticks[0] += 11
        return httpx.Response(
            200, content=bodies()[len(seen) - 1], headers={"content-type": "text/plain"}
        )

    with (
        api().NasdaqStockUniverseFetcher(
            transport=httpx.MockTransport(handler),
            user_agent="StockResearch/1.0",
            monotonic=lambda: ticks[0],
            timeout_seconds=10,
        ) as client,
        pytest.raises(ValueError, match="stock_universe_invalid"),
    ):
        client.capture()
    assert len(seen) == 1
